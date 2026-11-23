from nih_grant_matcher.models import Opportunity
from nih_grant_matcher.rules import GRANT_TYPES
from nih_grant_matcher.scoring import MLRelevanceScorer
from nih_grant_matcher.store import OpportunityStore
from nih_grant_matcher.writer import Workspace

R21 = GRANT_TYPES["NIH:R21"]
RULE = {section.key: section for section in R21.sections}

class Guide:
    def __init__(self, text: str, ggid: str = "360675") -> None: self.text, self.ggid, self.asked = text, ggid, []
    def doctext(self, docnum: str) -> tuple[str, str]:
        self.asked.append(docnum)
        return self.text, self.ggid

class Grants:
    def __init__(self, html: str) -> None: self.html, self.asked = html, []
    def full_announcement(self, opportunity_id: str) -> str:
        self.asked.append(opportunity_id)
        return self.html

def opportunity(number: str = "PAR-1", instruments: tuple[str, ...] = ("R21",)) -> Opportunity:
    return Opportunity(f"nih-guide:{number}", number, "Heart cells in failure", "NHLBI", "NIH NHLBI", "active", description="Heart cells.", funding_instruments=instruments)

def start(tmp_path, model=None, resubmission=False, facts=None, others=0, profile=None) -> Workspace:
    store = OpportunityStore(tmp_path / "g.sqlite3")
    if profile is not None:
        store.save_profile(profile)
    saved = opportunity()
    store.upsert_scored(MLRelevanceScorer().score(saved))
    for n in range(others):
        store.add_application(opportunity_number=f"PAR-{n + 2}", grant_type="NIH:R21", title="Other")
    ws = Workspace.start(store, saved, "NIH:R21", resubmission, model)
    for kind, text in (facts or {}).items():
        ws.add_fact(kind, text)
    return ws
