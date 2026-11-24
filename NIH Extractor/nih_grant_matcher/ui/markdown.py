import re

def escape_markdown(text: str) -> str:
    # Captions and alerts render as Markdown, so text the page did not write could otherwise add a link, an image or formatting.
    return re.sub(r"([!-/:-@\[-`{-~])", r"\\\1", text)
