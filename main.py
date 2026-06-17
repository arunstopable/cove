"""
Cove CLI — search, play, and export StreamingCommunity titles.

Usage:
  python3 main.py          Interactive CLI mode
"""

import os
import re
import subprocess
import sys
from typing import Any, Optional

from rich import print as rprint

import config
import ui
from sc_scraper import SCScraper


# ──────────────────────────────────────────────────────────────────────────────
# Utilities
# ──────────────────────────────────────────────────────────────────────────────

def safe_filename(name: str) -> str:
    """Strip characters that are illegal in filenames on Windows, macOS, and Linux."""
    return re.sub(r'[\\/*?:"<>|]', "", name).strip()


def _strm_url(title_id: int, episode_id: int) -> str:
    """Build the .strm content URL pointing to the proxy /stream.mkv endpoint."""
    return (
        f"http://{config.PROXY_SERVER_IP}:{config.PROXY_SERVER_PORT}"
        f"/stream.mkv?title_id={title_id}&episode_id={episode_id}"
    )


def _write_strm(path: str, content: str) -> bool:
    """
    Write a .strm file.
    Returns True if written, False if the file already existed (skipped).
    """
    if os.path.exists(path):
        return False
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(content)
    return True


# ──────────────────────────────────────────────────────────────────────────────
# Export
# ──────────────────────────────────────────────────────────────────────────────

def export_media(scraper: SCScraper, sc_title: dict[str, Any]) -> None:
    """Export a title (TV show or movie) as .strm files for Jellyfin."""
    is_tv = sc_title.get("type") == "tv"
    base_dir = config.NFS_SHOWS_PATH if is_tv else config.NFS_MOVIES_PATH

    if not os.path.exists(base_dir):
        rprint(f"[bold red]Error:[/bold red] NFS volume not mounted at [yellow]'{base_dir}'[/yellow].")
        rprint("[dim]Please mount your NFS volume and try again.[/dim]")
        return

    title_id: int = sc_title["id"]
    name = safe_filename(sc_title.get("name", "Unknown"))

    if is_tv:
        _export_tv_show(scraper, title_id, name, sc_title.get("slug", ""), base_dir)
    else:
        _export_movie(scraper, title_id, name, sc_title.get("slug", ""), base_dir)


def _export_tv_show(
    scraper: SCScraper,
    title_id: int,
    name: str,
    slug: str,
    base_dir: str,
) -> None:
    shows_dir = os.path.join(base_dir, name)
    os.makedirs(shows_dir, exist_ok=True)

    with ui.spinner(f"Fetching details for {name}…"):
        details = scraper.get_title_details(title_id, slug)

    seasons = details.get("title", {}).get("seasons", [])
    if not seasons:
        rprint("[red]No seasons found for this title.[/red]")
        return

    total_written = 0
    total_skipped = 0

    for season in seasons:
        season_num: int = season.get("number", 1)
        season_dir = os.path.join(shows_dir, f"Season {season_num:02d}")
        os.makedirs(season_dir, exist_ok=True)

        with ui.spinner(f"Exporting Season {season_num}…"):
            season_data = scraper.get_season_details(title_id, slug, season_num)

        episodes = season_data.get("loadedSeason", {}).get("episodes", [])

        for ep in episodes:
            ep_num: int = ep.get("number", 0)
            ep_id: Optional[int] = ep.get("id")
            if not ep_id:
                continue

            ep_name = safe_filename(ep.get("name", f"Episode {ep_num}"))
            base_name = f"{name} S{season_num:02d}E{ep_num:02d} - {ep_name}"
            strm_path = os.path.join(season_dir, f"{base_name}.strm")

            if _write_strm(strm_path, _strm_url(title_id, ep_id)):
                total_written += 1
            else:
                total_skipped += 1

    rprint(f"\n[bold green]✓ Export complete:[/bold green] [cyan]{name}[/cyan]")
    rprint(f"  [dim]Path    :[/dim] {shows_dir}")
    rprint(f"  [dim]Written :[/dim] {total_written} .strm file(s)")
    if total_skipped:
        rprint(f"  [dim]Skipped :[/dim] {total_skipped} already existed")


def _export_movie(
    scraper: SCScraper,
    title_id: int,
    name: str,
    slug: str,
    base_dir: str,
) -> None:
    movies_dir = os.path.join(base_dir, name)
    os.makedirs(movies_dir, exist_ok=True)

    with ui.spinner(f"Fetching details for {name}…"):
        details = scraper.get_title_details(title_id, slug)

    # Primary location: title.episodes[0].id
    ep_id: Optional[int] = None
    episodes_direct = details.get("title", {}).get("episodes", [])
    if episodes_direct:
        ep_id = episodes_direct[0].get("id")

    # Fallback: loadedSeason.episodes[0].id
    if not ep_id:
        fallback = details.get("loadedSeason", {}).get("episodes", [])
        if fallback:
            ep_id = fallback[0].get("id")

    if not ep_id:
        rprint(f"[red]Could not find episode ID for '[cyan]{name}[/cyan]'. Export skipped.[/red]")
        return

    strm_path = os.path.join(movies_dir, f"{name}.strm")
    written = _write_strm(strm_path, _strm_url(title_id, ep_id))

    if written:
        rprint(f"\n[bold green]✓ Export complete:[/bold green] [cyan]{name}[/cyan]")
        rprint(f"  [dim]Path:[/dim] {strm_path}")
    else:
        rprint(f"[yellow]'{name}.strm' already exists — skipped.[/yellow]")


# ──────────────────────────────────────────────────────────────────────────────
# Playback
# ──────────────────────────────────────────────────────────────────────────────

def play_stream(m3u8_url: str) -> None:
    """Launch the configured local player with the given HLS stream URL."""
    player = config.PLAYER_APP
    rprint(f"\n[bold green]Launching {player}…[/bold green]")

    ua = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
    vix_referer = "Referer: https://vixcloud.co/"

    try:
        if player == "IINA":
            cmd = [
                "open", "-a", "IINA",
                "--args",
                m3u8_url,
                f"--mpv-user-agent={ua}",
                f"--mpv-http-header-fields={vix_referer}",
                "--mpv-slang=ita,it,en",
            ]
        elif player == "VLC":
            cmd = [
                "open", "-a", "VLC",
                "--args",
                "--http-referrer=https://vixcloud.co/",
                m3u8_url,
            ]
        elif player == "mpv":
            cmd = [
                "mpv",
                f"--user-agent={ua}",
                "--referrer=https://vixcloud.co/",
                "--slang=ita,en",
                m3u8_url,
            ]
        else:
            rprint(f"[yellow]Unknown player '{player}'. Falling back to IINA.[/yellow]")
            cmd = ["open", "-a", "IINA", "--args", m3u8_url, f"--mpv-user-agent={ua}"]

        subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    except FileNotFoundError:
        rprint(f"[bold red]{player} not found.[/bold red] Check PLAYER_APP in your .env file.")
    except Exception as exc:
        rprint(f"[bold red]Failed to launch {player}: {exc}[/bold red]")


# ──────────────────────────────────────────────────────────────────────────────
# Title handlers
# ──────────────────────────────────────────────────────────────────────────────

def handle_tv_show(scraper: SCScraper, sc_title: dict[str, Any]) -> None:
    """Interactive season → episode → play flow for a TV show."""
    with ui.spinner("Fetching show details…"):
        details = scraper.get_title_details(sc_title["id"], sc_title.get("slug", ""))

    if not details:
        rprint("[red]Could not fetch show details.[/red]")
        return

    seasons = details.get("title", {}).get("seasons", [])
    if not seasons:
        rprint("[red]No seasons found.[/red]")
        return

    while True:
        season = ui.select_season(seasons)
        if not season or season == "BACK":
            break
        if not isinstance(season, dict):
            continue

        season_num: int = season.get("number", 1)

        with ui.spinner(f"Fetching Season {season_num} episodes…"):
            season_data = scraper.get_season_details(
                sc_title["id"], sc_title.get("slug", ""), season_num
            )

        episodes = season_data.get("loadedSeason", {}).get("episodes", [])
        if not episodes:
            rprint(f"[red]No episodes found for Season {season_num}.[/red]")
            continue

        while True:
            episode = ui.select_episode(episodes)
            if not episode or episode == "BACK":
                break
            if not isinstance(episode, dict):
                continue

            with ui.spinner("Extracting stream URL…"):
                m3u8_url = scraper.get_stream_url(sc_title["id"], episode["id"])

            if m3u8_url:
                play_stream(m3u8_url)
            else:
                rprint(
                    "[bold red]Stream extraction failed.[/bold red] "
                    "[dim]The source may have changed.[/dim]"
                )


def handle_movie(scraper: SCScraper, sc_title: dict[str, Any]) -> None:
    """Extract stream URL and play for a movie title."""
    with ui.spinner("Fetching movie details…"):
        details = scraper.get_title_details(sc_title["id"], sc_title.get("slug", ""))

    ep_id: Optional[int] = None
    episodes_direct = details.get("title", {}).get("episodes", [])
    if episodes_direct:
        ep_id = episodes_direct[0].get("id")
    if not ep_id:
        fallback = details.get("loadedSeason", {}).get("episodes", [])
        if fallback:
            ep_id = fallback[0].get("id")

    if not ep_id:
        rprint("[bold red]Could not find episode ID for this movie.[/bold red]")
        return

    with ui.spinner("Extracting stream URL…"):
        m3u8_url = scraper.get_stream_url(sc_title["id"], ep_id)

    if m3u8_url:
        play_stream(m3u8_url)
    else:
        rprint("[bold red]Stream extraction failed for this movie.[/bold red]")


# ──────────────────────────────────────────────────────────────────────────────
# Main loop
# ──────────────────────────────────────────────────────────────────────────────

def main() -> None:
    os.system("clear")
    ui.print_header()

    scraper = SCScraper()

    with ui.spinner("Initializing engine…"):
        scraper.init_session()

    if not scraper.active_domain:
        rprint("[bold red]Failed to resolve streaming domain.[/bold red]")
        rprint("[dim]Check your internet connection and SC_ANCHOR_URL in .env.[/dim]")
        sys.exit(1)

    rprint(f"[dim]Domain: {scraper.active_domain}[/dim]\n")

    import questionary  # local import to keep top-level imports clean

    while True:
        try:
            query: Optional[str] = questionary.text("Search title (or press Enter to exit):").ask()
        except (KeyboardInterrupt, EOFError):
            break

        if not query or not query.strip():
            break

        query = query.strip()

        with ui.spinner(f"Searching for '{query}'…"):
            results = scraper.search(query)

        if not results:
            rprint("[yellow]No results found. Try a different query.[/yellow]")
            continue

        selected = ui.select_sc_search_result(results)
        if not selected or selected == "BACK" or not isinstance(selected, dict):
            continue

        action = ui.select_action()
        if not action or action == "BACK":
            continue

        if action == "EXPORT":
            export_media(scraper, selected)
        elif action == "PLAY":
            if selected.get("type") == "tv":
                handle_tv_show(scraper, selected)
            else:
                handle_movie(scraper, selected)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        rprint("\n[dim]Goodbye![/dim]")
        sys.exit(0)
