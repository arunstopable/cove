import questionary
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from typing import Any, Optional, Union

console = Console()

def print_header() -> None:
    console.print(Panel.fit("[bold cyan]Cove 2.0[/bold cyan]\n[dim]StreamingCommunity CLI[/dim]", border_style="cyan"))

def show_spinner(task_msg: str) -> Progress:
    return Progress(
        SpinnerColumn(spinner_name="dots", style="cyan"),
        TextColumn("[cyan]{task.description}"),
        transient=True
    )

def select_action(is_logged_in: bool) -> Optional[str]:
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

def _add_back_option(choices: list[Any]) -> list[Any]:
    choices.append(questionary.Choice(title="[Back]", value="BACK"))
    return choices

def select_media(media_list: list[dict[str, Any]]) -> Union[dict[str, Any], str, None]:
    """Select a media from the watching list"""
    choices = []
    for item in media_list:
        title = item.get("title", f"TMDB ID: {item.get('tmdb_id', 'Unknown')}")
        choices.append(questionary.Choice(title=title, value=item))
    
    return questionary.select(
        "Select a title:",
        choices=_add_back_option(choices),
    ).ask()

def select_sc_search_result(results: list[dict[str, Any]]) -> Union[dict[str, Any], str, None]:
    choices = []
    for r in results:
        title = r.get('name', 'Unknown')
        media_type = "TV" if r.get('type') == 'tv' else "Movie"
        choices.append(questionary.Choice(title=f"{title} [{media_type}]", value=r))
        
    return questionary.select(
        "Select a search result:",
        choices=_add_back_option(choices),
    ).ask()

def select_season(seasons: list[dict[str, Any]]) -> Union[dict[str, Any], str, None]:
    choices = []
    for s in seasons:
        title = f"Season {s.get('number', '?')} ({s.get('episodes_count', 0)} eps)"
        choices.append(questionary.Choice(title=title, value=s))
        
    return questionary.select(
        "Select a season:",
        choices=_add_back_option(choices),
    ).ask()

def select_episode(episodes: list[dict[str, Any]], watched_eps: Optional[set[tuple[int, int]]] = None) -> Union[dict[str, Any], str, None]:
    if watched_eps is None:
        watched_eps = set()
        
    choices = []
    for ep in episodes:
        ep_num = ep.get('number', 0)
        
        title = f"Ep {ep_num}: {ep.get('name', 'Untitled')}"
        if ep.get('is_watched'):
            title = f"✓ {title}"
        else:
            title = f"  {title}"
            
        choices.append(questionary.Choice(title=title, value=ep))
        
    return questionary.select(
        "Select an episode:",
        choices=_add_back_option(choices),
    ).ask()
