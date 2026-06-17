import sys
import os
import subprocess
import questionary
from rich import print as rprint
from typing import Any, Optional

import httpx
import ui
from sc_scraper import SCScraper
import config
import re

def safe_filename(name: str) -> str:
    return re.sub(r'[\\/*?:"<>|]', "", name).strip()

def export_media(scraper: SCScraper, sc_title: dict[str, Any]) -> None:
    if sc_title.get('type') == 'tv':
        base_dir = "/Volumes/Logan/shows"
    else:
        base_dir = "/Volumes/Logan/movies"
        
    if not os.path.exists(base_dir):
        rprint(f"[bold red]Error: The network volume '{base_dir}' is not mounted.[/bold red]")
        rprint("[yellow]Please mount your NFS volumes first and try again.[/yellow]")
        return
        
    server_ip = config.PROXY_SERVER_IP
        
    title_id = sc_title['id']
    name = safe_filename(sc_title.get('name', 'Unknown'))
    
    if sc_title.get('type') == 'tv':
        shows_dir = os.path.join(base_dir, name)
        os.makedirs(shows_dir, exist_ok=True)
        
        with ui.show_spinner(f"Fetching details for {name}...") as progress:
            task = progress.add_task("Fetching", total=None)
            details = scraper.get_title_details(title_id, sc_title.get('slug', ''))
            
        seasons = details.get('title', {}).get('seasons', [])
        if not seasons:
            rprint("[red]No seasons found.[/red]")
            return
            
        for season in seasons:
            season_num = season.get('number', 1)
            season_dir = os.path.join(shows_dir, f"Season {season_num:02d}")
            os.makedirs(season_dir, exist_ok=True)
            
            with ui.show_spinner(f"Exporting Season {season_num}...") as progress:
                task = progress.add_task("Exporting", total=None)
                season_data = scraper.get_season_details(title_id, sc_title.get('slug', ''), season_num)
                episodes = season_data.get('loadedSeason', {}).get('episodes', [])
                
                for ep in episodes:
                    ep_num = ep.get('number', 0)
                    ep_id = ep['id']
                    ep_name = safe_filename(ep.get('name', f"Episode {ep_num}"))
                    
                    base_name = f"{name} S{season_num:02d}E{ep_num:02d} - {ep_name}"
                    strm_path = os.path.join(season_dir, f"{base_name}.strm")
                    with open(strm_path, "w", encoding="utf-8") as f:
                        f.write(f"http://{server_ip}:8000/play.m3u8?title_id={title_id}&episode_id={ep_id}")
        rprint(f"[green]Successfully exported TV Show: {name}[/green]")
        rprint(f"[dim]Saved to: {shows_dir}[/dim]")
        
    else: # Movie
        movies_dir = os.path.join(base_dir, name)
        os.makedirs(movies_dir, exist_ok=True)
        
        with ui.show_spinner("Exporting movie...") as progress:
            task = progress.add_task("Exporting", total=None)
            details = scraper.get_title_details(title_id, sc_title.get('slug', ''))
            
            ep_id = None
            try:
                ep_id = details.get('title', {}).get('episodes', [{}])[0].get('id')
                if not ep_id:
                    ep_id = details.get('loadedSeason', {}).get('episodes', [{}])[0].get('id')
            except Exception:
                pass
                
            if not ep_id:
                rprint("[red]Could not find movie episode ID for export.[/red]")
                return
                
            strm_path = os.path.join(movies_dir, f"{name}.strm")
            with open(strm_path, "w", encoding="utf-8") as f:
                f.write(f"http://{server_ip}:8000/play.m3u8?title_id={title_id}&episode_id={ep_id}")
                
        rprint(f"[green]Successfully exported Movie: {name}[/green]")
        rprint(f"[dim]Saved to: {movies_dir}[/dim]")

def play_stream(url: str) -> None:
    rprint(f"\n[bold green]Launching IINA...[/bold green]")
    try:
        ua = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        cmd = [
            "open", "-a", "IINA", 
            "--args", 
            url,
            f"--mpv-user-agent={ua}",
            "--mpv-http-header-fields=Referer: https://vixcloud.co/",
            "--mpv-slang=ita,it,Italian"
        ]
                
        subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception as e:
        rprint(f"[bold red]Failed to launch IINA: {e}[/bold red]")

def handle_tv_show(scraper: SCScraper, sc_title: dict[str, Any]) -> None:

    with ui.show_spinner("Fetching show details...") as progress:
        task = progress.add_task("Fetching", total=None)
        details = scraper.get_title_details(sc_title['id'], sc_title.get('slug', ''))
    
    if not details:
        rprint("[red]Could not fetch details.[/red]")
        return

    seasons = details.get('title', {}).get('seasons', [])
    if not seasons:
        rprint("[red]No seasons found.[/red]")
        return

    while True:
        season = ui.select_season(seasons)
        if not season or season == "BACK":
            break
            
        if isinstance(season, dict):
            season_num = season.get('number', 1)
            
            with ui.show_spinner(f"Fetching Season {season_num} episodes...") as progress:
                task = progress.add_task("Fetching", total=None)
                season_data = scraper.get_season_details(sc_title['id'], sc_title.get('slug', ''), season_num)
                
            episodes = season_data.get('loadedSeason', {}).get('episodes', [])
            
            # No watched tracking
                
            while True:
                episode = ui.select_episode(episodes)
                if not episode or episode == "BACK":
                    break
                    
                if isinstance(episode, dict):
                    # Play episode
                    with ui.show_spinner("Extracting stream URL...") as progress:
                        task = progress.add_task("Extracting", total=None)
                        m3u8_url = scraper.get_stream_url(sc_title['id'], episode['id'])
                        
                    if m3u8_url:
                        play_stream(m3u8_url)
                    else:
                        rprint("[bold red]Failed to extract stream URL. Domain/Inertia might have changed.[/bold red]")

def handle_movie(scraper: SCScraper, sc_title: dict[str, Any]) -> None:
    """Handles stream extraction and playback for a movie."""
    with ui.show_spinner("Extracting stream URL...") as progress:
        task = progress.add_task("Extracting", total=None)
        details = scraper.get_title_details(sc_title['id'], sc_title.get('slug', ''))
        try:
            # For movies, SC usually has a single episode under 'loadedSeason' or 'title.episodes'
            ep_id = details.get('title', {}).get('episodes', [{}])[0].get('id')
            if not ep_id:
                # Fallback if structure is slightly different
                ep_id = details.get('loadedSeason', {}).get('episodes', [{}])[0].get('id')
                
            if not ep_id:
                raise ValueError("Could not find movie episode ID in details.")
                
            m3u8_url = scraper.get_stream_url(sc_title['id'], ep_id)
        except Exception as e:
            m3u8_url = None
            rprint(f"[yellow]Warning during movie extraction: {e}[/yellow]")
            
        if m3u8_url:
            play_stream(m3u8_url)
        else:
            rprint("[bold red]Failed to extract stream URL for movie.[/bold red]")


def main() -> None:
    os.system('clear')
    ui.print_header()
    
    scraper = SCScraper()
    
    with ui.show_spinner("Initializing engine...") as progress:
        task = progress.add_task("Init", total=None)
        scraper.init_session()
        
    if not scraper.active_domain:
        rprint("[red]Failed to resolve streaming domain.[/red]")
        sys.exit(1)
        
    rprint(f"[dim]Active domain: {scraper.active_domain}[/dim]\n")

    while True:
        query = questionary.text("Enter title to search (or empty to exit):").ask()
        if not query:
            break
            
        with ui.show_spinner(f"Searching for '{query}'...") as progress:
            task = progress.add_task("Searching", total=None)
            results = scraper.search(query)
            
        if not results:
            rprint("[red]No results found.[/red]")
            continue
            
        selected_res = ui.select_sc_search_result(results)
        if not selected_res or selected_res == "BACK" or not isinstance(selected_res, dict):
            continue
            
        sc_title_search = selected_res
        
        action = ui.select_action()
        if not action or action == "BACK":
            continue
            
        if action == "EXPORT":
            export_media(scraper, sc_title_search)
        elif action == "PLAY":
            if sc_title_search.get('type') == 'tv':
                handle_tv_show(scraper, sc_title_search)
            else:
                handle_movie(scraper, sc_title_search)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        rprint("\n[dim]Goodbye![/dim]")
        sys.exit(0)

