"""Cove CLI — Minimalist Apple-inspired streaming hub."""

import os
import re
import glob
from typing import Any, Optional
import urllib.parse

import httpx
import questionary

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


from typing import Optional

def _strm_url(base_url: str, title_id: int, episode_id: Optional[int] = None) -> str:
    """Build the .strm content URL pointing to the active proxy /play.m3u8 endpoint."""
    url = f"{base_url}/play.m3u8?title_id={title_id}"
    if episode_id is not None:
        url += f"&episode_id={episode_id}"
    return url


# ──────────────────────────────────────────────────────────────────────────────
# Library Scanner
# ──────────────────────────────────────────────────────────────────────────────


def scan_library() -> list[dict[str, Any]]:
    """Scan NFS mounts for .strm files to build a stateless library."""
    items = []

    # Scan TV Shows
    if os.path.exists(config.NFS_SHOWS_PATH):
        for folder in sorted(os.listdir(config.NFS_SHOWS_PATH)):
            folder_path = os.path.join(config.NFS_SHOWS_PATH, folder)
            if not os.path.isdir(folder_path):
                continue

            strm_files = glob.glob(
                os.path.join(folder_path, "**", "*.strm"), recursive=True
            )
            if strm_files:
                # Read the first .strm to extract title_id
                with open(strm_files[0], "r") as f:
                    url = f.read().strip()
                parsed = urllib.parse.urlparse(url)
                qs = urllib.parse.parse_qs(parsed.query)
                t_id = qs.get("title_id", [""])[0]
                if t_id.isdigit():
                    items.append(
                        {"id": int(t_id), "name": folder, "type": "tv", "slug": ""}
                    )

    # Scan Movies
    if os.path.exists(config.NFS_MOVIES_PATH):
        for folder in sorted(os.listdir(config.NFS_MOVIES_PATH)):
            folder_path = os.path.join(config.NFS_MOVIES_PATH, folder)
            if not os.path.isdir(folder_path):
                continue

            strm_files = glob.glob(os.path.join(folder_path, "*.strm"))
            if strm_files:
                with open(strm_files[0], "r") as f:
                    url = f.read().strip()
                parsed = urllib.parse.urlparse(url)
                qs = urllib.parse.parse_qs(parsed.query)
                t_id = qs.get("title_id", [""])[0]
                if t_id.isdigit():
                    items.append(
                        {"id": int(t_id), "name": folder, "type": "movie", "slug": ""}
                    )

    return items


def get_downloaded_ep_nums(show_name: str, season_num: int) -> set[int]:
    """Scan the season directory for .mkv files and extract episode numbers."""
    target_dir = os.path.join(
        config.NFS_SHOWS_PATH, show_name, f"Season {season_num:02d}"
    )
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


# ──────────────────────────────────────────────────────────────────────────────
# Export (.strm)
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
                file_name_strm = (
                    f"{name} S{season_num:02d}E{ep_num:02d} - {ep_name}.strm"
                )
                file_path_strm = os.path.join(season_dir, file_name_strm)

                # If any .mkv exists for this episode, do not create .strm and clean up old .strm
                if ep_num in downloaded_nums:
                    # Look for any existing .strm for this episode number and delete it
                    for f in os.listdir(season_dir):
                        if (
                            f.endswith(".strm")
                            and f"S{season_num:02d}E{ep_num:02d}" in f
                        ):
                            try:
                                os.remove(os.path.join(season_dir, f))
                            except OSError:
                                pass
                    continue

                with open(file_path_strm, "w") as f:
                    f.write(
                        _strm_url(
                            f"http://{config.PROXY_SERVER_IP}:{config.PROXY_SERVER_PORT}",
                            title_id,
                            ep_id,
                        )
                    )

        ui.show_success(f"Exported {name} to {base_dir}")

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
                    try:
                        os.remove(os.path.join(movie_dir, f))
                    except OSError:
                        pass
            ui.show_info(f"Skipping export: {name} .mkv already exists.")
            return

        with open(file_path_strm, "w") as f:
            f.write(
                _strm_url(
                    f"http://{config.PROXY_SERVER_IP}:{config.PROXY_SERVER_PORT}",
                    title_id,
                    ep_id,
                )
            )

        ui.show_success(f"Exported {name} to {movie_dir}")


# ──────────────────────────────────────────────────────────────────────────────
# Offline Download & Cleanup
# ──────────────────────────────────────────────────────────────────────────────


def download_offline(scraper: SCScraper, sc_title: dict[str, Any]) -> None:
    is_tv = sc_title.get("type") == "tv"
    name = safe_filename(sc_title.get("name", "Unknown"))
    title_id: int = sc_title["id"]
    slug: str = sc_title.get("slug", "")

    if is_tv:
        with ui.spinner("Fetching details..."):
            details = scraper.get_title_details(title_id, slug)

        seasons = details.get("title", {}).get("seasons", [])
        if not seasons:
            ui.show_error("No seasons found.")
            return

        ui.clear_screen()
        ui.print_header()
        ui.show_info(f"Target: {name}")

        dl_choice = questionary.select(
            "Download Scope:",
            choices=[
                questionary.Choice(title="  Entire Show", value="SHOW"),
                questionary.Choice(title="  Specific Season (All Episodes)", value="SEASON"),
                questionary.Choice(title="  Specific Episodes", value="SPECIFIC"),
                ui._back()
            ],
            style=ui.cove_style,
            pointer="❯",
            qmark="",
        ).ask()

        if not dl_choice or dl_choice == "BACK":
            return

        target_seasons = seasons
        
        if dl_choice == "SEASON" or dl_choice == "SPECIFIC":
            selected_season = ui.select_season(seasons)
            if not selected_season or selected_season == "BACK":
                return
            target_seasons = [selected_season]

        queued = 0

        for season in target_seasons:
            season_num: int = season.get("number", 1)
            with ui.spinner(f"Loading Season {season_num}..."):
                season_data = scraper.get_season_details(title_id, slug, season_num)
                episodes = season_data.get("loadedSeason", {}).get("episodes", [])

            target_episodes = episodes
            if dl_choice == "SPECIFIC":
                downloaded_nums = get_downloaded_ep_nums(name, season_num)
                downloaded_ids = {
                    ep["id"]
                    for ep in episodes
                    if ep.get("number") in downloaded_nums and "id" in ep
                }
                downloading_ids = get_downloading_ep_ids()

                target_episodes = ui.select_episodes_multi(episodes, downloaded_ids, downloading_ids)
                if not target_episodes:
                    continue

            for ep in target_episodes:
                ep_num: int = ep.get("number", 0)
                ep_id: Optional[int] = ep.get("id")
                if not ep_id:
                    continue

                ep_name = safe_filename(ep.get("name", f"Episode {ep_num}"))
                rel_path = f"{name}/Season {season_num:02d}/{name} S{season_num:02d}E{ep_num:02d} - {ep_name}.mkv"
                if _queue_download(title_id, ep_id, "tv", rel_path):
                    queued += 1

        if queued > 0:
            ui.show_success(f"Queued {queued} episode(s) to the server.")

    else:
        # Movie
        with ui.spinner("Fetching details..."):
            details = scraper.get_title_details(title_id, slug)

        ep_id = extract_movie_ep_id(details)

        rel_path = f"{name}/{name}.mkv"
        if _queue_download(title_id, ep_id, "movie", rel_path):
            ui.show_success("Queued movie for background download.")


def _queue_download(
    title_id: int, episode_id: Optional[int], media_type: str, relative_path: str
) -> bool:
    url = f"http://{config.PROXY_SERVER_IP}:{config.PROXY_SERVER_PORT}/api/downloads"
    payload = {
        "title_id": title_id,
        "episode_id": episode_id,
        "type": media_type,
        "relative_path": relative_path,
    }
    try:
        r = httpx.post(url, json=payload, timeout=5.0)
        if r.status_code == 200:
            return True
        ui.show_error(f"Server returned error: {r.status_code}")
        return False
    except Exception as e:
        ui.show_error(f"Failed to contact proxy server: {e}")
        return False


def cleanup_offline(scraper: SCScraper, sc_title: dict[str, Any]) -> None:
    is_tv = sc_title.get("type") == "tv"
    base_dir = config.NFS_SHOWS_PATH if is_tv else config.NFS_MOVIES_PATH
    name = safe_filename(sc_title.get("name", "Unknown"))
    target_dir = os.path.join(base_dir, name)

    if not os.path.exists(target_dir):
        ui.show_error("Directory not found.")
        return

    if is_tv:
        seasons_dirs = sorted(glob.glob(os.path.join(target_dir, "Season *")))
        if not seasons_dirs:
            ui.show_info("No seasons found.")
            return

        choices = ["ALL"] + [os.path.basename(d) for d in seasons_dirs]
        scope = questionary.select(
            "Target Season:",
            choices=choices + ["BACK"],
            style=ui.cove_style,
            qmark="",
            pointer="❯",
        ).ask()
        if not scope or scope == "BACK":
            return

        search_path = (
            os.path.join(target_dir, "**", "*.mkv")
            if scope == "ALL"
            else os.path.join(target_dir, scope, "*.mkv")
        )
    else:
        search_path = os.path.join(target_dir, "*.mkv")

    mkv_files = glob.glob(search_path, recursive=True)
    if not mkv_files:
        ui.show_info("No downloaded .mkv files found here.")
        
    # Always ask if they want to clean up, because there might be ongoing downloads
    # that haven't produced .mkv files yet, but have .part files in .wip
    title_id = sc_title.get("id")
    confirm = questionary.confirm(
        f"Cancel ongoing downloads, clean WIP, and delete {len(mkv_files)} physical .mkv file(s)?",
        style=ui.cove_style,
        qmark="",
    ).ask()

    if not confirm:
        return

    # Cancel ongoing downloads for this title and let proxy wipe the .wip folder
    if title_id:
        try:
            import urllib.parse
            encoded_name = urllib.parse.quote(name)
            url = f"http://{config.PROXY_SERVER_IP}:{config.PROXY_SERVER_PORT}/api/downloads/{title_id}?name={encoded_name}"
            r = httpx.delete(url, timeout=3.0)
            if r.status_code == 200:
                c = r.json().get("cancelled", 0)
                if c > 0:
                    ui.show_info(f"Cancelled {c} ongoing download(s) for this title.")
        except Exception:
            pass
            
    deleted = 0
    for f in mkv_files:
        try:
            os.remove(f)
            deleted += 1
        except Exception:
            pass

    if deleted > 0:
        ui.show_success(f"Deleted {deleted} physical file(s).")
        
    # Restore .strm files for the missing episodes
    ui.show_info("Restoring .strm files...")
    export_media(scraper, sc_title)


def show_download_status() -> None:
    ui.clear_screen()
    ui.print_header()
    ui.show_info("Press Ctrl+C to return to main menu.\n")

    import time
    from rich.live import Live
    from rich.panel import Panel

    def get_status_panel() -> Panel:
        url = f"http://{config.PROXY_SERVER_IP}:{config.PROXY_SERVER_PORT}/api/downloads/status"
        try:
            r = httpx.get(url, timeout=3.0)
            if r.status_code == 200:
                data = r.json()
                queue_size = data.get("queue_size", 0)
                active_downloads = data.get("active_downloads", [])

                lines = []
                if active_downloads:
                    lines.append(f"[bold {ui.APPLE_BLUE}]Active Downloads:[/]")
                    for current in active_downloads:
                        lines.append(f"  {current.get('relative_path', 'Unknown')}")
                        mb = current.get('downloaded_mb', 0)
                        progress = current.get('time_progress', '00:00:00')
                        total = current.get('time_total', 'Unknown')
                        lines.append(f"  [dim]Status:[/] Downloading (ffmpeg running...) - {mb} MB | [bold]{progress} / {total}[/]")
                        lines.append("")
                else:
                    lines.append("[dim]No active downloads.[/]")

                lines.append("")
                lines.append(f"Queue Size: {queue_size}")
                
                queue_items = data.get("queue_items", [])
                if queue_items:
                    for idx, item in enumerate(queue_items, 1):
                        name = item.get("relative_path", "Unknown") if isinstance(item, dict) else item
                        lines.append(f"  {idx}. [dim]{name}[/]")

                return Panel(
                    "\n".join(lines),
                    title="Live Status (Refresh: 5s)",
                    border_style=ui.BORDER_GRAY,
                    padding=(1, 2),
                )
            else:
                return Panel(
                    f"[bold {ui.SOFT_RED}]Server returned error: {r.status_code}[/]",
                    title="Error",
                    border_style=ui.SOFT_RED,
                )
        except Exception as e:
            return Panel(
                f"[bold {ui.SOFT_RED}]Failed to contact proxy: {e}[/]",
                title="Error",
                border_style=ui.SOFT_RED,
            )

    try:
        with Live(get_status_panel(), refresh_per_second=1, console=ui.console) as live:
            while True:
                time.sleep(5)
                live.update(get_status_panel())
    except KeyboardInterrupt:
        pass


# ──────────────────────────────────────────────────────────────────────────────
# Playback
# ──────────────────────────────────────────────────────────────────────────────


def handle_tv_show(scraper: SCScraper, sc_title: dict[str, Any]) -> None:
    title_id: int = sc_title["id"]
    slug: str = sc_title.get("slug", "")
    name = sc_title.get("name", "Unknown")

    with ui.spinner("Fetching seasons..."):
        details = scraper.get_title_details(title_id, slug)

    seasons = details.get("title", {}).get("seasons", [])
    if not seasons:
        ui.show_error("No seasons found.")
        return

    while True:
        ui.clear_screen()
        ui.print_header()
        ui.show_info(f"Show: {name}")
        season = ui.select_season(seasons)
        if not season or season == "BACK":
            break

        season_num: int = season.get("number", 1)
        with ui.spinner("Fetching episodes..."):
            season_data = scraper.get_season_details(title_id, slug, season_num)

        episodes = season_data.get("loadedSeason", {}).get("episodes", [])
        if not episodes:
            ui.show_error("No episodes found.")
            input("\nPress Enter to return...")
            continue

        last_episode = None
        while True:
            downloaded_nums = get_downloaded_ep_nums(safe_filename(name), season_num)
            downloaded_ids = {
                ep["id"]
                for ep in episodes
                if ep.get("number") in downloaded_nums and "id" in ep
            }

            ui.clear_screen()
            ui.print_header()
            ui.show_info(f"Show: {name} (Season {season_num})")
            episode = ui.select_episode(episodes, downloaded_ids, default=last_episode)
            if not episode or episode == "BACK":
                break

            last_episode = episode

            ep_id: int = episode.get("id", 0)
            ep_num: int = episode.get("number", 0)
            is_downloaded = ep_num in downloaded_nums

            if ui.SERVER_ONLINE:
                ep_action = ui.select_episode_action(is_downloaded)
                if not ep_action or ep_action == "BACK":
                    continue
            else:
                ep_action = "PLAY"

            if ep_action == "DOWNLOAD":
                ep_name = safe_filename(episode.get("name", f"Episode {ep_num}"))
                rel_path = f"{name}/Season {season_num:02d}/{name} S{season_num:02d}E{ep_num:02d} - {ep_name}.mkv"
                if _queue_download(title_id, ep_id, "tv", rel_path):
                    ui.show_success("Queued episode for background download.")
                input("\nPress Enter to continue...")
                continue

            if is_downloaded:
                target_dir = os.path.join(config.NFS_SHOWS_PATH, safe_filename(name), f"Season {season_num:02d}")
                play_target = None
                for f in os.listdir(target_dir):
                    if f.endswith(".mkv") and f"S{season_num:02d}E{ep_num:02d}" in f:
                        play_target = os.path.join(target_dir, f)
                        break
                        
                if not play_target:
                    ui.show_error("Physical file not found despite being marked as downloaded.")
                    input("\nPress Enter to return...")
                    continue

                ui.show_info(f"Opening physical file ({config.PLAYER_APP})...")
                import subprocess

                if config.PLAYER_APP.lower() == "iina":
                    # Use --keep-running so it waits for the video to finish before returning to the menu
                    cmd = [
                        "/Applications/IINA.app/Contents/MacOS/iina-cli",
                        "--keep-running",
                        play_target,
                    ]
                elif config.PLAYER_APP.lower() == "vlc":
                    cmd = ["/Applications/VLC.app/Contents/MacOS/VLC", play_target]
                else:
                    cmd = ["open", "-a", config.PLAYER_APP, play_target]

                try:
                    subprocess.run(cmd, check=False)
                except FileNotFoundError:
                    ui.show_error(f"Player executable not found: {config.PLAYER_APP}")
            else:
                with local_proxy() as base_url:
                    play_target = _strm_url(base_url, title_id, ep_id)

                    try:
                        import urllib.request
                        import re

                        resp = urllib.request.urlopen(play_target, timeout=3)
                        text = resp.read().decode('utf-8')
                        res_match = re.search(r"RESOLUTION=\d+x(\d+)", text)
                        if res_match:
                            ui.show_success(
                                f"Stream quality locked at: {res_match.group(1)}p"
                            )
                    except Exception:
                        pass

                    ui.show_info(f"Streaming via proxy ({config.PLAYER_APP})...")
                    import subprocess

                    # When using fake M3U8 fallback, the player needs the referer to fetch the actual stream.
                    referer_arg = "--http-header-fields=Referer: https://vixcloud.co/"
                    
                    if config.PLAYER_APP.lower() == "iina":
                        cmd = [
                            "/Applications/IINA.app/Contents/MacOS/iina-cli",
                            "--keep-running",
                            "--mpv-http-header-fields=Referer: https://vixcloud.co/",
                            play_target,
                        ]
                    elif config.PLAYER_APP.lower() == "vlc":
                        # VLC uses --http-referrer
                        cmd = ["/Applications/VLC.app/Contents/MacOS/VLC", "--http-referrer=https://vixcloud.co/", play_target]
                    else:
                        cmd = [config.PLAYER_APP, play_target, referer_arg]

                    try:
                        subprocess.run(cmd, check=False)
                    except FileNotFoundError:
                        ui.show_error(
                            f"Player executable not found: {config.PLAYER_APP}"
                        )


def handle_movie(scraper: SCScraper, sc_title: dict[str, Any]) -> None:
    title_id: int = sc_title["id"]
    slug: str = sc_title.get("slug", "")

    with ui.spinner("Fetching metadata..."):
        details = scraper.get_title_details(title_id, slug)

    ep_id = extract_movie_ep_id(details)

    name = safe_filename(sc_title.get("name", "Unknown"))
    movie_dir = os.path.join(config.NFS_MOVIES_PATH, name)

    has_mkv = any(f.endswith(".mkv") for f in os.listdir(movie_dir)) if os.path.exists(movie_dir) else False

    if has_mkv:
        play_target = None
        for f in os.listdir(movie_dir):
            if f.endswith(".mkv"):
                play_target = os.path.join(movie_dir, f)
                break
                
        if not play_target:
            ui.show_error("Physical file not found despite being marked as downloaded.")
            return

        ui.show_info(f"Opening physical file ({config.PLAYER_APP})...")
        import subprocess

        if config.PLAYER_APP.lower() == "iina":
            cmd = [
                "/Applications/IINA.app/Contents/MacOS/iina-cli",
                "--keep-running",
                play_target,
            ]
        elif config.PLAYER_APP.lower() == "vlc":
            cmd = ["/Applications/VLC.app/Contents/MacOS/VLC", play_target]
        else:
            cmd = ["open", "-a", config.PLAYER_APP, play_target]

        try:
            subprocess.run(cmd, check=False)
        except FileNotFoundError:
            ui.show_error(f"Player executable not found: {config.PLAYER_APP}")
    else:
        with local_proxy() as base_url:
            play_target = _strm_url(base_url, title_id, ep_id)

            try:
                import urllib.request
                import re

                resp = urllib.request.urlopen(play_target, timeout=3)
                text = resp.read().decode('utf-8')
                res_match = re.search(r"RESOLUTION=\d+x(\d+)", text)
                if res_match:
                    ui.show_success(f"Stream quality locked at: {res_match.group(1)}p")
            except Exception:
                pass

            ui.show_info(f"Streaming via proxy ({config.PLAYER_APP})...")

            import subprocess

            if config.PLAYER_APP.lower() == "iina":
                cmd = [
                    "/Applications/IINA.app/Contents/MacOS/iina-cli",
                    "--keep-running",
                    play_target,
                ]
            elif config.PLAYER_APP.lower() == "vlc":
                cmd = ["/Applications/VLC.app/Contents/MacOS/VLC", play_target]
            else:
                cmd = [config.PLAYER_APP, play_target]

            try:
                subprocess.run(cmd, check=False)
            except FileNotFoundError:
                ui.show_error(f"Player executable not found: {config.PLAYER_APP}")


# ──────────────────────────────────────────────────────────────────────────────
# Entrypoint
# ──────────────────────────────────────────────────────────────────────────────


def main() -> None:
    ui.clear_screen()
    with ui.spinner("Checking system status..."):
        try:
            r = httpx.get(
                f"http://{config.PROXY_SERVER_IP}:{config.PROXY_SERVER_PORT}/health",
                timeout=1.0,
            )
            ui.SERVER_ONLINE = r.status_code == 200
        except Exception:
            ui.SERVER_ONLINE = False

        ui.NFS_ONLINE = os.path.exists(config.NFS_SHOWS_PATH) and os.path.exists(
            config.NFS_MOVIES_PATH
        )

    scraper = SCScraper()
    with ui.spinner("Initializing session & checking account limits..."):
        scraper.init_session()
        ui.MAX_QUALITY = scraper.check_global_quality()

    try:
        while True:
            ui.clear_screen()
            ui.print_header()

            if not ui.SERVER_ONLINE and not ui.NFS_ONLINE:
                main_action = "SEARCH"
            else:
                main_action = ui.select_main_menu()
                if not main_action or main_action == "EXIT":
                    ui.show_info("Goodbye.")
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
                    ui.show_info("Your library is empty. Export some titles first.")
                    input("\nPress Enter to return...")
                    continue

                selected = ui.select_library_item(library_items)

            elif main_action == "SEARCH":
                query = ui.ask_search_query()
                if query is None:
                    ui.show_info("Goodbye.")
                    break
                if not query.strip():
                    continue

                with ui.spinner("Searching..."):
                    results = scraper.search(query)

                if not results:
                    ui.show_error("No results found.")
                    input("\nPress Enter to return...")
                    continue

                ui.clear_screen()
                ui.print_header()
                selected = ui.select_sc_search_result(results)

            if not selected or selected == "BACK":
                continue

            # If it's from library and missing slug, fetch it silently
            if not selected.get("slug"):
                with ui.spinner("Resolving metadata..."):
                    search_results = scraper.search(selected.get("name", ""))
                    for r in search_results:
                        if r.get("id") == selected.get("id"):
                            selected["slug"] = r.get("slug", "")
                            break
                if not selected.get("slug"):
                    ui.show_error(
                        "Could not resolve metadata for this title on the server."
                    )
                    input("\nPress Enter to return...")
                    continue

            # Title selected -> Type specific flow
            while True:
                ui.clear_screen()
                ui.print_header()

                name = selected.get("name", "Unknown")
                is_tv = selected.get("type") == "tv"
                kind = "TV" if is_tv else "Movie"
                ui.show_info(f"Title: [bold white]{name}[/] ({kind})")

                if is_tv:
                    action = ui.select_tv_action() if ui.SERVER_ONLINE else "BROWSE"
                    if not action or action == "BACK":
                        break
                        
                    if action == "BROWSE":
                        handle_tv_show(scraper, selected)
                        if not ui.SERVER_ONLINE:
                            break
                    elif action == "BATCH_DOWNLOAD":
                        download_offline(scraper, selected)
                        input("\nPress Enter to continue...")
                    elif action == "MANAGE":
                        manage_action = ui.select_manage_action()
                        if manage_action == "EXPORT":
                            export_media(scraper, selected)
                            input("\nPress Enter to continue...")
                        elif manage_action == "CLEANUP":
                            cleanup_offline(scraper, selected)
                            input("\nPress Enter to continue...")
                else:
                    movie_dir = os.path.join(config.NFS_MOVIES_PATH, safe_filename(name))
                    has_mkv = any(f.endswith(".mkv") for f in os.listdir(movie_dir)) if os.path.exists(movie_dir) else False
                    
                    action = ui.select_movie_action(has_mkv) if ui.SERVER_ONLINE else "PLAY"
                    if not action or action == "BACK":
                        break
                        
                    if action == "PLAY":
                        handle_movie(scraper, selected)
                        if not ui.SERVER_ONLINE:
                            break
                    elif action == "DOWNLOAD":
                        download_offline(scraper, selected)
                        input("\nPress Enter to continue...")
                    elif action == "MANAGE":
                        manage_action = ui.select_manage_action()
                        if manage_action == "EXPORT":
                            export_media(scraper, selected)
                            input("\nPress Enter to continue...")
                        elif manage_action == "CLEANUP":
                            cleanup_offline(scraper, selected)
                            input("\nPress Enter to continue...")

    except (KeyboardInterrupt, EOFError):
        ui.console.print("\n[dim]Aborted by user.[/]")
    finally:
        scraper.close()


if __name__ == "__main__":
    main()
