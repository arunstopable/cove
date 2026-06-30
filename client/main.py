"""Cove CLI — Minimalist Apple-inspired streaming hub."""

import os
import re
import glob
import time
import urllib.parse
from typing import Any, Optional, Tuple

import httpx
from rich.live import Live
from rich.panel import Panel

from shared import config
from client import ui
from shared.sc_scraper import SCScraper
from client.local_proxy_runner import local_proxy


def extract_movie_ep_id(details: dict[str, Any]) -> Optional[int]:
    """Extract playback episode ID from movie details. Returns None if it has no episodes."""
    ep_id: Optional[int] = None
    episodes_direct = details.get("title", {}).get("episodes", [])
    if episodes_direct:
        ep_id = episodes_direct[0].get("id")
    if not ep_id:
        fallback = (details.get("loadedSeason") or {}).get("episodes", [])
        if fallback:
            ep_id = fallback[0].get("id")
    return ep_id

def safe_filename(name: str) -> str:
    """Make string safe for macOS/Linux file paths."""
    return re.sub(r'[\\/*?:"<>|]', "", name).strip()

def _strm_url(base_url: str, title_id: int, episode_id: Optional[int] = None, slug: str = "") -> str:
    """Build the .strm content URL pointing to the active proxy /play.m3u8 endpoint."""
    url = f"{base_url}/play.m3u8?title_id={title_id}"
    if episode_id is not None:
        url += f"&episode_id={episode_id}"
    if slug:
        encoded_slug = urllib.parse.quote(slug)
        url += f"&slug={encoded_slug}"
    return url

# ──────────────────────────────────────────────────────────────────────────────
# Library Scanner
# ──────────────────────────────────────────────────────────────────────────────

def scan_library() -> list[dict[str, Any]]:
    """Scan NFS mounts for .strm files to build a stateless library."""
    items = []

    def _parse_strm(file_path: str) -> Tuple[str, str]:
        with open(file_path, "r") as f:
            url = f.read().strip()
        parsed = urllib.parse.urlparse(url)
        qs = urllib.parse.parse_qs(parsed.query)
        t_id = qs.get("title_id", [""])[0]
        t_slug = qs.get("slug", [""])[0]
        return t_id, t_slug

    # Scan TV Shows
    if os.path.exists(config.NFS_SHOWS_PATH):
        for folder in sorted(os.listdir(config.NFS_SHOWS_PATH)):
            folder_path = os.path.join(config.NFS_SHOWS_PATH, folder)
            if not os.path.isdir(folder_path):
                continue

            strm_files = glob.glob(os.path.join(folder_path, "**", "*.strm"), recursive=True)
            if strm_files:
                t_id, t_slug = _parse_strm(strm_files[0])
                if t_id.isdigit():
                    items.append({"id": int(t_id), "name": folder, "type": "tv", "slug": t_slug})

    # Scan Movies
    if os.path.exists(config.NFS_MOVIES_PATH):
        for folder in sorted(os.listdir(config.NFS_MOVIES_PATH)):
            folder_path = os.path.join(config.NFS_MOVIES_PATH, folder)
            if not os.path.isdir(folder_path):
                continue

            strm_files = glob.glob(os.path.join(folder_path, "*.strm"))
            if strm_files:
                t_id, t_slug = _parse_strm(strm_files[0])
                if t_id.isdigit():
                    items.append({"id": int(t_id), "name": folder, "type": "movie", "slug": t_slug})

    return items

def get_downloaded_ep_nums(show_name: str, season_num: int) -> set[int]:
    """Scan the season directory for .mkv files and extract episode numbers."""
    target_dir = os.path.join(config.NFS_SHOWS_PATH, show_name, f"Season {season_num:02d}")
    if not os.path.exists(target_dir):
        return set()

    nums = set()
    for f in os.listdir(target_dir):
        if f.endswith(".mkv"):
            match = re.search(r"S\d{2}E(\d{2})", f)
            if match:
                nums.add(int(match.group(1)))
    return nums

def get_downloading_ep_ids() -> set[int]:
    """Fetch the currently downloading and queued episode IDs from the proxy."""
    try:
        url = f"http://{config.PROXY_SERVER_IP}:{config.PROXY_SERVER_PORT}/api/downloads/status"
        r = httpx.get(url, timeout=2.0)
        if r.status_code == 200:
            data = r.json()
            ids = set()
            for ad in data.get("active_downloads", []):
                if ad.get("episode_id"):
                    ids.add(ad["episode_id"])
            for qi in data.get("queue_items", []):
                if isinstance(qi, dict) and qi.get("episode_id"):
                    ids.add(qi["episode_id"])
            return ids
    except Exception:
        pass
    return set()

def update_active_downloads_count() -> None:
    try:
        url = f"http://{config.PROXY_SERVER_IP}:{config.PROXY_SERVER_PORT}/api/downloads/status"
        r = httpx.get(url, timeout=1.0)
        if r.status_code == 200:
            data = r.json()
            ui.ACTIVE_DOWNLOADS_COUNT = len(data.get("active_downloads", [])) + data.get("queue_size", 0)
    except Exception:
        ui.ACTIVE_DOWNLOADS_COUNT = 0

# ──────────────────────────────────────────────────────────────────────────────
# Export (.strm) & Cleanup
# ──────────────────────────────────────────────────────────────────────────────

def export_media(scraper: SCScraper, sc_title: dict[str, Any]) -> None:
    is_tv = sc_title.get("type") == "tv"
    base_dir = config.NFS_SHOWS_PATH if is_tv else config.NFS_MOVIES_PATH
    name = safe_filename(sc_title.get("name", "Unknown"))
    title_id: int = sc_title["id"]
    slug: str = sc_title.get("slug", "")

    if is_tv:
        with ui.spinner(f"Fetching details for {name}..."):
            details = scraper.get_title_details(title_id, slug)

        seasons = details.get("title", {}).get("seasons", [])
        if not seasons:
            ui.show_error("No seasons found.")
            time.sleep(2)
            return

        for season in seasons:
            season_num: int = season.get("number", 1)
            season_dir = os.path.join(base_dir, name, f"Season {season_num:02d}")
            os.makedirs(season_dir, exist_ok=True)

            downloaded_nums = get_downloaded_ep_nums(name, season_num)

            season_data = scraper.get_season_details(title_id, slug, season_num)
            episodes = season_data.get("loadedSeason", {}).get("episodes", [])
            for ep in episodes:
                ep_num: int = ep.get("number", 0)
                ep_id: Optional[int] = ep.get("id")
                if not ep_id:
                    continue
                ep_name = safe_filename(ep.get("name", f"Episode {ep_num}"))
                file_name_strm = f"{name} S{season_num:02d}E{ep_num:02d} - {ep_name}.strm"
                file_path_strm = os.path.join(season_dir, file_name_strm)

                if ep_num in downloaded_nums:
                    for f in os.listdir(season_dir):
                        if f.endswith(".strm") and f"S{season_num:02d}E{ep_num:02d}" in f:
                            try: os.remove(os.path.join(season_dir, f))
                            except OSError: pass
                    continue

                with open(file_path_strm, "w") as f:
                    f.write(_strm_url(f"http://{config.PROXY_SERVER_IP}:{config.PROXY_SERVER_PORT}", title_id, ep_id, slug))

        ui.show_success(f"Exported {name} to library")
        time.sleep(1)

    else:
        with ui.spinner(f"Fetching details for {name}..."):
            details = scraper.get_title_details(title_id, slug)

        ep_id = extract_movie_ep_id(details)
        movie_dir = os.path.join(base_dir, name)
        os.makedirs(movie_dir, exist_ok=True)
        file_path_strm = os.path.join(movie_dir, f"{name}.strm")

        has_mkv = any(f.endswith(".mkv") for f in os.listdir(movie_dir))

        if has_mkv:
            for f in os.listdir(movie_dir):
                if f.endswith(".strm"):
                    try: os.remove(os.path.join(movie_dir, f))
                    except OSError: pass
            ui.show_info(f"Skipping export: {name} local file exists.")
            time.sleep(1)
            return

        with open(file_path_strm, "w") as f:
            f.write(_strm_url(f"http://{config.PROXY_SERVER_IP}:{config.PROXY_SERVER_PORT}", title_id, ep_id, slug))

        ui.show_success(f"Exported {name} to library")
        time.sleep(1)


def cleanup_offline(scraper: SCScraper, sc_title: dict[str, Any]) -> None:
    is_tv = sc_title.get("type") == "tv"
    base_dir = config.NFS_SHOWS_PATH if is_tv else config.NFS_MOVIES_PATH
    name = safe_filename(sc_title.get("name", "Unknown"))
    target_dir = os.path.join(base_dir, name)

    if not os.path.exists(target_dir):
        ui.show_error("Directory not found.")
        time.sleep(1.5)
        return

    mkv_files = glob.glob(os.path.join(target_dir, "**", "*.mkv") if is_tv else os.path.join(target_dir, "*.mkv"), recursive=True)
    strm_files = glob.glob(os.path.join(target_dir, "**", "*.strm") if is_tv else os.path.join(target_dir, "*.strm"), recursive=True)

    if not mkv_files and not strm_files:
        import shutil
        try: shutil.rmtree(target_dir)
        except Exception: pass
        ui.show_info("Removed empty directory.")
        time.sleep(1)
        return

    if not ui.confirm(f"Remove {len(mkv_files)} local files and {len(strm_files)} .strm files for {name}?"):
        return

    # Cancel ongoing downloads
    title_id = sc_title.get("id")
    if title_id:
        try:
            encoded_name = urllib.parse.quote(name)
            url = f"http://{config.PROXY_SERVER_IP}:{config.PROXY_SERVER_PORT}/api/downloads/{title_id}?name={encoded_name}"
            httpx.delete(url, timeout=3.0)
        except Exception:
            pass
            
    deleted = 0
    for f in mkv_files + strm_files:
        try:
            os.remove(f)
            deleted += 1
        except Exception:
            pass

    # Clean empty directories
    try:
        if is_tv:
            for s_dir in glob.glob(os.path.join(target_dir, "Season *")):
                if not os.listdir(s_dir): os.rmdir(s_dir)
        if not os.listdir(target_dir):
            os.rmdir(target_dir)
    except Exception:
        pass

    ui.show_success(f"Deleted {deleted} files.")
    time.sleep(1.5)

# ──────────────────────────────────────────────────────────────────────────────
# Downloading Logic
# ──────────────────────────────────────────────────────────────────────────────

def _queue_download(title_id: int, episode_id: Optional[int], media_type: str, relative_path: str) -> bool:
    url = f"http://{config.PROXY_SERVER_IP}:{config.PROXY_SERVER_PORT}/api/downloads"
    payload = {
        "title_id": title_id,
        "episode_id": episode_id,
        "type": media_type,
        "relative_path": relative_path,
    }
    try:
        r = httpx.post(url, json=payload, timeout=5.0)
        return r.status_code == 200
    except Exception:
        return False

def download_season(scraper: SCScraper, sc_title: dict[str, Any]) -> None:
    title_id: int = sc_title["id"]
    slug: str = sc_title.get("slug", "")
    name = safe_filename(sc_title.get("name", "Unknown"))

    with ui.spinner("Fetching seasons..."):
        details = scraper.get_title_details(title_id, slug)

    seasons = details.get("title", {}).get("seasons", [])
    if not seasons: return

    season_choice = ui.select_season(seasons, for_download=True)
    if not season_choice or season_choice == "BACK": return

    target_seasons = seasons if season_choice == "ALL" else [season_choice]
    queued = 0

    for season in target_seasons:
        season_num = season.get("number", 1)
        with ui.spinner(f"Loading Season {season_num}..."):
            season_data = scraper.get_season_details(title_id, slug, season_num)
            episodes = season_data.get("loadedSeason", {}).get("episodes", [])
            
        downloaded_nums = get_downloaded_ep_nums(name, season_num)
        downloaded_ids = {ep["id"] for ep in episodes if ep.get("number") in downloaded_nums and "id" in ep}
        downloading_ids = get_downloading_ep_ids()

        target_episodes = ui.select_episodes_multi(episodes, downloaded_ids, downloading_ids)
        if not target_episodes: continue

        for ep in target_episodes:
            ep_num = ep.get("number", 0)
            ep_id = ep.get("id")
            if not ep_id: continue
            ep_name = safe_filename(ep.get("name", f"Episode {ep_num}"))
            rel_path = f"{name}/Season {season_num:02d}/{name} S{season_num:02d}E{ep_num:02d} - {ep_name}.mkv"
            if _queue_download(title_id, ep_id, "tv", rel_path):
                queued += 1

    if queued > 0:
        ui.show_success(f"Queued {queued} episodes.")
        update_active_downloads_count()
        time.sleep(1.5)

def download_movie(scraper: SCScraper, sc_title: dict[str, Any]) -> None:
    title_id: int = sc_title["id"]
    slug: str = sc_title.get("slug", "")
    name = safe_filename(sc_title.get("name", "Unknown"))

    with ui.spinner("Fetching metadata..."):
        details = scraper.get_title_details(title_id, slug)

    ep_id = extract_movie_ep_id(details)
    rel_path = f"{name}/{name}.mkv"
    
    if _queue_download(title_id, ep_id, "movie", rel_path):
        ui.show_success("Queued for download.")
        update_active_downloads_count()
        time.sleep(1.5)
    else:
        ui.show_error("Failed to queue download.")
        time.sleep(1.5)

# ──────────────────────────────────────────────────────────────────────────────
# Playback
# ──────────────────────────────────────────────────────────────────────────────

def _open_player(play_target: str, is_local: bool) -> None:
    import subprocess
    ui.show_info(f"Opening {config.PLAYER_APP}...")
    
    if is_local:
        if config.PLAYER_APP.lower() == "iina":
            cmd = ["/Applications/IINA.app/Contents/MacOS/iina-cli", "--keep-running", play_target]
        elif config.PLAYER_APP.lower() == "vlc":
            cmd = ["/Applications/VLC.app/Contents/MacOS/VLC", play_target]
        else:
            cmd = ["open", "-a", config.PLAYER_APP, play_target]
    else:
        referer_arg = "--http-header-fields=Referer: https://vixcloud.co/"
        if config.PLAYER_APP.lower() == "iina":
            cmd = ["/Applications/IINA.app/Contents/MacOS/iina-cli", "--keep-running", "--mpv-http-header-fields=Referer: https://vixcloud.co/", play_target]
        elif config.PLAYER_APP.lower() == "vlc":
            cmd = ["/Applications/VLC.app/Contents/MacOS/VLC", "--http-referrer=https://vixcloud.co/", play_target]
        else:
            cmd = [config.PLAYER_APP, play_target, referer_arg]

    try:
        subprocess.run(cmd, check=False)
    except FileNotFoundError:
        ui.show_error(f"Player executable not found: {config.PLAYER_APP}")
        time.sleep(2)

def handle_playback(title_id: int, ep_id: Optional[int], local_file: Optional[str]) -> None:
    if local_file and os.path.exists(local_file):
        _open_player(local_file, is_local=True)
    else:
        if not ui.SERVER_ONLINE:
            ui.show_error("Cannot stream: Proxy server is offline.")
            time.sleep(2)
            return

        with local_proxy() as base_url:
            play_target = _strm_url(base_url, title_id, ep_id)
            _open_player(play_target, is_local=False)

def browse_episodes(scraper: SCScraper, sc_title: dict[str, Any]) -> None:
    title_id: int = sc_title["id"]
    slug: str = sc_title.get("slug", "")
    name = safe_filename(sc_title.get("name", "Unknown"))

    with ui.spinner("Fetching seasons..."):
        details = scraper.get_title_details(title_id, slug)

    seasons = details.get("title", {}).get("seasons", [])
    if not seasons: return

    while True:
        ui.clear_screen()
        ui.print_header()
        season = ui.select_season(seasons)
        if not season or season == "BACK": break

        season_num: int = season.get("number", 1)
        with ui.spinner("Fetching episodes..."):
            season_data = scraper.get_season_details(title_id, slug, season_num)

        episodes = season_data.get("loadedSeason", {}).get("episodes", [])
        if not episodes: continue

        last_episode = None
        while True:
            downloaded_nums = get_downloaded_ep_nums(name, season_num)
            downloaded_ids = {ep["id"] for ep in episodes if ep.get("number") in downloaded_nums and "id" in ep}
            downloading_ids = get_downloading_ep_ids()

            ui.clear_screen()
            ui.print_header()
            episode = ui.select_episode(episodes, downloaded_ids, downloading_ids, default=last_episode)
            if not episode or episode == "BACK": break
            last_episode = episode

            ep_id: int = episode.get("id", 0)
            ep_num: int = episode.get("number", 0)
            is_downloaded = ep_num in downloaded_nums

            action = ui.select_episode_action(ep_num, episode.get("name", "Unknown"), is_downloaded)
            if not action or action == "BACK": continue

            if action == "DOWNLOAD":
                ep_name = safe_filename(episode.get("name", f"Episode {ep_num}"))
                rel_path = f"{name}/Season {season_num:02d}/{name} S{season_num:02d}E{ep_num:02d} - {ep_name}.mkv"
                if _queue_download(title_id, ep_id, "tv", rel_path):
                    ui.show_success("Queued for download.")
                    update_active_downloads_count()
                    time.sleep(1)
            elif action == "PLAY":
                local_file = None
                if is_downloaded:
                    target_dir = os.path.join(config.NFS_SHOWS_PATH, name, f"Season {season_num:02d}")
                    for f in os.listdir(target_dir):
                        if f.endswith(".mkv") and f"S{season_num:02d}E{ep_num:02d}" in f:
                            local_file = os.path.join(target_dir, f)
                            break
                handle_playback(title_id, ep_id, local_file)

# ──────────────────────────────────────────────────────────────────────────────
# Unified Title Flow
# ──────────────────────────────────────────────────────────────────────────────

def handle_title_card(scraper: SCScraper, selected: dict[str, Any]) -> None:
    title_id = selected.get("id")
    name = safe_filename(selected.get("name", "Unknown"))
    is_tv = selected.get("type") == "tv"

    # Silent slug resolution if missing (from library selection)
    if not selected.get("slug"):
        with ui.spinner("Resolving metadata..."):
            search_results = scraper.search(selected.get("name", ""))
            for r in search_results:
                if r.get("id") == title_id:
                    selected["slug"] = r.get("slug", "")
                    selected["seasons_count"] = r.get("seasons_count", 0)
                    break
        if not selected.get("slug"):
            ui.show_error("Could not resolve metadata for this title.")
            time.sleep(2)
            return

    while True:
        ui.clear_screen()
        ui.print_header()

        # Check local state
        has_mkv = False
        has_strm = False
        base_dir = config.NFS_SHOWS_PATH if is_tv else config.NFS_MOVIES_PATH
        target_dir = os.path.join(base_dir, name)

        if os.path.exists(target_dir):
            if is_tv:
                mkvs = glob.glob(os.path.join(target_dir, "**", "*.mkv"), recursive=True)
                has_mkv = len(mkvs) > 0
                strms = glob.glob(os.path.join(target_dir, "**", "*.strm"), recursive=True)
                has_strm = len(strms) > 0
            else:
                has_mkv = any(f.endswith(".mkv") for f in os.listdir(target_dir))
                has_strm = any(f.endswith(".strm") for f in os.listdir(target_dir))

        action = ui.select_title_action(selected, has_mkv, has_strm)
        
        if not action or action == "BACK":
            break
            
        if action == "BROWSE":
            browse_episodes(scraper, selected)
        elif action == "PLAY":
            local_file = None
            if has_mkv and not is_tv:
                for f in os.listdir(target_dir):
                    if f.endswith(".mkv"):
                        local_file = os.path.join(target_dir, f)
                        break
            
            # Fetch ep_id for movie
            ep_id = None
            if not is_tv:
                with ui.spinner("Fetching metadata..."):
                    details = scraper.get_title_details(title_id, selected.get("slug", ""))
                    ep_id = extract_movie_ep_id(details)
                    
            handle_playback(title_id, ep_id, local_file)
        elif action == "DOWNLOAD_SEASON":
            download_season(scraper, selected)
        elif action == "DOWNLOAD":
            download_movie(scraper, selected)
        elif action == "EXPORT":
            export_media(scraper, selected)
        elif action == "CLEANUP":
            cleanup_offline(scraper, selected)

# ──────────────────────────────────────────────────────────────────────────────
# Download Status UI
# ──────────────────────────────────────────────────────────────────────────────

def show_download_status() -> None:
    def get_status_panel() -> Panel:
        url = f"http://{config.PROXY_SERVER_IP}:{config.PROXY_SERVER_PORT}/api/downloads/status"
        try:
            r = httpx.get(url, timeout=2.0)
            if r.status_code != 200:
                return Panel(f"[bold {ui.SOFT_RED}]Server error: {r.status_code}[/]", title="Error", border_style=ui.SOFT_RED)
                
            data = r.json()
            active_downloads = data.get("active_downloads", [])
            queue_items = data.get("queue_items", [])
            queue_size = data.get("queue_size", 0)

            ui.ACTIVE_DOWNLOADS_COUNT = len(active_downloads) + queue_size

            lines = []
            if not active_downloads and not queue_items:
                lines.append(f"[bold {ui.CRISP_WHITE}]No active downloads.[/]")
            else:
                for current in active_downloads:
                    name = os.path.basename(current.get("relative_path", "Unknown"))
                    mb = current.get('downloaded_mb', 0)
                    progress = current.get('time_progress', '00:00:00')
                    total = current.get('time_total', 'Unknown')
                    
                    pct_str = ""
                    if total != "Unknown":
                        try:
                            def hms_to_s(hms):
                                h, m, s = map(float, hms.split(':'))
                                return h*3600 + m*60 + s
                            p_s = hms_to_s(progress)
                            t_s = hms_to_s(total)
                            if t_s > 0:
                                pct = min(100, int((p_s / t_s) * 100))
                                bars = int(pct / 5)
                                bar_str = "█" * bars + "░" * (20 - bars)
                                pct_str = f" {bar_str} {pct}%"
                        except Exception:
                            pass

                    lines.append(f"↓ [bold {ui.APPLE_BLUE}]{name}[/]")
                    lines.append(f"  {progress} / {total}{pct_str}  [{mb} MB]")
                    lines.append("")

                if queue_items:
                    lines.append(f"Queue: {queue_size} items")
                    for idx, item in enumerate(queue_items[:5], 1):
                        q_name = os.path.basename(item.get("relative_path", "Unknown"))
                        lines.append(f"  {idx}. [dim]{q_name}[/]")
                    if queue_size > 5:
                        lines.append(f"  [dim]... and {queue_size - 5} more[/]")

            return Panel("\n".join(lines), title="Live Status (Refresh: 3s, Ctrl+C to exit)", border_style=ui.BORDER_GRAY, padding=(1, 2))
        except Exception as e:
            return Panel(f"[bold {ui.SOFT_RED}]Failed to contact proxy: {e}[/]", title="Error", border_style=ui.SOFT_RED)

    ui.clear_screen()
    ui.print_header()
    
    try:
        with Live(get_status_panel(), refresh_per_second=1, console=ui.console) as live:
            while True:
                time.sleep(3)
                live.update(get_status_panel())
                # Allow returning if empty
                if ui.ACTIVE_DOWNLOADS_COUNT == 0:
                    break
    except KeyboardInterrupt:
        pass

# ──────────────────────────────────────────────────────────────────────────────
# Entrypoint
# ──────────────────────────────────────────────────────────────────────────────

def main() -> None:
    ui.clear_screen()
    with ui.spinner("Checking system status..."):
        try:
            r = httpx.get(f"http://{config.PROXY_SERVER_IP}:{config.PROXY_SERVER_PORT}/health", timeout=1.0)
            ui.SERVER_ONLINE = r.status_code == 200
        except Exception:
            ui.SERVER_ONLINE = False

        ui.NFS_ONLINE = os.path.exists(config.NFS_SHOWS_PATH) and os.path.exists(config.NFS_MOVIES_PATH)

    scraper = SCScraper()
    with ui.spinner("Initializing session..."):
        scraper.init_session()
        ui.MAX_QUALITY = scraper.check_global_quality()
        update_active_downloads_count()

    try:
        while True:
            ui.clear_screen()
            ui.print_header()

            if not ui.SERVER_ONLINE and not ui.NFS_ONLINE:
                main_action = "SEARCH"
            else:
                main_action = ui.select_main_menu()
                if not main_action or main_action == "EXIT":
                    break

            if main_action == "STATUS":
                show_download_status()
                continue

            selected = None

            if main_action == "LIBRARY":
                ui.clear_screen()
                ui.print_header()
                with ui.spinner("Scanning library..."):
                    library_items = scan_library()
                if not library_items:
                    ui.show_info("Your library is empty. Add titles first.")
                    time.sleep(2)
                    continue
                selected = ui.select_library_item(library_items)

            elif main_action == "SEARCH":
                query = ui.ask_search_query()
                if not query or not query.strip():
                    continue

                with ui.spinner("Searching..."):
                    results = scraper.search(query)

                if not results:
                    ui.show_error("No results found.")
                    time.sleep(2)
                    continue

                ui.clear_screen()
                ui.print_header()
                selected = ui.select_sc_search_result(results)

            if not selected or selected == "BACK":
                continue

            handle_title_card(scraper, selected)

    except (KeyboardInterrupt, EOFError):
        pass
    finally:
        ui.console.print("\n[dim]Goodbye.[/]")
        scraper.close()

if __name__ == "__main__":
    main()
