"""Cove UI components — Minimalist, Apple-inspired CLI interface."""

import os
from contextlib import contextmanager
from typing import Any, Generator, Union, List, Set, Optional

import questionary
from prompt_toolkit.formatted_text import FormattedText
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn

console = Console()

SERVER_ONLINE = False
NFS_ONLINE = False
MAX_QUALITY = "Unknown"
ACTIVE_DOWNLOADS_COUNT = 0

# ──────────────────────────────────────────────────────────────────────────────
# Styling Theme
# ──────────────────────────────────────────────────────────────────────────────

APPLE_BLUE = "#0A84FF"
CRISP_WHITE = "#FFFFFF"
DIM_GRAY = "#8E8E93"
SOFT_RED = "#FF453A"
BORDER_GRAY = "#333333"

cove_style = questionary.Style(
    [
        ("qmark", f"fg:{DIM_GRAY} bold"),
        ("question", f"fg:{CRISP_WHITE} bold"),
        ("answer", f"fg:{APPLE_BLUE} bold"),
        ("pointer", f"fg:{APPLE_BLUE} bold"),
        ("highlighted", f"fg:{APPLE_BLUE} bold bg:#1C1C1E"),
        ("selected", f"fg:{CRISP_WHITE} bold"),
        ("separator", f"fg:{DIM_GRAY}"),
        ("instruction", f"fg:{DIM_GRAY} italic"),
        ("text", f"fg:#E5E5EA"),
        ("disabled", f"fg:{DIM_GRAY} italic"),
    ]
)

# ──────────────────────────────────────────────────────────────────────────────
# Core Engine
# ──────────────────────────────────────────────────────────────────────────────

def clear_screen() -> None:
    """Clear the terminal screen completely."""
    os.system("cls" if os.name == "nt" else "clear")

def print_header() -> None:
    status_proxy = (
        f"[bold {APPLE_BLUE}]Proxy Online[/]"
        if SERVER_ONLINE
        else f"[bold {DIM_GRAY}]Proxy Offline[/]"
    )
    status_nfs = (
        f"[bold {APPLE_BLUE}]NFS Connected[/]"
        if NFS_ONLINE
        else f"[bold {DIM_GRAY}]NFS Disconnected[/]"
    )

    if MAX_QUALITY == "1080p":
        status_q = f"[bold {CRISP_WHITE}]★ 1080p[/]"
    elif MAX_QUALITY == "720p":
        status_q = f"[bold {DIM_GRAY}]○ 720p[/]"
    else:
        status_q = f"[bold {DIM_GRAY}]○ Unknown Q[/]"

    dl_text = f"  |  [bold {CRISP_WHITE}]↓ {ACTIVE_DOWNLOADS_COUNT} downloading[/]" if ACTIVE_DOWNLOADS_COUNT > 0 else ""

    header_text = f"[bold {CRISP_WHITE}]COVE[/]  ·  {status_proxy}  |  {status_nfs}  |  {status_q}{dl_text}"

    console.print(
        Panel(
            header_text,
            border_style=BORDER_GRAY,
            expand=False,
            padding=(0, 1)
        )
    )
    console.print()

def show_error(msg: str) -> None:
    console.print(f"[bold {SOFT_RED}]![/] [{CRISP_WHITE}]{msg}[/]")

def show_success(msg: str) -> None:
    console.print(f"[bold {APPLE_BLUE}]✓[/] [{CRISP_WHITE}]{msg}[/]")

def show_info(msg: str) -> None:
    console.print(f"[bold {DIM_GRAY}]i[/] [{CRISP_WHITE}]{msg}[/]")

@contextmanager
def spinner(message: str) -> Generator[None, None, None]:
    """Transient spinner context manager for background operations."""
    with Progress(
        SpinnerColumn(spinner_name="dots", style=APPLE_BLUE),
        TextColumn(f"[{DIM_GRAY}]{message}[/]"),
        transient=True,
        console=console,
    ) as progress:
        progress.add_task("", total=None)
        yield

# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _back() -> questionary.Choice:
    return questionary.Choice(
        title=FormattedText([("class:ansidarkgray", "< Back")]), value="BACK"
    )

def _year(title: dict[str, Any]) -> str:
    date: str = (
        title.get("release_date")
        or title.get("first_air_date")
        or title.get("year", "")
        or ""
    )
    return str(date)[:4] if len(str(date)) >= 4 else ""

# ──────────────────────────────────────────────────────────────────────────────
# Prompts & Selectors
# ──────────────────────────────────────────────────────────────────────────────

def ask_search_query() -> str:
    return questionary.text("Search title:", style=cove_style, qmark="").ask()

def select_main_menu() -> str:
    choices = [
        questionary.Choice(title=FormattedText([("", "Search Titles")]), value="SEARCH"),
    ]
    if NFS_ONLINE:
        choices.append(questionary.Choice(title=FormattedText([("", "My Library")]), value="LIBRARY"))

    if SERVER_ONLINE:
        choices.append(
            questionary.Choice(title=FormattedText([("", "Active Downloads")]), value="STATUS")
        )

    choices.append(questionary.Choice(title=FormattedText([("class:ansidarkgray", "Exit")]), value="EXIT"))

    return questionary.select(
        "Main Menu:",
        choices=choices,
        style=cove_style,
        qmark="",
        pointer="❯",
    ).ask()

def select_library_item(items: list[dict[str, Any]]) -> Union[dict[str, Any], str, None]:
    choices: list[questionary.Choice] = []

    for item in items:
        name = item.get("name", "Unknown")
        kind = "TV" if item.get("type") == "tv" else "Movie"
        color = "class:ansiwhite"

        label = FormattedText(
            [
                (color, f"{name} "),
                ("class:ansidarkgray", f"[{kind}]"),
            ]
        )
        choices.append(questionary.Choice(title=label, value=item))

    choices.append(_back())
    return questionary.select(
        "Library:",
        choices=choices,
        style=cove_style,
        qmark="",
        pointer="❯",
    ).ask()

def select_sc_search_result(results: list[dict[str, Any]]) -> Union[dict[str, Any], str, None]:
    choices: list[questionary.Choice] = []

    for r in results:
        name: str = r.get("name", "Unknown")
        is_tv = r.get("type") == "tv"
        kind = "TV" if is_tv else "Movie"
        year = _year(r)
        suffix = f" [{kind}{', ' + year if year else ''}]"

        label = FormattedText(
            [
                ("class:ansiwhite", f"{name} "),
                ("class:ansidarkgray", suffix),
            ]
        )
        choices.append(questionary.Choice(title=label, value=r))

    choices.append(_back())
    return questionary.select(
        "Search Results:",
        choices=choices,
        style=cove_style,
        qmark="",
        pointer="❯",
    ).ask()

def confirm(msg: str) -> bool:
    return questionary.confirm(msg, style=cove_style, qmark="").ask()

# ──────────────────────────────────────────────────────────────────────────────
# Title Card & Specific Menus
# ──────────────────────────────────────────────────────────────────────────────

def select_title_action(sc_title: dict[str, Any], has_mkv: bool, has_strm: bool) -> str:
    """Unified title card action menu for both Movies and TV Shows."""
    name = sc_title.get("name", "Unknown")
    is_tv = sc_title.get("type") == "tv"
    kind = "TV" if is_tv else "Movie"
    
    # Check seasons logic
    # In search results, seasons count might not be there. It's fine to omit it if 0.
    seasons_count = sc_title.get("seasons_count", 0) 
    if seasons_count == 0 and "seasons" in sc_title:
        seasons_count = len(sc_title["seasons"])
    
    # Render Context Header
    console.print(f"╭─ [bold {CRISP_WHITE}]{name}[/] · {kind} ─{'─'*40}")
    status_line = []
    
    if is_tv and seasons_count > 0:
        status_line.append(f"{seasons_count} seasons")
        
    if has_mkv:
        status_line.append(f"[bold {APPLE_BLUE}]Downloaded[/]")
    elif has_strm:
        status_line.append(f"[bold {CRISP_WHITE}]In Library (.strm)[/]")
    else:
        status_line.append(f"[bold {DIM_GRAY}]Not in library[/]")
        
    console.print(f"│  {' · '.join(status_line)}")
    console.print(f"╰{'─'*60}")
    console.print()

    choices = []
    
    if is_tv:
        choices.append(questionary.Choice(title="Browse Episodes", value="BROWSE"))
        if SERVER_ONLINE:
            choices.append(questionary.Choice(title="Download Season...", value="DOWNLOAD_SEASON"))
    else:
        play_label = "Play (Local)" if has_mkv else "Play (Stream)"
        choices.append(questionary.Choice(title=play_label, value="PLAY"))
        if SERVER_ONLINE and not has_mkv:
            choices.append(questionary.Choice(title="Download Offline", value="DOWNLOAD"))

    # Library Management
    if not has_strm and not has_mkv:
        choices.append(questionary.Choice(title="Add to Library (.strm)", value="EXPORT"))
    else:
        if has_mkv:
            choices.append(questionary.Choice(title="Manage Local Files (Delete/Re-export)", value="CLEANUP"))
        else:
            choices.append(questionary.Choice(title="Remove from Library", value="CLEANUP"))
            
    choices.append(_back())
    return questionary.select("Action:", choices=choices, style=cove_style, qmark="", pointer="❯").ask()

def select_season(seasons: list[dict[str, Any]], for_download: bool = False) -> Union[dict[str, Any], str, None]:
    choices: list[questionary.Choice] = []

    if for_download and len(seasons) > 1:
        choices.append(questionary.Choice(title="All Seasons", value="ALL"))

    for s in seasons:
        num = s.get("number", "?")
        eps = s.get("episodes_count", 0)
        label = f"Season {num} ({eps} eps)"
        choices.append(questionary.Choice(title=label, value=s))

    choices.append(_back())
    return questionary.select(
        "Select Season:",
        choices=choices,
        style=cove_style,
        qmark="",
        pointer="❯",
    ).ask()

def select_episode_action(ep_num: int, title: str, is_downloaded: bool) -> str:
    console.print(f"╭─ [bold {CRISP_WHITE}]Ep {ep_num:02d}: {title}[/] ─{'─'*40}")
    status = f"[bold {APPLE_BLUE}]Downloaded[/]" if is_downloaded else f"[bold {DIM_GRAY}]Stream only[/]"
    console.print(f"│  {status}")
    console.print(f"╰{'─'*60}")
    console.print()

    choices = []
    play_label = "Play (Local)" if is_downloaded else "Play (Stream)"
    choices.append(questionary.Choice(title=play_label, value="PLAY"))
    
    if SERVER_ONLINE and not is_downloaded:
        choices.append(questionary.Choice(title="Download Offline", value="DOWNLOAD"))
        
    choices.append(_back())
    return questionary.select("Action:", choices=choices, style=cove_style, qmark="", pointer="❯").ask()

def select_episode(
    episodes: list[dict[str, Any]],
    downloaded_ids: set[int] = None,
    downloading_ids: set[int] = None,
    default: dict[str, Any] = None,
) -> Union[dict[str, Any], str, None]:
    choices: list[questionary.Choice] = []
    if downloaded_ids is None: downloaded_ids = set()
    if downloading_ids is None: downloading_ids = set()

    default_choice = None

    for ep in episodes:
        num: int = ep.get("number", 0)
        ep_id: int = ep.get("id", 0)
        title: str = ep.get("name", "Untitled")

        if ep_id in downloaded_ids:
            prefix = [("class:ansiblue", "✓ ")]
        elif ep_id in downloading_ids:
            prefix = [("class:ansidarkgray", "↓ ")]
        else:
            prefix = [("class:ansidarkgray", "• ")]

        label = FormattedText(
            prefix
            + [
                ("", f"Ep {num:02d}: "),
                ("class:ansidarkgray", title),
            ]
        )
        choice = questionary.Choice(title=label, value=ep)
        choices.append(choice)

        if default and default.get("id") == ep_id:
            default_choice = choice

    choices.append(_back())

    kwargs = {}
    if default_choice:
        kwargs["default"] = default_choice

    return questionary.select(
        "Select Episode:",
        choices=choices,
        style=cove_style,
        qmark="",
        pointer="❯",
        **kwargs,
    ).ask()

def select_episodes_multi(
    episodes: list[dict[str, Any]], downloaded_ids: set[int] = None, downloading_ids: set[int] = None
) -> list[dict[str, Any]]:
    """Multi-select checkbox for downloading specific episodes."""
    choices: list[questionary.Choice] = []
    if downloaded_ids is None: downloaded_ids = set()
    if downloading_ids is None: downloading_ids = set()

    for ep in episodes:
        num: int = ep.get("number", 0)
        ep_id: int = ep.get("id", 0)
        title: str = ep.get("name", "Untitled")

        if ep_id in downloaded_ids:
            label = FormattedText([("class:ansiblue", f"Ep {num:02d}: {title} (Downloaded)")])
            choices.append(questionary.Choice(title=label, value=ep, disabled="Already downloaded"))
        elif ep_id in downloading_ids:
            label = FormattedText([("class:ansidarkgray", f"Ep {num:02d}: {title} (Downloading)")])
            choices.append(questionary.Choice(title=label, value=ep, disabled="Downloading"))
        else:
            label = FormattedText([("", f"Ep {num:02d}: "), ("class:ansidarkgray", title)])
            choices.append(questionary.Choice(title=label, value=ep))

    if not choices or all(c.disabled for c in choices):
        return []

    return questionary.checkbox(
        "Select episodes to download:",
        choices=choices,
        style=cove_style,
        qmark="",
        pointer="❯",
    ).ask()
