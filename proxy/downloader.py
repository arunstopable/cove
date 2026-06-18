import asyncio
import logging
import os

from typing import Any
from shared import config

log = logging.getLogger("cove.proxy.downloader")

# Download Queue and Status
download_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
current_download: dict[str, Any] = {
    "active": False,
    "relative_path": "",
    "absolute_path": "",
}


async def download_worker(get_stream_url_func) -> None:
    """Background task to process downloads sequentially."""
    while True:
        try:
            task = await download_queue.get()
            title_id = task["title_id"]
            episode_id = task["episode_id"]
            media_type = task["type"]
            rel_path = task["relative_path"]

            base_path = (
                config.SERVER_SHOWS_PATH
                if media_type == "tv"
                else config.SERVER_MOVIES_PATH
            )
            out_path = os.path.join(base_path, rel_path)
            os.makedirs(os.path.dirname(out_path), exist_ok=True)

            ext = os.path.splitext(out_path)[1]
            part_path = out_path + ".part" + ext
            current_download["active"] = True
            current_download["relative_path"] = rel_path
            current_download["absolute_path"] = out_path

            log.info(f"[DOWNLOAD] Extracting URL for {title_id} / {episode_id}")
            m3u8_url = await get_stream_url_func(title_id, episode_id)
            if not m3u8_url:
                log.error(f"[DOWNLOAD] Failed to extract URL for {out_path}")
                download_queue.task_done()
                continue

            log.info(f"[DOWNLOAD] Starting ffmpeg to {part_path}")

            # Use the local proxy so ffmpeg benefits from the quality filtering
            proxy_url = f"http://127.0.0.1:8000/play.m3u8?title_id={title_id}"
            if episode_id is not None:
                proxy_url += f"&episode_id={episode_id}"

            cmd = [
                "ffmpeg",
                "-y",
                "-user_agent",
                config.USER_AGENT,
                "-i",
                proxy_url,
                "-map", "0:v?",
                "-map", "0:a?",
                "-map", "0:s?",
                "-dn",  # Ignore data streams (like ID3 tags) which crash the MKV muxer
                "-c",
                "copy",
                part_path,
            ]

            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )

            _, stderr_data = await proc.communicate()

            if proc.returncode == 0 and os.path.exists(part_path):
                os.rename(part_path, out_path)
                log.info(f"[DOWNLOAD] ✓ Success: {out_path}")
            else:
                err_msg = stderr_data.decode('utf-8', errors='replace') if stderr_data else "No stderr"
                if len(err_msg) > 2000:
                    err_msg = "... [TRUNCATED] ...\n" + err_msg[-2000:]
                log.error(f"[DOWNLOAD] ✗ Failed (code={proc.returncode}): {out_path}\nFFmpeg error:\n{err_msg}")
                if os.path.exists(part_path):
                    os.remove(part_path)

        except Exception as e:
            log.exception(f"[DOWNLOAD] Worker error: {e}")
        finally:
            current_download["active"] = False
            current_download["relative_path"] = ""
            current_download["absolute_path"] = ""
            # We must mark the task as done, but only if we haven't already.
            pass
