import http.client, io, json, re, subprocess, urllib.error, urllib.parse
from pathlib import Path
from types import SimpleNamespace
from nih_grant_matcher.clients import ApiError
from nih_grant_matcher.llm import PROVIDERS, HttpModel, ModelError
from nih_grant_matcher.models import Completion, Opportunity
from nih_grant_matcher.rules import GRANT_TYPES
from nih_grant_matcher.scoring import MLRelevanceScorer
from nih_grant_matcher.store import OpportunityStore
from nih_grant_matcher.writer import Workspace

R21 = GRANT_TYPES["NIH:R21"]
RULE = {section.key: section for section in R21.sections}

class Guide:
    # With no page, the notice's page answers as the Guide does for a notice from fiscal 2026 on, with a 404.
    def __init__(self, text: str, ggid: str = "360675", page: str | None = None) -> None: self.text, self.ggid, self.html, self.asked, self.pages = text, ggid, page, [], []
    def doctext(self, docnum: str) -> tuple[str, str]:
        self.asked.append(docnum)
        return self.text, self.ggid
    def page(self, docnum: str) -> str:
        self.pages.append(docnum)
        if self.html is None:
            raise ApiError("HTTP Error 404: Not Found")
        return self.html

def no_page(self, docnum: str) -> str:
    raise ApiError("HTTP Error 404: Not Found")

class Grants:
    def __init__(self, html: str) -> None: self.html, self.asked = html, []
    def full_announcement(self, opportunity_id: str) -> str:
        self.asked.append(opportunity_id)
        return self.html

def opportunity(number: str = "PAR-1", instruments: tuple[str, ...] = ("R21",)) -> Opportunity:
    return Opportunity(f"nih-guide:{number}", number, "Heart cells in failure", "NHLBI", "NIH NHLBI", "active", description="Heart cells.", funding_instruments=instruments)

def start(tmp_path, model=None, resubmission=False, facts=None, others=0, profile=None, consent=True) -> Workspace:
    store = OpportunityStore(tmp_path / "g.sqlite3")
    if consent:
        store.set_setting("consent:example.test", "2026-11-23T00:00:00")
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

OVER_LIMIT = {"keywords": {"mitochondria": 18}, "examples": ["Study mitochondrial dynamics in cardiac muscle."], "focus": "profile", "examples_name": "your example sentences", "investigator": "Ada Lovelace", "resources": "r" * 7200}

def save_like_main(path, **profile) -> None:
    # Version 0.2.0 checked no length, so its wizard and import saved text this branch's limits refuse.
    store = OpportunityStore(path)
    try:
        store.conn.execute("INSERT INTO profile VALUES (1, ?, '2026-11-01T00:00:00')", (json.dumps({"format": "grant-matcher-profile/1", "profile": {**OVER_LIMIT, **profile}}),))
        store.conn.commit()
    finally:
        store.close()

LLM_FIXTURES = Path(__file__).parent / "fixtures" / "llm"

def fixture(name: str) -> dict:
    data = json.loads((LLM_FIXTURES / f"{name}.json").read_text(encoding="utf-8"))
    data.pop("_source")
    return data

def model(name: str, key: str | None = "k", base_url: str = "") -> HttpModel:
    return HttpModel(PROVIDERS[name], PROVIDERS[name].default_model or "m", base_url or PROVIDERS[name].base_url, key)

def model_for(wire: str) -> HttpModel:
    return model(next(p.name for p in PROVIDERS.values() if p.wire == wire))

def strict_open(request, timeout=None):
    # Runs http.client's own header check, which refuses a line break, and connects to nothing.
    conn = http.client.HTTPConnection(urllib.parse.urlsplit(request.full_url).hostname)
    conn.putrequest(request.get_method(), request.selector)
    for name, value in request.header_items():
        conn.putheader(name, value)
    raise AssertionError("http.client accepted every header, so no request was refused")

def error_with_unreadable_body(broken: BaseException, status: int = 502):
    # The connection drops while the error page arrives.
    class Body(io.BytesIO):
        def read(self, *args): raise broken
    def failed(url: str):
        raise urllib.error.HTTPError(url, status, "Bad Gateway", {}, Body())
    return failed

class FakeModel:
    provider, name, host = "fake", "fake-1", "example.test"
    def __init__(self, *replies: str | ModelError, truncated: bool = False, error: ModelError | None = None) -> None:
        self.replies, self.truncated, self.error, self.seen = list(replies), truncated, error, []
    def complete(self, system: str, user: str, max_tokens: int = 16000) -> Completion:
        self.seen.append(SimpleNamespace(system=system, user=user))
        if self.error is not None:
            raise self.error
        if isinstance(reply := self.replies.pop(0), ModelError):
            raise reply
        return Completion(reply, self.name, len((system + user).split()), 1, self.truncated)

class FakeSecurity:
    def __init__(self) -> None: self.items, self.argv, self.stdin, self.exit_with = {}, [], [], None
    def __call__(self, argv: list[str], input: str | None = None, **kwargs) -> subprocess.CompletedProcess:
        self.argv.append(list(argv))
        self.stdin.append(input or "")
        def done(code: int, out: str = "") -> subprocess.CompletedProcess: return subprocess.CompletedProcess(argv, code, out, "")
        if self.exit_with is not None:
            return done(self.exit_with)
        if argv[1:] == ["-i"]:
            line = re.fullmatch(r'add-generic-password -U -a "([^"]*)" -s "([^"]*)" -X ([0-9a-f]+)\n', input or "")
            if line is None:
                return done(1)
            self.items[(line[2], line[1])] = bytes.fromhex(line[3]).decode()
            return done(0)
        item = (argv[argv.index("-s") + 1], argv[argv.index("-a") + 1])
        if argv[1] == "find-generic-password":
            return done(0, self.items[item] + "\n") if item in self.items else done(44)
        return done(0 if self.items.pop(item, None) is not None else 44)
