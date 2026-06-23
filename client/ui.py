"""Cove UI components — Minimalist, Apple-inspired CLI interface."""

import os
from contextlib import contextmanager
from typing import Any, Generator, Union

import questionary
from prompt_toolkit.formatted_text import FormattedText
from rich.console import Console
from rich.panel import Panel
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn

console = Console()

SERVER_ONLINE = False
NFS_ONLINE = False
MAX_QUALITY = "Unknown"

# ──────────────────────────────────────────────────────────────────────────────
# Styling Theme
# ──────────────────────────────────────────────────────────────────────────────

APPLE_BLUE = "#0A84FF"
CRISP_WHITE = "#FFFFFF"
DIM_GRAY = "#8E8E93"
SOFT_RED = "#FF453A"
SOFT_GREEN = "#32D74B"
BORDER_GRAY = "#333333"
WARM_YELLOW = "#FFD60A"
RICH_PURPLE = "#BF5AF2"
CYAN = "#64D2FF"

cove_style = questionary.Style(
    [
        ("qmark", f"fg:{CYAN} bold"),
        ("question", f"fg:{CRISP_WHITE} bold"),
        ("answer", f"fg:{APPLE_BLUE} bold"),
        ("pointer", f"fg:{RICH_PURPLE} bold"),
        ("highlighted", f"fg:{APPLE_BLUE} bold bg:#1C1C1E"),
        ("selected", f"fg:{SOFT_GREEN} bold"),
        ("separator", f"fg:{DIM_GRAY}"),
        ("instruction", f"fg:{WARM_YELLOW} italic"),
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
    logo = """[bold white]
   ██████╗ ██████╗ ██╗   ██╗███████╗
  ██╔════╝██╔═══██╗██║   ██║██╔════╝
  ██║     ██║   ██║██║   ██║█████╗  
  ██║     ██║   ██║╚██╗ ██╔╝██╔══╝  
  ╚██████╗╚██████╔╝ ╚████╔╝ ███████╗
   ╚═════╝ ╚═════╝   ╚═══╝  ╚══════╝
[/]"""
    status_proxy = (
        f"[bold green]● Proxy Online[/]"
        if SERVER_ONLINE
        else f"[bold red]○ Proxy Offline[/]"
    )
    status_nfs = (
        f"[bold green]● NFS Connected[/]"
        if NFS_ONLINE
        else f"[bold red]○ NFS Disconnected[/]"
    )

    if MAX_QUALITY == "1080p":
        status_q = f"[bold {SOFT_GREEN}]★ VIP (1080p)[/]"
    elif MAX_QUALITY == "720p":
        status_q = f"[bold {CRISP_WHITE}]○ Free (720p)[/]"
    else:
        status_q = f"[dim]○ Q: ?[/]"

    console.print(
        Panel(
            logo.strip() + f"\n\n  {status_proxy}  |  {status_nfs}  |  {status_q}",
            border_style=BORDER_GRAY,
            expand=False,
        )
    )
    console.print()


def show_error(msg: str) -> None:
    console.print(f"[bold {SOFT_RED}]x[/] [{SOFT_RED}]{msg}[/]")


def show_success(msg: str) -> None:
    console.print(f"[bold {SOFT_GREEN}]✓[/] [{SOFT_GREEN}]{msg}[/]")


def show_info(msg: str) -> None:
    console.print(f"[bold {APPLE_BLUE}]i[/] [{CRISP_WHITE}]{msg}[/]")


@contextmanager
def spinner(message: str) -> Generator[None, None, None]:
    """Transient spinner context manager for background operations."""
    with Progress(
        SpinnerColumn(spinner_name="dots", style=APPLE_BLUE),
        TextColumn(f"[{CRISP_WHITE}]{message}[/]"),
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
    """Extract a 4-digit year string from a title dict, or empty string."""
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
    return questionary.text("Search title:", style=cove_style, qmark=">").ask()


def select_main_menu() -> str:
    choices = [
        questionary.Choice(title=FormattedText([("class:ansicyan", "  Search Titles")]), value="SEARCH"),
    ]
    if NFS_ONLINE:
        choices.append(questionary.Choice(title=FormattedText([("class:ansiblue", "  My Library")]), value="LIBRARY"))

    if SERVER_ONLINE:
        choices.append(
            questionary.Choice(title=FormattedText([("class:ansiyellow", "  Active Downloads")]), value="STATUS")
        )

    choices.append(questionary.Choice(title=FormattedText([("class:ansidarkgray", "  Exit")]), value="EXIT"))

    return questionary.select(
        "Main Menu:",
        choices=choices,
        style=cove_style,
        qmark="",
        pointer="❯",
    ).ask()


def select_library_item(
    items: list[dict[str, Any]],
) -> Union[dict[str, Any], str, None]:
    choices: list[questionary.Choice] = []

    for item in items:
        name = item.get("name", "Unknown")
        kind = "TV" if item.get("type") == "tv" else "Movie"
        color = "class:ansicyan" if kind == "TV" else "class:ansiblue"

        label = FormattedText(
            [
                (color, "■ "),
                ("", f"{name} "),
                ("class:ansidarkgray", f"[{kind}]"),
            ]
        )
        choices.append(questionary.Choice(title=label, value=item))

    choices.append(_back())
    return questionary.select(
        "Select from Library:",
        choices=choices,
        style=cove_style,
        qmark="",
        pointer="❯",
    ).ask()


def select_sc_search_result(
    results: list[dict[str, Any]],
) -> Union[dict[str, Any], str, None]:
    """Display search results with type and year labels."""
    choices: list[questionary.Choice] = []

    for r in results:
        name: str = r.get("name", "Unknown")
        is_tv = r.get("type") == "tv"
        kind = "TV" if is_tv else "Movie"
        year = _year(r)
        color = "class:ansicyan" if is_tv else "class:ansiblue"
        suffix = f" [{kind}{', ' + year if year else ''}]"

        label = FormattedText(
            [
                (color, "■ "),
                ("", f"{name} "),
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


def select_movie_action(has_mkv: bool) -> str:
    choices = []
    play_label = "  Play (Downloaded)" if has_mkv else "  Play (Stream)"
    choices.append(questionary.Choice(title=FormattedText([("class:ansigreen" if has_mkv else "class:ansicyan", play_label)]), value="PLAY"))
    
    if SERVER_ONLINE and not has_mkv:
        choices.append(questionary.Choice(title="  Download Offline", value="DOWNLOAD"))
    if SERVER_ONLINE:
        choices.append(questionary.Choice(title="  Manage...", value="MANAGE"))
        
    choices.append(_back())
    return questionary.select("Action:", choices=choices, style=cove_style, qmark="", pointer="❯").ask()

def select_tv_action() -> str:
    choices = [
        questionary.Choice(title=FormattedText([("class:ansicyan", "  Browse Episodes")]), value="BROWSE"),
    ]
    if SERVER_ONLINE:
        choices.extend([
            questionary.Choice(title="  Batch Download", value="BATCH_DOWNLOAD"),
            questionary.Choice(title="  Manage...", value="MANAGE"),
        ])
    choices.append(_back())
    return questionary.select("Action:", choices=choices, style=cove_style, qmark="", pointer="❯").ask()

def select_episode_action(is_downloaded: bool) -> str:
    choices = []
    play_label = "  Play (Downloaded)" if is_downloaded else "  Play (Stream)"
    choices.append(questionary.Choice(title=FormattedText([("class:ansigreen" if is_downloaded else "class:ansicyan", play_label)]), value="PLAY"))
    
    if SERVER_ONLINE and not is_downloaded:
        choices.append(questionary.Choice(title="  Download", value="DOWNLOAD"))
        
    choices.append(_back())
    return questionary.select("Action:", choices=choices, style=cove_style, qmark="", pointer="❯").ask()

def select_manage_action() -> str:
    choices = [
        questionary.Choice(title="  Export to Jellyfin (.strm)", value="EXPORT"),
        questionary.Choice(title="  Cleanup Physical Files", value="CLEANUP"),
        _back()
    ]
    return questionary.select("Manage:", choices=choices, style=cove_style, qmark="", pointer="❯").ask()


def select_season(seasons: list[dict[str, Any]]) -> Union[dict[str, Any], str, None]:
    choices: list[questionary.Choice] = []

    for s in seasons:
        num = s.get("number", "?")
        eps = s.get("episodes_count", 0)
        label = f"  Season {num} ({eps} eps)"
        choices.append(questionary.Choice(title=label, value=s))

    choices.append(_back())
    return questionary.select(
        "Select Season:",
        choices=choices,
        style=cove_style,
        qmark="",
        pointer="❯",
    ).ask()


def select_episode(
    episodes: list[dict[str, Any]],
    downloaded_ids: set[int] = None,
    default: dict[str, Any] = None,
) -> Union[dict[str, Any], str, None]:
    choices: list[questionary.Choice] = []
    if downloaded_ids is None:
        downloaded_ids = set()

    default_choice = None

    for ep in episodes:
        num: int = ep.get("number", 0)
        ep_id: int = ep.get("id", 0)
        title: str = ep.get("name", "Untitled")

        if ep_id in downloaded_ids:
            # Green checkmark for physically downloaded MKV files
            prefix = [("class:ansigreen", "✓ ")]
        else:
            # Gray dot for streaming available
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
    if downloaded_ids is None:
        downloaded_ids = set()
    if downloading_ids is None:
        downloading_ids = set()

    for ep in episodes:
        num: int = ep.get("number", 0)
        ep_id: int = ep.get("id", 0)
        title: str = ep.get("name", "Untitled")

        if ep_id in downloaded_ids:
            # Already downloaded
            label = FormattedText(
                [
                    ("class:ansigreen", f"Ep {num:02d}: {title} (Downloaded)"),
                ]
            )
            choices.append(
                questionary.Choice(title=label, value=ep, disabled="Already downloaded")
            )
        elif ep_id in downloading_ids:
            # Downloading
            label = FormattedText(
                [
                    ("class:ansiyellow", f"Ep {num:02d}: {title} (Downloading...)"),
                ]
            )
            choices.append(
                questionary.Choice(title=label, value=ep, disabled="Currently downloading")
            )
        else:
            label = FormattedText(
                [
                    ("", f"Ep {num:02d}: "),
                    ("class:ansidarkgray", title),
                ]
            )
            choices.append(questionary.Choice(title=label, value=ep))

    if not choices or all(c.disabled for c in choices):
        return []

    return questionary.checkbox(
        "Select episodes to download (Space to select, Enter to confirm):",
        choices=choices,
        style=cove_style,
        qmark="",
        pointer="❯",
    ).ask()
