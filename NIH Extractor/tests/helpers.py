class Guide:
    def __init__(self, text: str) -> None: self.text = text
    def doctext(self, docnum: str) -> tuple[str, str]: return self.text, "360675"

class Grants:
    def __init__(self, html: str) -> None: self.html = html
    def full_announcement(self, opportunity_id: str) -> str: return self.html
