import re

def escape_markdown(text: str) -> str:
    # Captions and alerts render as Markdown, and profile text comes from the user or from a pasted file.
    return re.sub(r"([!-/:-@\[-`{-~])", r"\\\1", text)
