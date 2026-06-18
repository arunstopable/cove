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
from fastapi.responses import StreamingResponse
from starlette.background import BackgroundTask
from fastapi.middleware.cors import CORSMiddleware

from shared import config
from shared.sc_scraper import SCScraper
from proxy.m3u8_rewriter import rewrite_master_m3u8, rewrite_child_m3u8
from proxy.downloader import download_worker, download_queue, active_downloads

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
            master_url = await asyncio.to_thread(scraper.get_stream_url, title_id, episode_id)
            if master_url:
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

    worker_tasks = [
        asyncio.create_task(download_worker(i, _get_stream_url))
        for i in range(config.MAX_CONCURRENT_DOWNLOADS)
    ]

    yield

    for task in worker_tasks:
        task.cancel()
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
    episode_id: Optional[int] = None
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
    # Extract the relative_path from items currently in the queue
    items = []
    for item in list(download_queue._queue):
        items.append(item.get("relative_path", "Unknown"))

    return {
        "active_downloads": list(active_downloads.values()),
        "queue_size": download_queue.qsize(),
        "queue_items": items,
    }


@app.post("/api/downloads")
async def queue_download(req: DownloadRequest) -> dict[str, str]:
    await download_queue.put(req.dict())
    return {"status": "queued"}


# ──────────────────────────────────────────────────────────────────────────────
# Routes: Proxy
# ──────────────────────────────────────────────────────────────────────────────


@app.get("/play.m3u8")
async def proxy_master(
    title_id: int, request: Request, episode_id: Optional[int] = None
) -> Response:
    """
    1. Extracts stream URL from vixcloud
    2. Fetches master M3U8
    3. Rewrites it so child playlists pass through /proxy_child.m3u8
    """
    m3u8_url = await _get_stream_url(title_id, episode_id)
    if not m3u8_url:
        raise HTTPException(
            status_code=404, detail="Stream URL not found or extraction failed."
        )

    try:
        # IMPORTANT: the token in m3u8_url is tied to the scraper's session cookies.
        # Using a separate httpx client always 403s. We must reuse scraper._get.
        resp = await asyncio.to_thread(
            scraper._get,
            m3u8_url,
            headers={"Referer": VIXCLOUD_REFERER, "Accept": "*/*"},
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
    Child tokens are tied to the scraper's session — must reuse scraper._get.
    """
    try:
        resp = await asyncio.to_thread(
            scraper._get,
            child_url,
            headers={"Referer": VIXCLOUD_REFERER},
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

    except Exception as exc:
        log.error(f"Error proxying child M3U8: {exc}")
        raise HTTPException(
            status_code=502, detail="Error communicating with upstream server."
        )


@app.get("/enc.key")
async def proxy_enc_key(key_url: str) -> Response:
    """
    Proxy an AES-128 encryption key request.
    Key tokens are tied to the scraper's session — must reuse scraper._get.
    """
    try:
        # Resolve relative paths (e.g. /storage/enc.key → https://vixcloud.co/storage/enc.key)
        if key_url.startswith("/"):
            key_url = f"https://vixcloud.co{key_url}"

        resp = await asyncio.to_thread(
            scraper._get,
            key_url,
            headers={"Referer": VIXCLOUD_REFERER},
        )
        if resp.status_code != 200:
            raise HTTPException(
                status_code=resp.status_code, detail="Failed to fetch key."
            )
        return Response(content=resp.content, media_type="application/octet-stream")
    except Exception as exc:
        log.error(f"Error fetching encryption key: {exc}")
        raise HTTPException(status_code=502, detail="Error fetching encryption key.")


@app.get("/segment.ts")
async def proxy_segment(url: str, request: Request) -> Response:
    """
    Proxy a video/audio .ts segment from the CDN.

    The CDN (sc-u12-01.vix-content.net) blocks browser UAs (Chrome) and media
    player UAs (Lavf/MPV) with 403. It also blocks HTTP/1.1 requests from httpx.
    Using httpx default UA and HTTP/2 works.
    We stream the response using StreamingResponse so the player doesn't timeout.
    """
    client = httpx.AsyncClient(timeout=30.0, follow_redirects=True, http2=True)
    try:
        req = client.build_request("GET", url)
        # We must use stream=True and not use "async with" to keep client open during streaming.
        # BackgroundTask handles closing it.
        resp = await client.send(req, stream=True)
        if resp.status_code != 200:
            await resp.aclose()
            await client.aclose()
            raise HTTPException(
                status_code=resp.status_code, detail="Failed to fetch segment."
            )
        return StreamingResponse(
            resp.aiter_raw(),
            media_type="video/mp2t",
            headers={"Cache-Control": "no-cache"},
            background=BackgroundTask(client.aclose),
        )
    except httpx.RequestError as exc:
        await client.aclose()
        log.error(f"Error fetching segment: {exc}")
        raise HTTPException(status_code=502, detail="Error fetching segment.")
