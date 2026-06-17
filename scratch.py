import questionary
from prompt_toolkit.formatted_text import FormattedText

choices = [
    questionary.Choice(
        title=FormattedText([("class:ansigreen", "• "), ("", "Show 1")]),
        value=1
    ),
    questionary.Choice(
        title=FormattedText([("class:ansiblue", "• "), ("", "Movie 1")]),
        value=2
    )
]

try:
    print("Testing select prompt")
    q = questionary.select("Pick one:", choices=choices)
    print("Initialization OK")
except Exception as e:
    print(f"Error: {e}")
