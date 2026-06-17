"""Cove UI components — Minimalist, Apple-inspired CLI interface."""

import os
from contextlib import contextmanager
from typing import Any, Generator, Union

import questionary
from prompt_toolkit.formatted_text import FormattedText
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.text import Text

console = Console()

# ──────────────────────────────────────────────────────────────────────────────
# Styling Theme
# ──────────────────────────────────────────────────────────────────────────────

APPLE_BLUE = "#007AFF"
CRISP_WHITE = "#FFFFFF"
DIM_GRAY = "#8E8E93"
SOFT_RED = "#FF3B30"
SOFT_GREEN = "#34C759"
BORDER_GRAY = "#333333"

cove_style = questionary.Style([
    ("qmark", f"fg:{APPLE_BLUE} bold"),
    ("question", f"fg:{CRISP_WHITE} bold"),
    ("answer", f"fg:{APPLE_BLUE} bold"),
    ("pointer", f"fg:{APPLE_BLUE} bold"),
    ("highlighted", f"fg:{APPLE_BLUE} bold"),
    ("selected", f"fg:{SOFT_GREEN} bold"),
    ("separator", f"fg:{DIM_GRAY}"),
    ("instruction", f"fg:{DIM_GRAY} italic"),
    ("text", f"fg:#CCCCCC"),
])


# ──────────────────────────────────────────────────────────────────────────────
# Core Engine
# ──────────────────────────────────────────────────────────────────────────────

def clear_screen() -> None:
    """Clear the terminal screen completely."""
    os.system("cls" if os.name == "nt" else "clear")


def print_header() -> None:
    """Print the minimalist Cove logo centered on the screen."""
    console.print(
        Panel.fit(
            f"[bold {APPLE_BLUE}]C O V E[/]\n"
            f"[dim {DIM_GRAY}]Streaming Environment[/]",
            border_style=BORDER_GRAY,
            padding=(1, 4),
        ),
        justify="center"
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
    return questionary.Choice(title=FormattedText([("class:ansidarkgray", "< Back")]), value="BACK")


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
    return questionary.text(
        "Search title:",
        style=cove_style,
        qmark=">"
    ).ask()


def select_main_menu() -> str:
    return questionary.select(
        "Main Menu:",
        choices=[
            questionary.Choice(title="  Search New Title", value="SEARCH"),
            questionary.Choice(title="  My Library", value="LIBRARY"),
            questionary.Choice(title="  View Download Status", value="STATUS"),
            questionary.Choice(title="  Exit", value="EXIT"),
        ],
        style=cove_style,
        qmark="",
        pointer="❯",
    ).ask()


def select_library_item(items: list[dict[str, Any]]) -> Union[dict[str, Any], str, None]:
    choices: list[questionary.Choice] = []
    
    for item in items:
        name = item.get("name", "Unknown")
        kind = "TV" if item.get("type") == "tv" else "Movie"
        color = "class:ansicyan" if kind == "TV" else "class:ansiblue"
        
        label = FormattedText([
            (color, "■ "),
            ("", f"{name} "),
            ("class:ansidarkgray", f"[{kind}]"),
        ])
        choices.append(questionary.Choice(title=label, value=item))

    choices.append(_back())
    return questionary.select(
        "Select from Library:",
        choices=choices,
        style=cove_style,
        qmark="",
        pointer="❯",
    ).ask()


def select_sc_search_result(results: list[dict[str, Any]]) -> Union[dict[str, Any], str, None]:
    """Display search results with type and year labels."""
    choices: list[questionary.Choice] = []

    for r in results:
        name: str = r.get("name", "Unknown")
        is_tv = r.get("type") == "tv"
        kind = "TV" if is_tv else "Movie"
        year = _year(r)
        color = "class:ansicyan" if is_tv else "class:ansiblue"
        suffix = f" [{kind}{', ' + year if year else ''}]"

        label = FormattedText([
            (color, "■ "),
            ("", f"{name} "),
            ("class:ansidarkgray", suffix),
        ])
        choices.append(questionary.Choice(title=label, value=r))

    choices.append(_back())
    return questionary.select(
        "Search Results:",
        choices=choices,
        style=cove_style,
        qmark="",
        pointer="❯",
    ).ask()


def select_action() -> str:
    return questionary.select(
        "Action:",
        choices=[
            questionary.Choice(title="  Play Locally", value="PLAY"),
            questionary.Choice(title="  Export to Jellyfin (.strm)", value="EXPORT"),
            questionary.Choice(title="  Download Offline (.mkv)", value="DOWNLOAD"),
            questionary.Choice(title="  Delete Downloaded Files", value="CLEANUP"),
            _back(),
        ],
        style=cove_style,
        qmark="",
        pointer="❯",
    ).ask()


def select_scope(show_name: str, seasons: list[dict[str, Any]]) -> Union[str, dict[str, Any], None]:
    choices: list[questionary.Choice] = [
        questionary.Choice(title=f"  All Seasons ({show_name})", value="ALL")
    ]
    
    for s in seasons:
        num = s.get("number", "?")
        eps = s.get("episodes_count", 0)
        label = f"  Season {num} ({eps} eps)"
        choices.append(questionary.Choice(title=label, value=s))

    choices.append(_back())
    return questionary.select(
        "Select Scope:",
        choices=choices,
        style=cove_style,
        qmark="",
        pointer="❯",
    ).ask()


def select_episode(
    episodes: list[dict[str, Any]], 
    downloaded_ids: set[int] = None
) -> Union[dict[str, Any], str, None]:
    choices: list[questionary.Choice] = []
    if downloaded_ids is None:
        downloaded_ids = set()

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
            
        label = FormattedText(prefix + [
            ("", f"Ep {num:02d}: "),
            ("class:ansidarkgray", title),
        ])
        choices.append(questionary.Choice(title=label, value=ep))

    choices.append(_back())
    return questionary.select(
        "Select Episode:",
        choices=choices,
        style=cove_style,
        qmark="",
        pointer="❯",
    ).ask()


def select_episodes_multi(
    episodes: list[dict[str, Any]], 
    downloaded_ids: set[int] = None
) -> list[dict[str, Any]]:
    """Multi-select checkbox for downloading specific episodes."""
    choices: list[questionary.Choice] = []
    if downloaded_ids is None:
        downloaded_ids = set()

    for ep in episodes:
        num: int = ep.get("number", 0)
        ep_id: int = ep.get("id", 0)
        title: str = ep.get("name", "Untitled")
        
        if ep_id in downloaded_ids:
            # Already downloaded
            label = FormattedText([
                ("class:ansigreen", f"Ep {num:02d}: {title} (Downloaded)"),
            ])
            choices.append(questionary.Choice(title=label, value=ep, disabled="Already downloaded"))
        else:
            label = FormattedText([
                ("", f"Ep {num:02d}: "),
                ("class:ansidarkgray", title),
            ])
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
