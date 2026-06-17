"""
Cove Proxy Server — FastAPI proxy for Jellyfin / Streamyfin.

Endpoints
─────────
GET /health              Health check: domain, session state, cache size.
GET /api/downloads/status Get the current download queue status.
POST /api/downloads      Queue a new download.
GET /play.m3u8           Rewritten master HLS M3U8 (all child URLs go through proxy).
GET /proxy_child.m3u8   Proxy for child (quality-level / audio / subtitle) M3U8 files.
GET /enc.key             Proxies AES-128 encryption keys from Vixcloud.
"""

import asyncio
import logging
import re
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from typing import Any, AsyncIterator, Optional

import httpx
from pydantic import BaseModel
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware

from shared import config
from shared.sc_scraper import SCScraper
from proxy.m3u8_rewriter import rewrite_master_m3u8, rewrite_child_m3u8
from proxy.downloader import download_worker, download_queue, current_download

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
# Global Configuration
# ──────────────────────────────────────────────────────────────────────────────
VIXCLOUD_REFERER = "https://vixcloud.co/"

# ──────────────────────────────────────────────────────────────────────────────
# Global state
# ──────────────────────────────────────────────────────────────────────────────

scraper = SCScraper()
_scraper_lock = (
    asyncio.Lock()
)  # Serialises all scraper calls (sync client, not thread-safe)

# TTL cache:  (title_id, episode_id) → (m3u8_url, cached_at)
_stream_cache: dict[tuple[int, int], tuple[str, datetime]] = {}
_CACHE_TTL = timedelta(minutes=4)  # Vixcloud tokens expire after ~5 minutes


async def _get_stream_url(title_id: int, episode_id: int) -> Optional[str]:
    """Fetch the real Vixcloud stream URL, using TTL cache."""
    now = datetime.now()
    if (title_id, episode_id) in _stream_cache:
        url, cached_at = _stream_cache[(title_id, episode_id)]
        if now - cached_at < _CACHE_TTL:
            return url

    async with _scraper_lock:
        try:
            titles = await asyncio.to_thread(scraper.search, str(title_id))
            if not titles:
                return None

            slug = titles[0].get("slug")
            await asyncio.to_thread(scraper.get_title_details, title_id, slug)

            iframe_url = f"{scraper.active_domain}/it/iframe/{title_id}?episode_id={episode_id}&next_episode=1"
            iframe_resp = await asyncio.to_thread(
                scraper._get,
                iframe_url,
                headers={
                    "Referer": f"{scraper.active_domain}/it/watch/{title_id}?e={episode_id}"
                },
            )

            embed_match = re.search(
                r"src=[\"\']+(https://vixcloud\.co/embed/[^\"\']+)[\"\']",
                iframe_resp.text,
            )
            if not embed_match:
                return None

            embed_url = embed_match.group(1).replace("&amp;", "&")
            vix_resp = await asyncio.to_thread(
                scraper._get,
                embed_url,
                headers={"Referer": f"{scraper.active_domain}/"},
            )

            token_match = re.search(r"\'token\': \'([^\']+)\'", vix_resp.text)
            expires_match = re.search(r"\'expires\': \'([^\']+)\'", vix_resp.text)
            playlist_match = re.search(
                r"url:\s*\'(https://vixcloud\.co/playlist/\d+)\'", vix_resp.text
            )

            if not (token_match and expires_match and playlist_match):
                return None

            master_url = f"{playlist_match.group(1)}?ub=1&token={token_match.group(1)}&expires={expires_match.group(1)}"

            _stream_cache[(title_id, episode_id)] = (master_url, now)
            return master_url

        except Exception as e:
            log.error(f"Error fetching stream URL: {e}")
            return None


# ──────────────────────────────────────────────────────────────────────────────
# Lifespan (startup / shutdown)
# ──────────────────────────────────────────────────────────────────────────────


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    log.info("Starting Cove Proxy...")
    await asyncio.to_thread(scraper.init_session)
    log.info(f"Active domain: {scraper.active_domain}")

    worker_task = asyncio.create_task(download_worker(_get_stream_url))

    yield

    worker_task.cancel()
    log.info("Shutting down Cove Proxy...")


app = FastAPI(title="Cove Proxy", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ──────────────────────────────────────────────────────────────────────────────
# API Models
# ──────────────────────────────────────────────────────────────────────────────


class DownloadRequest(BaseModel):
    title_id: int
    episode_id: int
    type: str  # "tv" or "movie"
    relative_path: str


# ──────────────────────────────────────────────────────────────────────────────
# Routes: API
# ──────────────────────────────────────────────────────────────────────────────


@app.get("/health")
async def health_check() -> dict[str, Any]:
    return {
        "status": "ok",
        "domain": scraper.active_domain,
        "session_valid": scraper._session_valid,
        "cache_size": len(_stream_cache),
    }


@app.get("/api/downloads/status")
async def get_download_status() -> dict[str, Any]:
    return {
        "active_download": current_download if current_download["active"] else None,
        "queue_size": download_queue.qsize(),
    }


@app.post("/api/downloads")
async def queue_download(req: DownloadRequest) -> dict[str, str]:
    await download_queue.put(req.dict())
    return {"status": "queued"}


# ──────────────────────────────────────────────────────────────────────────────
# Routes: Proxy
# ──────────────────────────────────────────────────────────────────────────────


@app.get("/play.m3u8")
async def play_m3u8(title_id: int, episode_id: int, request: Request) -> Response:
    """
    Returns the rewritten Master M3U8.
    """
    m3u8_url = await _get_stream_url(title_id, episode_id)
    if not m3u8_url:
        raise HTTPException(
            status_code=404, detail="Stream URL not found or extraction failed."
        )

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                m3u8_url,
                headers={"Referer": VIXCLOUD_REFERER, "User-Agent": config.USER_AGENT},
            )
        if resp.status_code != 200:
            raise HTTPException(
                status_code=resp.status_code, detail="Failed to fetch master M3U8."
            )

        m3u8_text = resp.text
        proxy_base_url = f"{request.url.scheme}://{request.url.netloc}"
        rewritten_m3u8 = rewrite_master_m3u8(m3u8_text, proxy_base_url, title_id)

        return Response(
            content=rewritten_m3u8, media_type="application/vnd.apple.mpegurl"
        )

    except httpx.RequestError as exc:
        log.error(f"Error fetching master M3U8: {exc}")
        raise HTTPException(
            status_code=502, detail="Error communicating with upstream stream server."
        )


@app.get("/proxy_child.m3u8")
async def proxy_child_m3u8(title_id: int, child_url: str, request: Request) -> Response:
    """
    Proxy a child M3U8 (video quality level, audio track, or subtitle track).
    """
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                child_url,
                headers={"Referer": VIXCLOUD_REFERER, "User-Agent": config.USER_AGENT},
            )
        if resp.status_code != 200:
            raise HTTPException(
                status_code=resp.status_code, detail="Failed to fetch child M3U8."
            )

        proxy_base_url = f"{request.url.scheme}://{request.url.netloc}"
        rewritten_m3u8 = rewrite_child_m3u8(resp.text, child_url, proxy_base_url)
        return Response(
            content=rewritten_m3u8, media_type="application/vnd.apple.mpegurl"
        )

    except httpx.RequestError as exc:
        log.error(f"Error proxying child M3U8: {exc}")
        raise HTTPException(
            status_code=502, detail="Error communicating with upstream server."
        )


@app.get("/enc.key")
async def proxy_enc_key(key_url: str) -> Response:
    """
    Proxy an AES-128 encryption key request.
    """
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(
                key_url,
                headers={"Referer": VIXCLOUD_REFERER, "User-Agent": config.USER_AGENT},
            )
        if resp.status_code != 200:
            raise HTTPException(
                status_code=resp.status_code, detail="Failed to fetch key."
            )
        return Response(content=resp.content, media_type="application/octet-stream")
    except httpx.RequestError as exc:
        log.error(f"Error fetching encryption key: {exc}")
        raise HTTPException(status_code=502, detail="Error fetching encryption key.")
