import asyncio
import logging
import os
import shutil
import re

from typing import Any
from shared import config

log = logging.getLogger("cove.proxy.downloader")

# Download Queue and Status
download_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
active_downloads: dict[int, dict[str, Any]] = {}


def cancel_downloads(title_id: int) -> int:
    """Cancel any active or queued downloads for the given title_id."""
    cancelled = 0

    # 1. Remove from queue
    old_qsize = download_queue.qsize()
    new_queue = [item for item in download_queue._queue if item.get("title_id") != title_id]
    cancelled += old_qsize - len(new_queue)
    download_queue._queue.clear()
    download_queue._queue.extend(new_queue)

    # 2. Cancel active downloads
    for worker_id, current in list(active_downloads.items()):
        if current.get("title_id") == title_id:
            proc = current.get("proc")
            if proc and proc.returncode is None:
                try:
                    proc.kill()
                    cancelled += 1
                except Exception:
                    pass

    return cancelled


def cleanup_empty_dirs(path: str, base_dir: str) -> None:
    """Recursively remove empty directories up to base_dir."""
    current = os.path.dirname(path)
    # Ensure paths are absolute for reliable comparison
    current_abs = os.path.abspath(current)
    base_abs = os.path.abspath(base_dir)
    
    while current_abs and current_abs != base_abs and current_abs.startswith(base_abs):
        try:
            if not os.listdir(current_abs):
                os.rmdir(current_abs)
                log.info(f"[DOWNLOAD] Removed empty WIP dir: {current_abs}")
                current_abs = os.path.dirname(current_abs)
            else:
                break
        except Exception:
            break


async def download_worker(worker_id: int, get_stream_url_func) -> None:
    """Background task to process downloads."""
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

            wip_path = os.path.join(config.SERVER_WIP_PATH, rel_path)
            os.makedirs(os.path.dirname(wip_path), exist_ok=True)

            ext = os.path.splitext(out_path)[1]
            part_path = wip_path + ".part" + ext
            active_downloads[worker_id] = {
                "active": True,
                "relative_path": rel_path,
                "absolute_path": out_path,
                "part_path": part_path,
                "episode_id": episode_id,
            }

            log.info(f"[DOWNLOAD] Extracting URL for {title_id} / {episode_id}")
            result = await get_stream_url_func(title_id, episode_id)
            if not result:
                log.error(f"[DOWNLOAD] Failed to extract URL for {out_path}")
                download_queue.task_done()
                continue
            m3u8_url, _ = result

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
            
            # Store proc and title_id so cancel_downloads can kill it
            active_downloads[worker_id]["proc"] = proc
            active_downloads[worker_id]["title_id"] = title_id

            stderr_history = []
            while True:
                try:
                    # ffmpeg uses \r for progress updates, not \n
                    line = await proc.stderr.readuntil(b'\r')
                except asyncio.exceptions.IncompleteReadError as e:
                    line = e.partial
                except asyncio.exceptions.LimitOverrunError:
                    # If it somehow exceeds limit, just read chunk
                    line = await proc.stderr.read(4096)

                if not line:
                    break
                
                line_str = line.decode('utf-8', errors='replace').strip()
                if not line_str:
                    continue

                stderr_history.append(line_str)
                if len(stderr_history) > 50:
                    stderr_history.pop(0)

                if "Duration:" in line_str and "time_total" not in active_downloads[worker_id]:
                    dur_match = re.search(r"Duration:\s*(\d{2}:\d{2}:\d{2})", line_str)
                    if dur_match:
                        active_downloads[worker_id]["time_total"] = dur_match.group(1)

                time_match = re.search(r"time=(\d{2}:\d{2}:\d{2})", line_str)
                if time_match:
                    active_downloads[worker_id]["time_progress"] = time_match.group(1)

            await proc.wait()

            if proc.returncode == 0 and os.path.exists(part_path):
                shutil.move(part_path, out_path)
                
                # Delete corresponding .strm file if it exists
                strm_path = os.path.splitext(out_path)[0] + ".strm"
                if os.path.exists(strm_path):
                    try:
                        os.remove(strm_path)
                        log.info(f"[DOWNLOAD] Deleted old .strm file: {strm_path}")
                    except OSError as e:
                        log.warning(f"[DOWNLOAD] Could not delete .strm file {strm_path}: {e}")

                log.info(f"[DOWNLOAD] ✓ Success: {out_path}")
            else:
                err_msg = "".join(stderr_history)
                if len(err_msg) > 2000:
                    err_msg = "... [TRUNCATED] ...\n" + err_msg[-2000:]
                log.error(f"[DOWNLOAD] ✗ Failed (code={proc.returncode}): {out_path}\nFFmpeg error:\n{err_msg}")
                if os.path.exists(part_path):
                    try:
                        os.remove(part_path)
                    except OSError:
                        pass

        except Exception as e:
            log.exception(f"[DOWNLOAD] Worker error: {e}")
        finally:
            if 'proc' in locals() and proc.returncode is None:
                try:
                    proc.kill()
                except ProcessLookupError:
                    pass
            if worker_id in active_downloads:
                del active_downloads[worker_id]
                
            # Clean up empty directories in WIP just in case
            if 'part_path' in locals():
                cleanup_empty_dirs(part_path, config.SERVER_WIP_PATH)
