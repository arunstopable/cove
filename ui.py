"""Cove UI components — Rich panels + Questionary interactive selectors."""

from contextlib import contextmanager
from typing import Any, Generator, Union

import questionary
from prompt_toolkit.formatted_text import FormattedText
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn

console = Console()


# ──────────────────────────────────────────────────────────────────────────────
# Header
# ──────────────────────────────────────────────────────────────────────────────

def print_header() -> None:
    console.print(
        Panel.fit(
            "[bold cyan]🌊  COVE[/bold cyan]  [dim]v3.0[/dim]\n"
            "[dim]Your personal streaming interface[/dim]",
            border_style="cyan",
            padding=(0, 2),
        )
    )


# ──────────────────────────────────────────────────────────────────────────────
# Spinner
# ──────────────────────────────────────────────────────────────────────────────

@contextmanager
def spinner(message: str) -> Generator[None, None, None]:
    """
    Transient spinner context manager.

    Usage::

        with spinner("Fetching…"):
            result = do_something()
    """
    with Progress(
        SpinnerColumn(spinner_name="dots", style="cyan"),
        TextColumn(f"[cyan]{message}[/cyan]"),
        transient=True,
        console=console,
    ) as progress:
        progress.add_task("", total=None)
        yield


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _back() -> questionary.Choice:
    return questionary.Choice(title="↩  Back", value="BACK")


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
# Selectors
# ──────────────────────────────────────────────────────────────────────────────

def select_sc_search_result(
    results: list[dict[str, Any]],
) -> Union[dict[str, Any], str, None]:
    """Display search results with type and year labels."""
    choices: list[questionary.Choice] = []

    for r in results:
        name: str = r.get("name", "Unknown")
        is_tv = r.get("type") == "tv"
        kind = "Serie TV" if is_tv else "Film"
        year = _year(r)
        color = "class:ansigreen" if is_tv else "class:ansicyan"
        suffix = f"  [{kind}{', ' + year if year else ''}]"

        label = FormattedText(
            [
                (color, "● "),
                ("", name),
                ("class:ansidarkgray", suffix),
            ]
        )
        choices.append(questionary.Choice(title=label, value=r))

    choices.append(_back())
    return questionary.select("Select a title:", choices=choices).ask()


def select_season(
    seasons: list[dict[str, Any]],
) -> Union[dict[str, Any], str, None]:
    choices: list[questionary.Choice] = []

    for s in seasons:
        num = s.get("number", "?")
        eps = s.get("episodes_count", 0)
        label = f"Season {num}  ({eps} episode{'s' if eps != 1 else ''})"
        choices.append(questionary.Choice(title=label, value=s))

    choices.append(_back())
    return questionary.select("Select a season:", choices=choices).ask()


def select_episode(
    episodes: list[dict[str, Any]],
) -> Union[dict[str, Any], str, None]:
    choices: list[questionary.Choice] = []

    for ep in episodes:
        num: int = ep.get("number", 0)
        title: str = ep.get("name", "Untitled")
        air_date: str = (ep.get("air_date") or "")[:10]  # YYYY-MM-DD
        date_str = f"  [{air_date}]" if air_date else ""
        label = f"Ep {num:02d}:  {title}{date_str}"
        choices.append(questionary.Choice(title=label, value=ep))

    choices.append(_back())
    return questionary.select("Select an episode:", choices=choices).ask()


def select_action() -> str:
    return questionary.select(
        "What do you want to do?",
        choices=[
            questionary.Choice(title="▶   Play locally", value="PLAY"),
            questionary.Choice(title="📁  Export to Jellyfin (.strm)", value="EXPORT"),
            questionary.Choice(title="↩   Back", value="BACK"),
        ],
    ).ask()
