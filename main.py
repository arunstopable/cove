import sys
import subprocess
import questionary
from rich import print as rprint

import httpx
import ui
import db_client
from sc_scraper import SCScraper

import concurrent.futures

def download_sub(sub):
    try:
        resp = httpx.get(sub['url'], headers={"Referer": "https://vixcloud.co/"}, timeout=5.0)
        if resp.status_code == 200:
            safe_name = "".join(c if c.isalnum() or c in " []()" else "_" for c in sub['name'])
            sub_path = f"/tmp/{safe_name}.vtt"
            with open(sub_path, "w", encoding="utf-8") as f:
                f.write(resp.text)
            return sub_path
    except Exception as e:
        rprint(f"[yellow]Warning: Could not download subtitle {sub['name']}: {e}[/yellow]")
    return None

def play_stream(url: str, subs: list = None):
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
        if subs:
            sub_paths = []
            with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
                futures = [executor.submit(download_sub, sub) for sub in subs]
                for future in concurrent.futures.as_completed(futures):
                    res = future.result()
                    if res:
                        sub_paths.append(res)
            
            if sub_paths:
                cmd.append(f"--mpv-sub-files={':'.join(sub_paths)}")
                
        subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception as e:
        rprint(f"[bold red]Failed to launch IINA: {e}[/bold red]")

def handle_tv_show(scraper: SCScraper, sc_title, watched_episodes: set = None):
    if watched_episodes is None:
        watched_episodes = set()

    with ui.show_spinner("Fetching show details...") as progress:
        task = progress.add_task("Fetching", total=None)
        details = scraper.get_title_details(sc_title['id'], sc_title['slug'])
    
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
            
        season_num = season.get('number')
        
        with ui.show_spinner(f"Fetching Season {season_num} episodes...") as progress:
            task = progress.add_task("Fetching", total=None)
            season_data = scraper.get_season_details(sc_title['id'], sc_title['slug'], season_num)
            
        episodes = season_data.get('loadedSeason', {}).get('episodes', [])
        
        # Mark watched
        for ep in episodes:
            ep_num = ep.get('number')
            ep['is_watched'] = (season_num, ep_num) in watched_episodes
            
        while True:
            episode = ui.select_episode(episodes)
            if not episode or episode == "BACK":
                break
                
            # Play episode
            with ui.show_spinner("Extracting stream URL and subtitles...") as progress:
                task = progress.add_task("Extracting", total=None)
                m3u8_url, subs = scraper.get_stream_url(sc_title['id'], episode['id'])
                
            if m3u8_url:
                play_stream(m3u8_url, subs)
                # After playing, we return so user can watch. 
                # (We don't block the UI, but usually you watch one thing at a time)
            else:
                rprint("[bold red]Failed to extract stream URL. Domain/Inertia might have changed.[/bold red]")

def main():
    ui.print_header()
    
    scraper = SCScraper()
    
    with ui.show_spinner("Initializing engine...") as progress:
        task = progress.add_task("Init", total=None)
        scraper.init_session()
        
    if not scraper.active_domain:
        rprint("[red]Failed to resolve StreamingCommunity domain.[/red]")
        sys.exit(1)
        
    rprint(f"[dim]Active domain: {scraper.active_domain}[/dim]\n")

    while True:
        logged_in = db_client.is_logged_in()
        action = ui.select_action(logged_in)
        
        if action == "Exit" or action is None:
            break
            
        elif action == "Login to Kino":
            email = questionary.text("Email:").ask()
            if not email: continue
            password = questionary.password("Password:").ask()
            if not password: continue
            
            with ui.show_spinner("Logging in...") as progress:
                task = progress.add_task("Login", total=None)
                success, msg = db_client.login(email, password)
            if success:
                rprint("[bold green]Successfully logged in![/bold green]")
            else:
                rprint(f"[bold red]Login failed: {msg}[/bold red]")
                
        elif action == "Logout from Kino":
            db_client.clear_session()
            rprint("[bold yellow]Logged out successfully.[/bold yellow]")
            
        elif action == "My List (Watching)":
            with ui.show_spinner("Fetching your list from Kino...") as progress:
                task = progress.add_task("Fetching", total=None)
                my_list = db_client.get_watching_list()
                
            if not my_list:
                rprint("[yellow]Your watching list is empty or could not be fetched.[/yellow]")
                continue
                
            # Fetch TMDB details to show proper titles
            for item in my_list:
                if 'title' not in item or not item['title']:
                    tmdb_data = db_client.fetch_tmdb_details(item['tmdb_id'], item['media_type'])
                    if tmdb_data:
                        item['title'] = tmdb_data['title']
                    else:
                        item['title'] = f"Unknown ({item['tmdb_id']})"
                        
            while True:
                selected_item = ui.select_media(my_list)
                if not selected_item or selected_item == "BACK":
                    break
                    
                # We need to find this item on StreamingCommunity
                title_to_search = selected_item['title']
                with ui.show_spinner(f"Searching SC for '{title_to_search}'...") as progress:
                    task = progress.add_task("Searching", total=None)
                    results = scraper.search(title_to_search)
                    
                if not results:
                    rprint(f"[red]No matches found for '{title_to_search}' on StreamingCommunity.[/red]")
                    continue
                    
                sc_title = None
                if len(results) == 1:
                    sc_title = results[0]
                else:
                    # Let user disambiguate
                    sc_title = ui.select_sc_search_result(results)
                    
                if not sc_title or sc_title == "BACK":
                    continue
                    
                if selected_item['media_type'] == 'tv':
                    # Fetch progress
                    with ui.show_spinner("Fetching progress from Kino...") as progress:
                        task = progress.add_task("Fetching progress", total=None)
                        watched_episodes = db_client.get_watched_episodes(selected_item['tmdb_id'])
                        
                    handle_tv_show(scraper, sc_title, watched_episodes)
                else:
                    # Movie logic
                    with ui.show_spinner("Extracting stream URL and subtitles...") as progress:
                        task = progress.add_task("Extracting", total=None)
                        # Movies usually have season 1 episode 1 or similar structure, wait...
                        # In SC, movies have title details without seasons.
                        # We just call get_stream_url with the title id. Wait, episode id is needed?
                        # Let's fetch details to get the "episode" id for the movie.
                        details = scraper.get_title_details(sc_title['id'], sc_title['slug'])
                        # For movies, there's usually a loadedSeason -> episodes -> index 0
                        try:
                            ep_id = details['title']['episodes'][0]['id'] # SC might structure movies this way
                            m3u8_url, subs = scraper.get_stream_url(sc_title['id'], ep_id)
                        except:
                            m3u8_url = None
                            subs = None
                            
                        if m3u8_url:
                            play_stream(m3u8_url, subs)
                        else:
                            rprint("[bold red]Failed to extract stream URL for movie.[/bold red]")
                            
        elif action == "Search StreamingCommunity":
            query = questionary.text("Enter title to search:").ask()
            if not query:
                continue
                
            with ui.show_spinner(f"Searching for '{query}'...") as progress:
                task = progress.add_task("Searching", total=None)
                results = scraper.search(query)
                
            if not results:
                rprint("[red]No results found.[/red]")
                continue
                
            sc_title = ui.select_sc_search_result(results)
            if not sc_title or sc_title == "BACK":
                continue
                
            if sc_title.get('type') == 'tv':
                handle_tv_show(scraper, sc_title, set())
            else:
                # Movie
                with ui.show_spinner("Extracting stream URL and subtitles...") as progress:
                    task = progress.add_task("Extracting", total=None)
                    details = scraper.get_title_details(sc_title['id'], sc_title['slug'])
                    try:
                        ep_id = details['title']['episodes'][0]['id']
                        m3u8_url, subs = scraper.get_stream_url(sc_title['id'], ep_id)
                    except Exception as e:
                        print(e)
                        m3u8_url = None
                        subs = None
                        
                    if m3u8_url:
                        play_stream(m3u8_url, subs)
                    else:
                        rprint("[bold red]Failed to extract stream URL.[/bold red]")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        rprint("\n[dim]Goodbye![/dim]")
        sys.exit(0)
