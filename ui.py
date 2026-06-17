import questionary
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from typing import Any, Optional, Union
from prompt_toolkit.formatted_text import FormattedText

console = Console()

def print_header() -> None:
    console.print(Panel.fit("[bold cyan]Cove 2.0[/bold cyan]\n[dim]Your personal streaming CLI[/dim]", border_style="cyan"))

def show_spinner(task_msg: str) -> Progress:
    return Progress(
        SpinnerColumn(spinner_name="dots", style="cyan"),
        TextColumn("[cyan]{task.description}"),
        transient=True
    )

def _add_back_option(choices: list[Any]) -> list[Any]:
    choices.append(questionary.Choice(title="[Back]", value="BACK"))
    return choices

def select_sc_search_result(results: list[dict[str, Any]]) -> Union[dict[str, Any], str, None]:
    choices = []
    for r in results:
        title = r.get('name', 'Unknown')
        if r.get('type') == 'tv':
            formatted_title = FormattedText([("class:ansigreen", "• "), ("", title)])
        else:
            formatted_title = FormattedText([("class:ansiblue", "• "), ("", title)])
        choices.append(questionary.Choice(title=formatted_title, value=r))
        
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

def select_episode(episodes: list[dict[str, Any]]) -> Union[dict[str, Any], str, None]:
    choices = []
    for ep in episodes:
        ep_num = ep.get('number', 0)
        
        title = f"Ep {ep_num}: {ep.get('name', 'Untitled')}"

            
        choices.append(questionary.Choice(title=title, value=ep))
        
    return questionary.select(
        "Select an episode:",
        choices=_add_back_option(choices),
    ).ask()

def select_action() -> str:
    return questionary.select(
        "What do you want to do?",
        choices=[
            questionary.Choice(title="Play Locally (IINA)", value="PLAY"),
            questionary.Choice(title="Export to Jellyfin (.strm)", value="EXPORT"),
            questionary.Choice(title="[Back]", value="BACK")
        ]
    ).ask()

def ask_server_ip() -> str:
    return questionary.text(
        "Enter the local IP address of your TrueNAS server (e.g., 192.168.1.50):",
        default="127.0.0.1"
    ).ask()
