import questionary
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text
from rich import print as rprint
from rich.progress import Progress, SpinnerColumn, TextColumn

console = Console()

def print_header():
    console.print(Panel.fit("[bold cyan]Cove 2.0[/bold cyan]\n[dim]StreamingCommunity CLI[/dim]", border_style="cyan"))

def show_spinner(task_msg: str):
    return Progress(
        SpinnerColumn(spinner_name="dots", style="cyan"),
        TextColumn("[cyan]{task.description}"),
        transient=True
    )

def select_action(is_logged_in: bool):
    choices = []
    if is_logged_in:
        choices.append("My List (Watching)")
        choices.append("Search StreamingCommunity")
        choices.append("Logout from Kino")
    else:
        choices.append("Search StreamingCommunity")
        choices.append("Login to Kino")
    choices.append("Exit")

    return questionary.select(
        "What do you want to do?",
        choices=choices,
        style=questionary.Style([
            ('qmark', 'fg:#00ffff bold'),
            ('question', 'bold'),
            ('answer', 'fg:#00ffff bold'),
            ('pointer', 'fg:#00ffff bold'),
            ('highlighted', 'fg:#00ffff bold'),
        ])
    ).ask()

def select_media(media_list):
    """Select a media from the watching list"""
    choices = []
    for item in media_list:
        title = item.get("title", f"TMDB ID: {item['tmdb_id']}")
        choices.append(questionary.Choice(title=title, value=item))
    choices.append(questionary.Choice(title="[Back]", value="BACK"))
    
    return questionary.select(
        "Select a title:",
        choices=choices,
    ).ask()

def select_sc_search_result(results):
    choices = []
    for r in results:
        title = r.get('name', 'Unknown')
        media_type = "TV" if r.get('type') == 'tv' else "Movie"
        choices.append(questionary.Choice(title=f"{title} [{media_type}]", value=r))
    choices.append(questionary.Choice(title="[Back]", value="BACK"))
    
    return questionary.select(
        "Select a search result:",
        choices=choices,
    ).ask()

def select_season(seasons):
    choices = []
    for s in seasons:
        title = f"Season {s.get('number', '?')} ({s.get('episodes_count', 0)} eps)"
        choices.append(questionary.Choice(title=title, value=s))
    choices.append(questionary.Choice(title="[Back]", value="BACK"))
    
    return questionary.select(
        "Select a season:",
        choices=choices,
    ).ask()

def select_episode(episodes, watched_eps=None):
    if watched_eps is None:
        watched_eps = set()
        
    choices = []
    for ep in episodes:
        season_num = ep.get('season_id') # Needs mapping or we just use passed context
        ep_num = ep.get('number', 0)
        
        # Check if watched
        is_watched = False
        # We need the real season number to check watched status reliably.
        # This will be handled in main.py by formatting the title
        
        title = f"Ep {ep_num}: {ep.get('name', 'Untitled')}"
        if ep.get('is_watched'):
            title = f"✓ {title}"
        else:
            title = f"  {title}"
            
        choices.append(questionary.Choice(title=title, value=ep))
    choices.append(questionary.Choice(title="[Back]", value="BACK"))
    
    return questionary.select(
        "Select an episode:",
        choices=choices,
    ).ask()
