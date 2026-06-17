"""
Cove Proxy Server — FastAPI proxy for Jellyfin / Streamyfin.

Endpoints
─────────
GET /health              Health check: domain, session state, cache size.
GET /stream.mkv          ffmpeg-piped MKV (video + audio + all subtitles).
                         Used by Jellyfin .strm files and Streamyfin offline downloads.
GET /play.m3u8           Rewritten master HLS M3U8 (all child URLs go through proxy).
                         Kept for compatibility with HLS-native players.
GET /proxy_child.m3u8   Proxy for child (quality-level / audio / subtitle) M3U8 files.
                         Resolves relative segment paths and proxies the enc.key.
GET /enc.key             Proxies AES-128 encryption keys from Vixcloud.
"""

import asyncio
import logging
import re
import urllib.parse
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from typing import Any, AsyncIterator, Optional
import os

import httpx
from pydantic import BaseModel
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from shared import config
from shared.sc_scraper import SCScraper

# ──────────────────────────────────────────────────────────────────────────────
# Logging
# ──────────────────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.DEBUG if config.DEBUG else logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("cove.proxy")

# ──────────────────────────────────────────────────────────────────────────────
# Global state
# ──────────────────────────────────────────────────────────────────────────────

scraper = SCScraper()
_scraper_lock = asyncio.Lock()  # Serialises all scraper calls (sync client, not thread-safe)

# TTL cache:  (title_id, episode_id) → (m3u8_url, cached_at)
_stream_cache: dict[tuple[int, int], tuple[str, datetime]] = {}
_CACHE_TTL = timedelta(minutes=4)  # Vixcloud tokens expire after ~5 minutes

VIXCLOUD_REFERER = "https://vixcloud.co/"

# Download Queue and Status
download_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
current_download: dict[str, Any] = {
    "active": False,
    "relative_path": "",
    "absolute_path": "",
}

async def download_worker() -> None:
    """Background task to process downloads sequentially."""
    global current_download
    while True:
        try:
            task = await download_queue.get()
            title_id = task["title_id"]
            episode_id = task["episode_id"]
            media_type = task["type"]
            rel_path = task["relative_path"]
            
            base_path = config.SERVER_SHOWS_PATH if media_type == "tv" else config.SERVER_MOVIES_PATH
            out_path = os.path.join(base_path, rel_path)
            os.makedirs(os.path.dirname(out_path), exist_ok=True)
            
            part_path = out_path + ".part"
            current_download["active"] = True
            current_download["relative_path"] = rel_path
            current_download["absolute_path"] = out_path  # keep base path for tracking

            log.info(f"[DOWNLOAD] Extracting URL for {title_id} / {episode_id}")
            m3u8_url = await _get_stream_url(title_id, episode_id)
            if not m3u8_url:
                log.error(f"[DOWNLOAD] Failed to extract URL for {out_path}")
                download_queue.task_done()
                continue
                
            log.info(f"[DOWNLOAD] Starting ffmpeg to {part_path}")
            
            ffmpeg_cmd = [
                "ffmpeg", "-y", "-v", "error", 
                "-allowed_extensions", "ALL", 
                "-protocol_whitelist", "file,http,https,tcp,tls,crypto",
                "-headers", f"Referer: {VIXCLOUD_REFERER}\r\n",
                "-i", m3u8_url,
                "-map", "0:v:0", "-map", "0:a", "-map", "0:s?",
                "-c:v", "copy", "-c:a", "aac", "-c:s", "copy",
                "-f", "matroska", part_path
            ]
            
            proc = await asyncio.create_subprocess_exec(*ffmpeg_cmd)
            await proc.wait()
            
            if proc.returncode == 0:
                os.rename(part_path, out_path)
                log.info(f"[DOWNLOAD] ✓ Success: {out_path}")
            else:
                log.error(f"[DOWNLOAD] ✗ Failed with code {proc.returncode}: {out_path}")
                if os.path.exists(part_path):
                    os.remove(part_path)
                
            current_download["active"] = False
            download_queue.task_done()
        except asyncio.CancelledError:
            break
        except Exception as e:
            log.error(f"[DOWNLOAD] Worker error: {e}")
            current_download["active"] = False
            try:
                download_queue.task_done()
            except ValueError:
                pass


# ──────────────────────────────────────────────────────────────────────────────
# Lifespan (startup / shutdown)
# ──────────────────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    log.info("Initializing SCScraper session…")
    await asyncio.to_thread(scraper.init_session)
    log.info(f"Active domain: {scraper.active_domain}")
    
    worker_task = asyncio.create_task(download_worker())
    
    yield
    
    log.info("Shutting down — closing HTTP client…")
    worker_task.cancel()
    scraper.close()


# ──────────────────────────────────────────────────────────────────────────────
# App
# ──────────────────────────────────────────────────────────────────────────────

app = FastAPI(title="Cove Proxy", version="3.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ──────────────────────────────────────────────────────────────────────────────
# Stream URL cache helper
# ──────────────────────────────────────────────────────────────────────────────

async def _get_stream_url(title_id: int, episode_id: int) -> Optional[str]:
    """
    Return a valid master M3U8 URL for the given title/episode, using an
    in-memory TTL cache to avoid redundant extractions.

    Thread-safety: all scraper calls are serialised by _scraper_lock so that
    the synchronous httpx.Client is never used from two threads at once.
    """
    cache_key = (title_id, episode_id)

    # Fast path: valid cached entry (no lock needed for a pure read)
    entry = _stream_cache.get(cache_key)
    if entry and datetime.now() - entry[1] < _CACHE_TTL:
        log.debug(f"Cache hit — ({title_id}, {episode_id})")
        return entry[0]

    async with _scraper_lock:
        # Double-check after acquiring the lock (another coroutine may have
        # already populated the cache while we were waiting)
        entry = _stream_cache.get(cache_key)
        if entry and datetime.now() - entry[1] < _CACHE_TTL:
            return entry[0]

        log.info(f"Extracting stream URL — title={title_id} episode={episode_id}")
        url = await asyncio.to_thread(scraper.get_stream_url, title_id, episode_id)

        if not url:
            log.warning("Extraction failed — re-initializing session and retrying…")
            await asyncio.to_thread(scraper.init_session)
            url = await asyncio.to_thread(scraper.get_stream_url, title_id, episode_id)

        if url:
            _stream_cache[cache_key] = (url, datetime.now())
            log.info(f"Cached — ({title_id}, {episode_id})")

        return url


# ──────────────────────────────────────────────────────────────────────────────
# Endpoints
# ──────────────────────────────────────────────────────────────────────────────

@app.get("/health")
async def health() -> dict[str, Any]:
    """Return server status, active domain, and session age."""
    age: Optional[float] = None
    if scraper._last_init:
        age = round((datetime.now() - scraper._last_init).total_seconds(), 1)
    return {
        "status": "ok",
        "domain": scraper.active_domain,
        "session_valid": scraper._session_valid,
        "session_age_seconds": age,
        "cache_entries": len(_stream_cache),
        "download_queue_size": download_queue.qsize(),
    }


# ─── /api/download ────────────────────────────────────────────────────────────

class DownloadRequest(BaseModel):
    title_id: int
    episode_id: int
    type: str
    relative_path: str

@app.post("/api/download")
async def queue_download(req: DownloadRequest) -> dict[str, str]:
    """Queue a media file for background downloading via ffmpeg."""
    await download_queue.put(req.model_dump())
    log.info(f"Queued download: {req.relative_path} (Queue size: {download_queue.qsize()})")
    return {"status": "queued"}

@app.get("/api/downloads/status")
async def download_status() -> dict[str, Any]:
    """Return the current download status and queue size."""
    size_mb = 0.0
    if current_download["active"]:
        part_path = current_download["absolute_path"] + ".part"
        if os.path.exists(part_path):
            size_mb = os.path.getsize(part_path) / (1024 * 1024)
        
    return {
        "queue_size": download_queue.qsize(),
        "current": {
            "active": current_download["active"],
            "relative_path": current_download["relative_path"],
            "downloaded_mb": round(size_mb, 2)
        }
    }


@app.get("/health")
async def health_check() -> dict[str, str]:
    """Health check for the proxy server."""
    return {"status": "ok"}


@app.get("/play.m3u8")
async def play_m3u8(title_id: int, episode_id: int, request: Request) -> Response:
    """
    Fetch the master HLS M3U8 and rewrite all child playlist URIs to route
    through /proxy_child.m3u8 on this server.

    Handles:
    - Absolute URL stream lines  (video quality playlists)
    - URI="" attributes in tags  (#EXT-X-MEDIA audio / subtitle tracks)
    """
    m3u8_url = await _get_stream_url(title_id, episode_id)
    if not m3u8_url:
        raise HTTPException(status_code=404, detail="Stream not found or extraction failed.")

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(m3u8_url, headers={"Referer": VIXCLOUD_REFERER})
        if resp.status_code != 200:
            raise HTTPException(status_code=resp.status_code, detail="Failed to fetch master M3U8.")

        proxy_base = str(request.base_url).rstrip("/")
        modified = _rewrite_master_m3u8(resp.text, proxy_base)
        return Response(content=modified, media_type="application/vnd.apple.mpegurl")

    except httpx.RequestError as exc:
        log.error(f"Error fetching master M3U8: {exc}")
        raise HTTPException(status_code=502, detail=str(exc))


# ─── /proxy_child.m3u8 ───────────────────────────────────────────────────────

@app.get("/proxy_child.m3u8")
async def proxy_child_m3u8(url: str, request: Request) -> Response:
    """
    Proxy a child M3U8 (video quality level, audio track, or subtitle track).

    Transforms applied:
    - Relative segment paths → absolute Vixcloud URLs
    - #EXT-X-KEY URI → routed through /enc.key on this server
    """
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(url, headers={"Referer": VIXCLOUD_REFERER})
        if resp.status_code != 200:
            raise HTTPException(status_code=resp.status_code, detail="Failed to fetch child M3U8.")

        proxy_base = str(request.base_url).rstrip("/")
        segment_base = url.rsplit("/", 1)[0]
        modified = _rewrite_child_m3u8(resp.text, segment_base, proxy_base)
        return Response(content=modified, media_type="application/vnd.apple.mpegurl")

    except httpx.RequestError as exc:
        log.error(f"Error fetching child M3U8: {exc}")
        raise HTTPException(status_code=502, detail=str(exc))


# ─── /enc.key ────────────────────────────────────────────────────────────────

@app.get("/enc.key")
async def proxy_enc_key(url: str) -> Response:
    """
    Proxy an AES-128 encryption key from Vixcloud.

    Encryption key URIs in child M3U8 files are rewritten to point here so
    that the player does not need to add custom Referer headers for key fetches.
    """
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url, headers={"Referer": VIXCLOUD_REFERER})
        if resp.status_code != 200:
            raise HTTPException(status_code=resp.status_code, detail="Failed to fetch encryption key.")
        return Response(content=resp.content, media_type="application/octet-stream")

    except httpx.RequestError as exc:
        log.error(f"Error fetching enc.key: {exc}")
        raise HTTPException(status_code=502, detail=str(exc))


# ──────────────────────────────────────────────────────────────────────────────
# M3U8 rewriting helpers
# ──────────────────────────────────────────────────────────────────────────────

def _rewrite_master_m3u8(m3u8_text: str, proxy_base: str) -> str:
    """
    Rewrite a master M3U8 so every child playlist URI is routed through
    /proxy_child.m3u8 on this server.

    Handles:
      • Bare absolute URL lines (video stream playlist references)
      • URI="…" attributes inside tag lines (#EXT-X-MEDIA, #EXT-X-I-FRAME-STREAM-INF …)
    """
    lines = m3u8_text.splitlines()
    out: list[str] = []

    for line in lines:
        stripped = line.strip()

        if not stripped:
            out.append(line)
            continue

        # ── Bare absolute URL → proxy child ──────────────────────────────────
        if stripped.startswith("http"):
            encoded = urllib.parse.quote(stripped, safe="")
            out.append(f"{proxy_base}/proxy_child.m3u8?url={encoded}")
            continue

        # ── URI="" attribute inside a tag line ────────────────────────────────
        if stripped.startswith("#") and 'URI="' in stripped:
            def _replace_uri(match: re.Match) -> str:  # noqa: E306
                original = match.group(1)
                encoded = urllib.parse.quote(original, safe="")
                return f'URI="{proxy_base}/proxy_child.m3u8?url={encoded}"'

            line = re.sub(r'URI="([^"]+)"', _replace_uri, line)

        out.append(line)

    return "\n".join(out)


def _rewrite_child_m3u8(m3u8_text: str, segment_base: str, proxy_base: str) -> str:
    """
    Rewrite a child M3U8:
      • #EXT-X-KEY URI  → proxied through /enc.key (handles relative and absolute URIs)
      • Relative segment paths → absolute Vixcloud URLs
      • Absolute segment paths that start with '/' → prefixed with vixcloud.co host
    """
    lines = m3u8_text.splitlines()
    out: list[str] = []

    for line in lines:
        stripped = line.strip()

        if not stripped:
            out.append(line)
            continue

        # ── #EXT-X-KEY: proxy the encryption key URI ─────────────────────────
        if stripped.startswith("#EXT-X-KEY") and "URI=" in stripped:
            def _replace_key_uri(match: re.Match) -> str:  # noqa: E306
                key_uri = match.group(1)
                # Resolve relative key URIs to an absolute Vixcloud URL
                if key_uri.startswith("/"):
                    key_uri = f"https://vixcloud.co{key_uri}"
                elif not key_uri.startswith("http"):
                    key_uri = f"{segment_base}/{key_uri}"
                encoded = urllib.parse.quote(key_uri, safe="")
                return f'URI="{proxy_base}/enc.key?url={encoded}"'

            line = re.sub(r'URI="([^"]+)"', _replace_key_uri, line)
            out.append(line)
            continue

        # ── Non-comment lines: make segment paths absolute ────────────────────
        if not stripped.startswith("#"):
            if stripped.startswith("http"):
                pass  # Already absolute, keep as-is
            elif stripped.startswith("/"):
                line = f"https://vixcloud.co{stripped}"
            else:
                line = f"{segment_base}/{stripped}"

        out.append(line)

    return "\n".join(out)


# ──────────────────────────────────────────────────────────────────────────────
# Entry point (for direct execution)
# ──────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "proxy:app",
        host="0.0.0.0",
        port=config.PROXY_SERVER_PORT,
        reload=False,
    )
