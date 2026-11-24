import json, sqlite3
from datetime import date, datetime, timezone
from pathlib import Path
import pytest
from helpers import FakeModel, Grants, Guide, error_with_unreadable_body, model, start
from nih_grant_matcher import __version__
from nih_grant_matcher.clients import ApiError
from nih_grant_matcher.llm import ModelError
from nih_grant_matcher.profile import Profile, Reference
from nih_grant_matcher.writer import NotReady, StaleEdit, Workspace, WorkspaceError, read_summary

FOUR_PAGES = "Section IV. Application and Submission Information\nThe Research Strategy is limited to 4 pages.\nSection V. Review\nx" + " More text." * 100
GRANTS_PAGE = "<p>Section IV. Application and Submission Information</p><p>The Research Strategy is limited to 4 pages, as in (NOT-OD-26-001).</p>" + "<p>Follow the guide.</p>" * 80

class GuideDown:
    def doctext(self, number): raise ApiError("timed out")

class GrantsDown:
    def full_announcement(self, opportunity_id): raise ApiError("HTTP 503")

DROPPED_FOUR = 'Your decision on "Research Strategy: at most 4 pages." was dropped, because the new text no longer has the sentence it came from.'
READ = "Section I. Notice of Funding Opportunity Description\nApplicants must describe data sharing.\nSection IV. Application and Submission Information\nThe Specific Aims must state one hypothesis.\nSection V. Application Review Information\nReviewers will judge rigor." + " More text." * 100
item = lambda kind, section, text, quote: {"kind": kind, "section": section, "text": text, "quote": quote, "limit": None}
READ_I = json.dumps([item("must", "", "Describe data sharing.", "Applicants must describe data sharing.")])
READ_REPLIES = (READ_I, json.dumps([item("must", "specific-aims", "State one hypothesis.", "The Specific Aims must state one hypothesis.")]), json.dumps([item("criterion", "", "Rigor.", "Reviewers will judge rigor."), item("must", "", "Invented.", "Applicants must include a power analysis for every aim.")]))
MUST = "Section IV. Application and Submission Information\nPHS 398 Research Plan\nAll instructions must be followed, with the following additional instructions: Describe the cohort in 2 tables.\nSection V. Review\nx" + " More text." * 100

def test_a_new_application_lists_its_sections_and_gaps(tmp_path) -> None:
    view = start(tmp_path).view()
    assert [s.rule.key for s in view.sections] == ["specific-aims", "research-strategy", "project-summary", "project-narrative"]
    assert view.section("specific-aims").state == "empty" and view.section("specific-aims").gaps == ("aim", "hypothesis")

def test_a_resubmission_adds_the_introduction(tmp_path) -> None:
    assert start(tmp_path, resubmission=True).view().sections[0].rule.key == "introduction"

def test_a_save_from_a_stale_revision_is_refused_and_keeps_both(tmp_path) -> None:
    ws = start(tmp_path)
    first = ws.write("specific-aims", "Tab one.", parent=None)
    with pytest.raises(StaleEdit) as stale:
        ws.write("specific-aims", "Tab two.", parent=None)
    assert stale.value.head.id == first.id
    ws.write("specific-aims", "Tab two.", parent=first.id)
    assert [r.text for r in ws.view().log] == ["Tab one.", "Tab two."]

def test_signing_is_refused_while_an_error_stands_and_goes_stale_on_an_edit(tmp_path) -> None:
    ws = start(tmp_path)
    revision = ws.write("project-narrative", "One. Two. Three. Four.", parent=None)
    with pytest.raises(NotReady) as blocked:
        ws.sign("project-narrative", "A. Applicant", revision.id)
    assert [f.code for f in blocked.value.findings] == ["over-limit"] and blocked.value.reason
    fixed = ws.write("project-narrative", "One. Two. Three.", parent=revision.id)
    with pytest.raises(StaleEdit):
        ws.sign("project-narrative", "A. Applicant", revision.id)
    signed = ws.sign("project-narrative", "A. Applicant", fixed.id)
    assert signed.revision_id == fixed.id and "By Grant Matcher's record, 0 percent" in signed.attestation
    assert ws.view().section("project-narrative").state == "final"
    ws.write("project-narrative", "One. Two.", parent=fixed.id)
    assert ws.view().section("project-narrative").state == "draft"

def test_a_confirmed_announcement_limit_replaces_the_standing_one_in_the_view_and_the_draft(tmp_path) -> None:
    ws = start(tmp_path, model=FakeModel("Draft."), facts=dict.fromkeys(("aim", "significance", "innovation", "method"), "An input."))
    ws.fetch_announcement(Guide(FOUR_PAGES), Grants(""))
    requirement = next(r for r in ws.view().requirements if r.kind == "limit")
    assert ws.view().section("research-strategy").limit.amount == 6
    ws.decide(requirement.id, True)
    assert ws.view().section("research-strategy").limit.amount == 4
    ws.propose("research-strategy", "draft")
    assert "Its limit is 4 pages." in ws.model.seen[-1].system

def test_two_confirmed_limits_for_a_section_apply_the_smaller_with_a_notice(tmp_path) -> None:
    ws = start(tmp_path)
    ws.fetch_announcement(Guide(FOUR_PAGES.replace("Section V", "The Research Strategy must not exceed 3 pages. Section V")), Grants(""))
    for requirement in ws.view().requirements:
        ws.decide(requirement.id, True)
    view = ws.view()
    assert view.section("research-strategy").limit.amount == 3 and any("Research Strategy" in notice for notice in view.notices)

def test_the_workspace_opens_when_the_announcement_cannot_be_fetched(tmp_path) -> None:
    ws = start(tmp_path)
    with pytest.raises(ApiError):
        ws.fetch_announcement(Guide(""), Grants(""))
    assert ws.view().announcement is None and len(ws.view().sections) == 4

def test_a_decided_requirement_stays_while_its_quote_is_in_the_text(tmp_path) -> None:
    ws = start(tmp_path)
    ws.fetch_announcement(Guide(FOUR_PAGES), Grants(""))
    ws.decide(ws.view().requirements[0].id, False)
    ws.fetch_announcement(Guide(FOUR_PAGES + " More text."), Grants(""))
    assert [(r.kind, r.confirmed) for r in ws.view().requirements] == [("limit", False)]
    ws.fetch_announcement(Guide(FOUR_PAGES.replace("4 pages", "5 pages")), Grants(""))
    assert [(r.text, r.confirmed) for r in ws.view().requirements] == [("Research Strategy: at most 5 pages.", None)]

def test_the_sixth_application_of_the_year_carries_the_notice(tmp_path) -> None:
    ws = start(tmp_path, others=5)
    assert any("six" in notice for notice in ws.view().notices)
    assert not start(tmp_path / "fewer", others=4).view().notices

def test_restoring_an_old_revision_brings_back_its_text(tmp_path) -> None:
    ws = start(tmp_path)
    first = ws.write("specific-aims", "Aim 1.", parent=None)
    second = ws.write("specific-aims", "Aim 1, changed.", parent=first.id)
    restored = ws.restore("specific-aims", first.id, parent=second.id)
    assert (restored.parent_id, restored.author, ws.view().section("specific-aims").text) == (first.id, "applicant", "Aim 1.")

def test_the_prior_work_of_the_profile_becomes_reference_facts(tmp_path) -> None:
    ws = start(tmp_path, profile=Profile(prior_work=(Reference("smith2021", "Smith J. Heart cells. 2021.", pmid="123"),)))
    assert [(f.kind, f.label, f.detail) for f in ws.view().facts] == [("reference", "smith2021", {"pmid": "123"})]
    ws.write("specific-aims", "As we showed [@smith2021].", parent=None)
    assert "unknown-citation" not in {f.code for f in ws.view().section("specific-aims").findings}

def test_a_retired_reference_is_not_a_known_citation(tmp_path) -> None:
    ws = start(tmp_path)
    fact = ws.add_fact("reference", "Smith J. Heart cells. 2021.", label="smith2021")
    ws.write("specific-aims", "As we showed [@smith2021].", parent=None)
    assert "unknown-citation" not in {f.code for f in ws.view().section("specific-aims").findings}
    ws.retire_fact(fact.id)
    assert ws.view().facts == () and "unknown-citation" in {f.code for f in ws.view().section("specific-aims").findings}

class Index:
    def __init__(self, titles: dict[str, str], fail_on: str | tuple[str, ...] = ()) -> None: self.titles, self.fail_on, self.asked = titles, (fail_on,) if isinstance(fail_on, str) else fail_on, []
    def lookup(self, pmid: str = "", doi: str = "") -> str:
        self.asked.append((pmid, doi))
        if (pmid or doi) in self.fail_on:
            raise ApiError("Checking it failed: HTTP Error 503")
        return self.titles.get(pmid or doi, "")

REFERENCES = {"known": "Smith J. Heart cells. 2021. PMID: 123 doi:10.1038/smith", "unknown": "Jones K. Lost work. 2020. https://doi.org/10.9999/none.", "bare": "Lee A. Unpublished. 2019."}

def _with_references(tmp_path) -> Workspace:
    ws = start(tmp_path)
    for label, text in REFERENCES.items():
        ws.add_fact("reference", text, label=label)
    ws.write("specific-aims", "We showed [@known], [@unknown] and [@bare].", parent=None)
    return ws

def test_verify_records_what_each_index_holds_and_warns_on_what_it_does_not(tmp_path) -> None:
    ws, index = _with_references(tmp_path), Index({"123": "Heart cells."})
    assert ws.verify_references(index) == 2
    assert index.asked == [("123", "10.1038/smith"), ("", "10.9999/none")]
    lookups = {f.label: f.detail.get("lookup") for f in ws.view().facts}
    assert {k: (v["service"], v["id"], v["title"]) for k, v in lookups.items() if v} == {"known": ("PubMed", "PMID 123", "Heart cells."), "unknown": ("Crossref", "DOI 10.9999/none", "")}
    assert lookups["bare"] is None and lookups["known"]["on"] == date.today().isoformat()
    assert [f.excerpt for f in ws.view().section("specific-aims").findings if f.code == "unverified-reference"] == ["[@unknown]", "[@bare]"]
    assert ws.store.facts(ws.application_id)[0].text == REFERENCES["known"]

def test_an_unverified_reference_does_not_block_sign_off(tmp_path) -> None:
    ws = _with_references(tmp_path)
    s = ws.view().section("specific-aims")
    assert ws.sign("specific-aims", "A. Applicant", s.revision_id).findings.count("unverified-reference") == 1

def test_a_failed_lookup_keeps_earlier_results_and_records_nothing_for_it(tmp_path) -> None:
    ws = _with_references(tmp_path)
    with pytest.raises(ApiError, match=r"^Grant Matcher could not check 1 reference\. \[@unknown\]: Checking it failed: HTTP Error 503\. It checked 1 reference and saved what it found\."):
        ws.verify_references(Index({"123": "Heart cells."}, fail_on="10.9999/none"))
    assert [bool(f.detail.get("lookup")) for f in ws.view().facts] == [True, False, False]

def _three(tmp_path) -> Workspace:
    ws = start(tmp_path)
    for label, text in (("mine", "Mine A. 2021. PMID: 0033611339"), ("smith", "Smith J. 2020. PMID: 111"), ("lee", "Lee K. 2019. doi:10.1000/x")):
        ws.add_fact("reference", text, label=label)
    return ws

def test_a_reference_that_fails_every_time_does_not_block_the_ones_after_it(tmp_path) -> None:
    from nih_grant_matcher.writer import lookup_line
    ws, index = _three(tmp_path), Index({"111": "Smith title.", "10.1000/x": "Lee title."}, fail_on="33611339")
    with pytest.raises(ApiError) as failed:
        ws.verify_references(index)
    said = str(failed.value)
    assert index.asked == [("33611339", ""), ("111", ""), ("", "10.1000/x")]
    assert said.startswith("Grant Matcher could not check 1 reference. [@mine]: Checking it failed: HTTP Error 503. It checked 2 references and saved what it found.") and "Try again later. For a reference that fails every time, correct its identifier or retire it." in said
    lines = {f.label: lookup_line(f) for f in ws.view().facts}
    assert lines["mine"] == "Not checked yet." and lines["smith"].endswith("PubMed holds PMID 111 as: Smith title.") and lines["lee"].endswith("Crossref holds DOI 10.1000/x as: Lee title.")

def test_two_failed_lookups_in_a_row_stop_the_check_and_say_so(tmp_path) -> None:
    ws, index = _three(tmp_path), Index({"10.1000/x": "Lee title."}, fail_on=("33611339", "111"))
    with pytest.raises(ApiError) as failed:
        ws.verify_references(index)
    said = str(failed.value)
    assert index.asked == [("33611339", ""), ("111", "")] and "could not check 2 references. [@mine]: Checking it failed: HTTP Error 503. [@smith]: Checking it failed: HTTP Error 503. It checked 0 references" in said
    assert "Two lookups in a row failed, so the index is most likely not answering, and Grant Matcher did not try the 1 reference after them." in said
    assert not any(f.detail.get("lookup") for f in ws.view().facts)

def test_a_zero_padded_pmid_finds_the_record_ncbi_keys_without_the_zeros(tmp_path, monkeypatch) -> None:
    import io
    from nih_grant_matcher import clients
    from nih_grant_matcher.writer import lookup_line
    asked = []
    def ncbi(request, timeout):
        asked.append(pmid := request.full_url.split("id=")[1].split("&")[0])
        return io.BytesIO(json.dumps({"header": {}, "result": {"uids": [pmid.lstrip("0")], pmid.lstrip("0"): {"uid": pmid.lstrip("0"), "title": "The role of m6A."}}}).encode())
    monkeypatch.setattr(clients.urllib.request, "urlopen", ncbi)
    monkeypatch.setattr(clients.time, "sleep", lambda seconds: None)
    ws = start(tmp_path)
    ws.add_fact("reference", "Mine A. 2021. PMID: 0033611339", label="mine")
    assert ws.verify_references() == 1 and asked == ["33611339"]
    assert lookup_line(ws.view().facts[0]).endswith("PubMed holds PMID 33611339 as: The role of m6A.")

def test_the_check_is_dated_by_this_computer_s_clock(tmp_path, monkeypatch) -> None:
    from nih_grant_matcher import writer
    class Day(date):
        @classmethod
        def today(cls): return date(2026, 11, 23)
    class Now(datetime):
        @classmethod
        def now(cls, tz=None): return datetime(2026, 11, 24, 1, tzinfo=timezone.utc)
    monkeypatch.setattr(writer, "date", Day)
    monkeypatch.setattr(writer, "datetime", Now)
    ws = _with_references(tmp_path)
    ws.verify_references(Index({"123": "Heart cells."}))
    assert ws.view().facts[0].detail["lookup"]["on"] == "2026-11-23"

def test_a_save_that_fails_after_a_lookup_says_what_was_sent(tmp_path, monkeypatch) -> None:
    ws = _with_references(tmp_path)
    def locked(*args, **kwargs): raise sqlite3.OperationalError("attempt to write a readonly database")
    monkeypatch.setattr(ws.store, "set_fact_detail", locked)
    with pytest.raises(WorkspaceError, match=r"^Grant Matcher sent PMID 123 to PubMed, but could not save what it found \(attempt to write a readonly database\)\. It checked 0 references before it\.") as failed:
        ws.verify_references(Index({"123": "Heart cells."}))
    assert isinstance(failed.value, ValueError)

@pytest.mark.parametrize("found, said, gone", [({"service": "Crossref", "id": "DOI 10.48550/arXiv.1706.03762"}, "Crossref holds no record for DOI 10.48550/arXiv.1706.03762. A DOI registered elsewhere, such as an arXiv or Zenodo DOI, which DataCite registers, is not in Crossref. Check the identifier.", "exist"), ({"service": "PubMed", "id": "PMID 999"}, "PubMed has no record of PMID 999.", "DataCite")], ids=["doi", "pmid"])
def test_a_doi_crossref_does_not_hold_is_not_said_to_be_missing_from_the_world(found, said, gone) -> None:
    from nih_grant_matcher.checks import check_section
    from nih_grant_matcher.models import Fact
    from nih_grant_matcher.rules import GRANT_TYPES, Limit
    from nih_grant_matcher.writer import lookup_line
    fact = Fact(1, "reference", "Vaswani A. 2017. PMID: 999 doi:10.48550/arXiv.1706.03762", label="v", detail={"lookup": {**found, "on": "2026-11-23", "title": ""}})
    assert lookup_line(fact) == f"Checked on 2026-11-23. {said}"
    r21 = GRANT_TYPES["NIH:R21"]
    warning = next(f.message for f in check_section("As shown [@v].", r21.sections[0], Limit(1, "pages"), r21.page, (fact,), "", ()) if f.code == "unverified-reference")
    assert said[:30] in warning and gone not in warning

def test_a_second_run_looks_every_live_reference_up_again(tmp_path) -> None:
    ws = _with_references(tmp_path)
    ws.verify_references(Index({}))
    ws.retire_fact(ws.view().facts[1].id)
    index = Index({"123": "Heart cells."})
    assert ws.verify_references(index) == 1 and index.asked == [("123", "10.1038/smith")]
    assert ws.view().facts[0].detail["lookup"]["title"] == "Heart cells."

def test_a_second_grant_type_for_the_same_announcement_is_its_own_application(tmp_path) -> None:
    ws = start(tmp_path)
    other = Workspace.start(ws.store, ws.opportunity, "NIH:R21", resubmission=True)
    assert other.application_id != ws.application_id and Workspace.start(ws.store, ws.opportunity, "NIH:R21").application_id == ws.application_id

def test_a_grant_type_the_opportunity_does_not_list_is_refused(tmp_path) -> None:
    ws = start(tmp_path)
    with pytest.raises(ValueError):
        Workspace.start(ws.store, ws.opportunity, "NIH:R01")

def test_deleting_an_application_removes_it(tmp_path) -> None:
    ws = start(tmp_path)
    ws.write("specific-aims", "Aim 1.", parent=None)
    ws.delete()
    assert ws.store.applications() == []

def test_export_marks_an_unsigned_section_as_a_draft(tmp_path) -> None:
    ws = start(tmp_path)
    ws.write("project-narrative", "One. Two.", parent=None)
    names = sorted(path.name for path in ws.export(tmp_path / "out").iterdir())
    assert "DRAFT-project-narrative.md" in names and "provenance-log.md" in names and "requirements.md" in names

def test_a_signed_section_exports_without_the_draft_mark(tmp_path) -> None:
    ws = start(tmp_path)
    revision = ws.write("project-narrative", "One. Two.", parent=None)
    ws.export(tmp_path / "out")
    ws.sign("project-narrative", "A. Applicant", revision.id)
    names = {path.name for path in ws.export(tmp_path / "out").iterdir()}
    assert "project-narrative.md" in names and "DRAFT-project-narrative.md" not in names
    assert "A. Applicant" in (tmp_path / "out" / "provenance-log.md").read_text(encoding="utf-8")

def test_writing_the_same_text_adds_no_revision(tmp_path) -> None:
    ws = start(tmp_path)
    first = ws.write("specific-aims", "Aim 1.", parent=None)
    assert ws.write("specific-aims", "Aim 1.", parent=first.id) == first and len(ws.view().log) == 1

def test_a_mostly_drafted_section_signs_only_when_acknowledged(tmp_path) -> None:
    ws = start(tmp_path)
    call = ws.store.add_call(ws.application_id, "project-narrative", "draft", "anthropic", "claude-opus-5-5", "s", "p", "r")
    revision = ws.store.add_revision(ws.application_id, "project-narrative", None, "model", "draft", "We study heart cells.", call.id)
    with pytest.raises(NotReady) as blocked:
        ws.sign("project-narrative", "A. Applicant", revision.id)
    assert [f.code for f in blocked.value.findings] == ["mostly-drafted"]
    signed = ws.sign("project-narrative", "A. Applicant", revision.id, acknowledge=True)
    stored = ws.store.signoffs(ws.application_id)[0]
    assert "mostly-drafted" in stored.findings and stored.tool_version == __version__ and "100 percent" in signed.attestation

def test_a_sign_off_needs_a_name_and_text(tmp_path) -> None:
    ws = start(tmp_path)
    with pytest.raises(NotReady):
        ws.sign("project-narrative", "A. Applicant", 1)
    revision = ws.write("project-narrative", "One.", parent=None)
    with pytest.raises(NotReady):
        ws.sign("project-narrative", "  ", revision.id)

def test_a_save_between_reading_the_head_and_writing_is_refused(tmp_path, monkeypatch) -> None:
    from nih_grant_matcher.store import OpportunityStore
    ws = start(tmp_path)
    base = ws.write("specific-aims", "Base.", parent=None)
    other = Workspace(OpportunityStore(ws.store.db_path), ws.application_id)
    read = ws.store.revisions
    def read_then_other_tab_saves(app_id):
        found = read(app_id)
        monkeypatch.setattr(ws.store, "revisions", read)
        other.write("specific-aims", "Tab two.", parent=base.id)
        return found
    monkeypatch.setattr(ws.store, "revisions", read_then_other_tab_saves)
    with pytest.raises(StaleEdit) as stale:
        ws.write("specific-aims", "Tab one.", parent=base.id)
    assert stale.value.head.text == "Tab two."
    assert [(r.id, r.parent_id, r.text) for r in ws.view().log] == [(1, None, "Base."), (2, 1, "Tab two.")]
    other.store.close()

def test_an_unreadable_profile_does_not_stop_a_start(tmp_path) -> None:
    from helpers import opportunity
    from nih_grant_matcher.store import OpportunityStore
    store = OpportunityStore(tmp_path / "g.sqlite3")
    with store.conn:
        store.conn.execute("INSERT INTO profile VALUES (1, ?, ?)", ('{"format": "grant-matcher-profile/2", "profile": {}}', "2026-11-23T00:00:00"))
    ws = Workspace.start(store, opportunity(), "NIH:R21")
    assert ws.view().facts == () and len(ws.view().sections) == 4

def test_a_confirmed_limit_in_another_unit_is_not_applied(tmp_path) -> None:
    ws = start(tmp_path)
    ws.fetch_announcement(Guide(FOUR_PAGES.replace("Section V", "The Project Summary/Abstract is limited to 1 page. Section V")), Grants(""))
    for requirement in ws.view().requirements:
        ws.decide(requirement.id, True)
    assert (ws.view().section("project-summary").limit.amount, ws.view().section("project-summary").limit.unit) == (30, "lines")
    assert any("Project Summary/Abstract" in notice and "1 page" in notice and "lines" in notice for notice in ws.view().notices)

def test_a_second_application_for_the_announcement_gets_its_requirements(tmp_path) -> None:
    ws = start(tmp_path)
    ws.fetch_announcement(Guide(FOUR_PAGES), Grants(""))
    ws.decide(ws.view().requirements[0].id, True)
    other = Workspace.start(ws.store, ws.opportunity, "NIH:R21", resubmission=True)
    assert [(r.text, r.confirmed) for r in other.view().requirements] == [("Research Strategy: at most 4 pages.", None)]
    other.decide(other.view().requirements[0].id, False)
    Workspace.start(ws.store, ws.opportunity, "NIH:R21", resubmission=True)
    assert [r.confirmed for r in other.view().requirements] == [False] and [r.confirmed for r in ws.view().requirements] == [True]

def test_a_fetch_in_one_application_reads_the_announcement_for_another_of_its_number(tmp_path) -> None:
    a = start(tmp_path)
    b = Workspace.start(a.store, a.opportunity, "NIH:R21", resubmission=True)
    a.fetch_announcement(Guide(FOUR_PAGES), Grants(""))
    assert [(r.text, r.confirmed) for r in b.view().requirements] == [("Research Strategy: at most 4 pages.", None)]
    b.decide(b.view().requirements[0].id, True)
    assert b.view().section("research-strategy").limit.amount == 4
    a.fetch_announcement(Guide(FOUR_PAGES.replace("4 pages", "5 pages")), Grants(""))
    assert [(r.text, r.confirmed) for r in b.view().requirements] == [("Research Strategy: at most 5 pages.", None)]
    assert b.view().section("research-strategy").limit.amount == 6

def test_a_decision_in_another_application_stays_while_its_quote_is_in_the_text(tmp_path) -> None:
    a = start(tmp_path)
    b = Workspace.start(a.store, a.opportunity, "NIH:R21", resubmission=True)
    a.fetch_announcement(Guide(FOUR_PAGES), Grants(""))
    b.decide(b.view().requirements[0].id, False)
    a.fetch_announcement(Guide(FOUR_PAGES + " More text."), Grants(""))
    assert [(r.text, r.confirmed) for r in b.view().requirements] == [("Research Strategy: at most 4 pages.", False)]

def test_a_grants_gov_text_replaces_a_saved_guide_copy_and_the_guide_text_does_not_replace_it(tmp_path) -> None:
    from dataclasses import replace
    ws = start(tmp_path)
    ws.opportunity = replace(ws.opportunity, raw={"guide_item": {"ggid": "360675"}})
    ws.fetch_announcement(Guide(FOUR_PAGES), Grants(""))
    official, _ = ws.fetch_announcement(GuideDown(), Grants(GRANTS_PAGE))
    assert official.origin == "grants.gov" and ws.view().announcement == official
    # Grants.gov is down or attaches nothing this time, and the Guide can serve an older text.
    ws.decide(ws.view().requirements[0].id, True)
    with pytest.raises(ApiError, match="Grants.gov has no full announcement attached. Grant Matcher kept the copy it saved from Grants.gov on"):
        ws.fetch_announcement(Guide(FOUR_PAGES.replace("4 pages", "5 pages")), Grants(""))
    assert ws.view().announcement == official and [(r.text, r.confirmed) for r in ws.view().requirements] == [("Research Strategy: at most 4 pages.", True)]

def test_a_guide_text_saved_while_grants_gov_is_down_says_it_may_not_be_the_official_one(tmp_path) -> None:
    ws = start(tmp_path)
    announcement, notes = ws.fetch_announcement(Guide(FOUR_PAGES), GrantsDown())
    assert announcement.origin == "nih-guide" and len(notes) == 1 and "The request to Grants.gov failed (HTTP 503)" in notes[0] and "may not be the official one" in notes[0]
    assert ws.fetch_announcement(Guide(FOUR_PAGES), Grants(""))[1] == []

def test_a_decision_on_instructions_that_changed_in_one_number_is_dropped(tmp_path) -> None:
    ws = start(tmp_path)
    ws.fetch_announcement(Guide(MUST), Grants(""))
    ws.decide(ws.view().requirements[0].id, True)
    assert ws.fetch_announcement(Guide(MUST + " More text."), Grants(""))[1] == [] and ws.view().requirements[0].confirmed is True
    _, notes = ws.fetch_announcement(Guide(MUST.replace("2 tables", "3 tables")), Grants(""))
    assert notes == ['Your decision on "Follow the announcement\'s additional instructions for the Research Plan." was dropped, because the new text no longer has the sentence it came from.']
    assert [(r.confirmed, "3 tables" in r.quote) for r in ws.view().requirements] == [(None, True)]

def test_a_decision_whose_sentence_stays_but_is_no_longer_read_as_a_requirement_is_dropped(tmp_path) -> None:
    ws = start(tmp_path)
    ws.fetch_announcement(Guide(FOUR_PAGES), Grants(""))
    ws.decide(ws.view().requirements[0].id, True)
    _, notes = ws.fetch_announcement(Guide(FOUR_PAGES.replace("Section IV. ", "Part 4. ")), Grants(""))
    assert notes == ['Your decision on "Research Strategy: at most 4 pages." was dropped, because Grant Matcher no longer reads that requirement from the new text.'] and ws.view().requirements == ()

def test_a_decision_moves_to_the_new_sentence_and_a_changed_limit_drops_it(tmp_path) -> None:
    ws = start(tmp_path)
    ws.fetch_announcement(Guide(FOUR_PAGES), Grants(""))
    ws.decide(ws.view().requirements[0].id, True)
    longer = FOUR_PAGES.replace("4 pages.", "4 pages for the first phase.")
    _, dropped = ws.fetch_announcement(Guide(longer), Grants(""))
    kept = ws.view().requirements
    assert dropped == [] and [(r.text, r.confirmed) for r in kept] == [("Research Strategy: at most 4 pages.", True)] and "first phase" in kept[0].quote
    _, dropped = ws.fetch_announcement(Guide(FOUR_PAGES.replace("4 pages.", "4.5 pages.")), Grants(""))
    assert dropped == [DROPPED_FOUR]
    assert [(r.text, r.confirmed) for r in ws.view().requirements] == [("Research Strategy: at most 4.5 pages.", None)]

def test_a_decision_made_on_the_guide_text_carries_to_the_grants_gov_text_of_the_same_sentence(tmp_path) -> None:
    ws = start(tmp_path)
    # The Guide text drops the opening bracket that the Grants.gov text keeps.
    ws.fetch_announcement(Guide(FOUR_PAGES.replace("4 pages.", "4 pages, as in NOT-OD-26-001).")), Grants(""))
    ws.decide(ws.view().requirements[0].id, True)
    _, dropped = ws.fetch_announcement(Guide(""), Grants(GRANTS_PAGE))
    assert dropped == [] and ws.view().announcement.origin == "grants.gov" and [(r.text, r.confirmed) for r in ws.view().requirements] == [("Research Strategy: at most 4 pages.", True)]

def test_a_fetch_reports_the_decisions_it_dropped_in_every_application_of_the_number(tmp_path) -> None:
    a = start(tmp_path)
    b = Workspace.start(a.store, a.opportunity, "NIH:R21", resubmission=True)
    a.fetch_announcement(Guide(FOUR_PAGES), Grants(""))
    a.decide(a.view().requirements[0].id, True)
    b.decide(b.view().requirements[0].id, False)
    _, dropped = a.fetch_announcement(Guide(FOUR_PAGES.replace("4 pages", "5 pages")), Grants(""))
    assert dropped == [DROPPED_FOUR, DROPPED_FOUR.replace("Your decision", f"Application {b.application_id} lost its decision").replace(" was dropped", "")]

def test_a_blank_section_cannot_be_signed(tmp_path) -> None:
    ws = start(tmp_path)
    revision = ws.write("project-narrative", "  \n ", parent=None)
    with pytest.raises(NotReady):
        ws.sign("project-narrative", "A. Applicant", revision.id)
    assert ws.store.signoffs(ws.application_id) == []

def test_a_signed_section_with_a_new_error_is_a_draft_again(tmp_path) -> None:
    ws = start(tmp_path)
    fact = ws.add_fact("reference", "Smith J. Heart cells. 2021.", label="smith2021")
    revision = ws.write("specific-aims", "As we showed [@smith2021].", parent=None)
    ws.sign("specific-aims", "A. Applicant", revision.id)
    assert ws.view().section("specific-aims").state == "final" and not ws.view().notices
    ws.retire_fact(fact.id)
    view = ws.view()
    assert view.section("specific-aims").state == "draft" and len(ws.store.signoffs(ws.application_id)) == 1
    assert [n for n in view.notices if "Specific Aims" in n and "draft again" in n and "error" in n and "log" in n]
    names = {path.name for path in ws.export(tmp_path / "out").iterdir()}
    assert "DRAFT-specific-aims.md" in names and "specific-aims.md" not in names

def test_an_announcement_without_a_section_iv_is_named_as_one(tmp_path) -> None:
    ws = start(tmp_path)
    assert not ws.view().no_section_iv
    ws.fetch_announcement(Guide(FOUR_PAGES), Grants(""))
    assert not ws.view().no_section_iv
    ws.fetch_announcement(Guide("A notice with no headings at all. " * 40), Grants(""))
    assert ws.view().no_section_iv and ws.view().requirements == ()

def test_export_returns_the_absolute_folder(tmp_path, monkeypatch) -> None:
    ws = start(tmp_path)
    monkeypatch.chdir(tmp_path)
    assert ws.export(Path("outputs/application-1")) == (tmp_path / "outputs" / "application-1").resolve()

def test_the_provenance_log_names_the_announcement_and_the_inputs(tmp_path) -> None:
    ws = start(tmp_path)
    announcement, _ = ws.fetch_announcement(Guide(FOUR_PAGES), Grants(""))
    kept, retired = ws.add_fact("reference", "Smith J. Heart cells. 2021.", label="smith2021"), ws.add_fact("aim", "A secret aim.")
    ws.retire_fact(retired.id)
    log = (ws.export(tmp_path / "out") / "provenance-log.md").read_text(encoding="utf-8")
    assert all(part in log for part in ("the NIH Guide", announcement.url, announcement.sha256, f"{announcement.fetched_at:%Y-%m-%d}"))
    assert f"Input {kept.id}. reference, key smith2021. In use." in log and f"Input {retired.id}. aim. Retired on" in log
    assert "A secret aim." not in log and "Heart cells" not in log

def test_a_rejected_limit_is_not_applied(tmp_path) -> None:
    ws = start(tmp_path)
    ws.fetch_announcement(Guide(FOUR_PAGES), Grants(""))
    ws.decide(ws.view().requirements[0].id, False)
    assert ws.view().section("research-strategy").limit.amount == 6

def test_an_application_whose_notice_has_closed_still_fetches_by_its_number(tmp_path) -> None:
    from datetime import date
    from dataclasses import replace
    from helpers import opportunity
    from nih_grant_matcher.scoring import MLRelevanceScorer
    from nih_grant_matcher.store import OpportunityStore
    store = OpportunityStore(tmp_path / "g.sqlite3")
    closed = replace(opportunity(), close_date=date(2020, 1, 1), raw={"guide_item": {"ggid": "361234"}})
    store.upsert_scored(MLRelevanceScorer().score(closed))
    ws = Workspace.start(store, closed, "NIH:R21")
    guide, grants = Guide(FOUR_PAGES, ggid=""), Grants(GRANTS_PAGE)
    ws.fetch_announcement(guide, grants)
    assert guide.asked == ["PAR-1"] and grants.asked == ["361234"] and ws.view().announcement.origin == "grants.gov"

def test_the_attestation_names_the_digest_of_the_section_text(tmp_path) -> None:
    import hashlib
    ws = start(tmp_path)
    revision = ws.write("project-narrative", "One. Two.", parent=None)
    signed = ws.sign("project-narrative", "A. Applicant", revision.id)
    assert signed.attestation.endswith(f"Revision {revision.id}, sha256 {hashlib.sha256('One. Two.'.encode('utf-8')).hexdigest()}.")

def test_the_export_holds_the_rules_the_decisions_the_log_and_the_text(tmp_path) -> None:
    ws = start(tmp_path)
    ws.fetch_announcement(Guide(FOUR_PAGES), Grants(""))
    ws.decide(ws.view().requirements[0].id, True)
    revision = ws.write("specific-aims", "Aim 1 maps heart cells.", parent=None)
    out = ws.export(tmp_path / "out")
    requirements = (out / "requirements.md").read_text(encoding="utf-8")
    assert "- Specific Aims. At most 1 page." in requirements and "- Research Strategy: at most 4 pages. (confirmed). The announcement says" in requirements
    assert f"- Revision {revision.id}. Specific Aims. applicant write, parent none, at " in (out / "provenance-log.md").read_text(encoding="utf-8")
    assert (out / "DRAFT-specific-aims.md").read_text(encoding="utf-8") == "# Specific Aims\n\nAim 1 maps heart cells.\n"

def test_a_restore_after_a_save_from_another_tab_is_refused(tmp_path) -> None:
    from nih_grant_matcher.store import OpportunityStore
    ws = start(tmp_path)
    first = ws.write("specific-aims", "Aim 1.", parent=None)
    second = ws.write("specific-aims", "Aim 1, changed.", parent=first.id)
    other = Workspace(OpportunityStore(ws.store.db_path), ws.application_id)
    other.write("specific-aims", "Tab two.", parent=second.id)
    with pytest.raises(StaleEdit) as stale:
        ws.restore("specific-aims", first.id, parent=second.id)
    assert stale.value.head.text == "Tab two." and ws.view().section("specific-aims").text == "Tab two."
    other.store.close()

def test_a_restore_is_refused_when_another_tab_saves_during_the_call(tmp_path, monkeypatch) -> None:
    from nih_grant_matcher.store import OpportunityStore
    ws = start(tmp_path)
    first = ws.write("specific-aims", "Aim 1.", parent=None)
    second = ws.write("specific-aims", "Aim 1, changed.", parent=first.id)
    other = Workspace(OpportunityStore(ws.store.db_path), ws.application_id)
    read = ws.store.revisions
    def read_then_other_tab_saves(app_id):
        found = read(app_id)
        monkeypatch.setattr(ws.store, "revisions", read)
        other.write("specific-aims", "Tab two.", parent=second.id)
        return found
    monkeypatch.setattr(ws.store, "revisions", read_then_other_tab_saves)
    with pytest.raises(StaleEdit) as stale:
        ws.restore("specific-aims", first.id, parent=second.id)
    assert stale.value.head.text == "Tab two." and [r.text for r in ws.view().log] == ["Aim 1.", "Aim 1, changed.", "Tab two."]
    other.store.close()

def test_a_proposal_changes_nothing_until_it_is_accepted(tmp_path) -> None:
    ws = start(tmp_path, model=FakeModel("We study cardiac muscle cells."))
    mine = ws.write("specific-aims", "We study heart cells.", parent=None)
    proposal = ws.propose("specific-aims", "polish")
    assert ws.view().section("specific-aims").text == "We study heart cells." and proposal.parent_id == mine.id
    accepted = ws.accept(proposal.call_id)
    assert (accepted.author, accepted.action, accepted.call_id) == ("model", "polish", proposal.call_id)
    assert ws.accept(proposal.call_id).id == accepted.id
    assert ws.view().section("specific-aims").attribution.model_words == 2

def test_accepting_with_my_edits_credits_my_words_to_me(tmp_path) -> None:
    ws = start(tmp_path, model=FakeModel("We study cardiac muscle cells."))
    ws.write("specific-aims", "We study heart cells.", parent=None)
    ws.accept(ws.propose("specific-aims", "polish").call_id, edited="We study cardiac cells.")
    assert ws.view().section("specific-aims").attribution.model_words == 1
    assert [r.author for r in ws.view().log] == ["applicant", "model", "applicant"]

def test_a_truncated_reply_is_not_offered(tmp_path) -> None:
    ws = start(tmp_path, model=FakeModel("We study", truncated=True))
    ws.write("specific-aims", "We study heart cells.", parent=None)
    with pytest.raises(ModelError, match="cut off"):
        ws.propose("specific-aims", "polish")
    assert len(ws.store.calls(ws.application_id)) == 1 and len(ws.view().log) == 1
    assert ws.pending("specific-aims") is None and ws.store.calls(ws.application_id)[0].purpose == "failed"

def test_a_reply_with_no_text_is_not_offered(tmp_path) -> None:
    ws = start(tmp_path, model=FakeModel(" \n "))
    ws.write("specific-aims", "We study heart cells.", parent=None)
    with pytest.raises(ModelError, match="returned no text"):
        ws.propose("specific-aims", "polish")
    assert ws.pending("specific-aims") is None and [c.purpose for c in ws.store.calls(ws.application_id)] == ["failed"]

def test_a_refusal_is_reported_and_logged(tmp_path) -> None:
    ws = start(tmp_path, model=FakeModel(error=ModelError("declined", kind="refused")))
    ws.write("specific-aims", "We study heart cells.", parent=None)
    with pytest.raises(ModelError):
        ws.propose("specific-aims", "polish")
    assert ws.store.calls(ws.application_id)[0].response == ""
    assert ws.pending("specific-aims") is None and ws.store.calls(ws.application_id)[0].purpose == "failed"

def test_a_call_whose_error_cannot_be_read_is_logged_as_failed(tmp_path, post) -> None:
    post.queue.append(error_with_unreadable_body(TimeoutError("timed out")))
    ws = start(tmp_path, model=model("compatible", base_url="https://example.test/v1"))
    ws.write("specific-aims", "We study heart cells.", parent=None)
    with pytest.raises(ModelError, match="may have reached example.test"):
        ws.propose("specific-aims", "polish")
    assert [c.purpose for c in ws.store.calls(ws.application_id)] == ["failed"] and "No AI model was used" not in ws.view().disclosure

@pytest.mark.parametrize("odd", [{"model": {"id": "served-2"}}, {"model": ["served-2"]}, {"usage": {"prompt_tokens": "40", "completion_tokens": 7.0}}, {"usage": {"prompt_tokens": True, "completion_tokens": {"text": 7}}}, {"usage": {"prompt_tokens": [40], "completion_tokens": "7"}}, {"usage": {"prompt_tokens": 10**20, "completion_tokens": -3}}])
def test_a_reply_with_a_model_or_a_count_of_another_type_is_offered_and_logged(odd, tmp_path, post) -> None:
    post.reply({"model": "served-1", "choices": [{"message": {"role": "assistant", "content": "We study cardiac cells."}, "finish_reason": "stop"}], "usage": {"prompt_tokens": 9, "completion_tokens": 5}, **odd})
    ws = start(tmp_path, model=model("compatible", base_url="https://example.test/v1"))
    ws.write("specific-aims", "We study heart cells.", parent=None)
    assert ws.propose("specific-aims", "polish").text == "We study cardiac cells."
    call = ws.store.calls(ws.application_id)[0]
    assert (call.purpose, call.model, call.input_tokens, call.output_tokens) == ("polish", "m" if "model" in odd else "served-1", *((0, 0) if "usage" in odd else (9, 5)))

@pytest.mark.parametrize("error", [None, ModelError("example.test answered 500: overloaded.", "overload", 500)])
def test_a_log_that_cannot_be_written_after_the_request_says_the_text_was_sent(error, tmp_path) -> None:
    import sqlite3
    fake = FakeModel("We study cardiac cells.", error=error)
    ws = start(tmp_path, model=fake)
    ws.write("specific-aims", "We study heart cells.", parent=None)
    blocker = sqlite3.connect(ws.store.db_path)
    blocker.execute("BEGIN IMMEDIATE")
    ws.store.conn.execute("PRAGMA busy_timeout = 50")
    try:
        with pytest.raises(ModelError) as failed:
            ws.propose("specific-aims", "polish")
    finally:
        blocker.rollback()
        blocker.close()
    said = str(failed.value)
    assert len(fake.seen) == 1 and "database is locked" in said and "AI-use statement will not show this call" in said
    assert said.startswith("Your text was sent to example.test" if error is None else "example.test answered 500: overloaded. Grant Matcher also could not write")

def test_the_statement_says_only_what_the_log_shows(tmp_path) -> None:
    ws = start(tmp_path, model=FakeModel("We study cardiac muscle cells."))
    ws.write("specific-aims", "We study heart cells.", parent=None)
    ws.write("project-narrative", "This helps patients.", parent=None)
    before = ws.view().disclosure
    assert "No AI model was used" in before and "polish" not in before and "I entered" not in before
    ws.add_fact("aim", "Test the drug.")
    proposal = ws.propose("specific-aims", "polish")
    assert "did not use" not in ws.view().disclosure and "polish the" not in ws.view().disclosure
    ws.accept(proposal.call_id)
    statement = ws.view().disclosure
    assert "I used fake-1 (fake) to polish the Specific Aims." in statement and "0 percent of the Specific Aims text came from a model's draft or revision that I accepted, and 40 percent from a model's polish" in statement
    assert "I entered the aims of this application myself." in statement and "The Project Narrative was written without a model." in statement
    assert "No AI model was used" not in statement and "signed off" not in statement and "I edited" not in statement
    ws.set_disclosure(False)
    assert ws.view().disclosure == ""

def test_the_statement_counts_a_suggestion_that_was_not_used(tmp_path) -> None:
    ws = start(tmp_path, model=FakeModel("We study cardiac muscle cells."))
    ws.write("specific-aims", "We study heart cells.", parent=None)
    ws.discard(ws.propose("specific-aims", "polish").call_id)
    assert ws.pending("specific-aims") is None
    assert "produce suggestions that I did not use (1)" in ws.view().disclosure and "to polish the" not in ws.view().disclosure

def test_only_a_proposal_can_be_accepted_and_only_on_the_text_it_read(tmp_path) -> None:
    ws = start(tmp_path, model=FakeModel("We study cardiac muscle cells.", "We study cardiac cells."))
    mine = ws.write("specific-aims", "We study heart cells.", parent=None)
    stale = ws.propose("specific-aims", "polish")
    ws.write("specific-aims", "We study heart cells in mice.", parent=mine.id)
    with pytest.raises(StaleEdit):
        ws.accept(stale.call_id)
    other = ws.store.add_call(ws.application_id, section="specific-aims", purpose="review", provider="fake", model="fake-1", system="s", prompt="p", response="{}", input_tokens=1, output_tokens=1)
    with pytest.raises(ValueError):
        ws.accept(other.id)

def test_a_draft_call_can_be_accepted(tmp_path) -> None:
    ws = start(tmp_path)
    mine = ws.write("specific-aims", "Aim 1.", parent=None)
    drafted = ws.store.add_call(ws.application_id, "specific-aims", "draft", "fake", "fake-1", "s", "p", "Aim 1 maps heart cells.", 1, 1, parent_id=mine.id)
    accepted = ws.accept(drafted.id)
    assert (accepted.author, accepted.action, accepted.call_id, ws.view().section("specific-aims").text) == ("model", "draft", drafted.id, "Aim 1 maps heart cells.")

def test_no_text_is_sent_without_consent_for_the_host(tmp_path) -> None:
    model = FakeModel("We study cardiac muscle cells.")
    ws = start(tmp_path, model=model, consent=False, facts={"aim": "Test drug X.", "hypothesis": "X lowers pressure."})
    ws.write("specific-aims", "We study heart cells.", parent=None)
    ws.fetch_announcement(Guide(READ), Grants(""))
    for ask in (lambda: ws.propose("specific-aims", "polish"), lambda: ws.propose("specific-aims", "draft"), ws.extract_requirements):
        with pytest.raises(NotReady, match="Agree to send text to example.test first"):
            ask()
    assert model.seen == [] and ws.store.calls(ws.application_id) == []

def test_consent_for_one_host_does_not_send_text_to_another(tmp_path) -> None:
    model = FakeModel("We study cardiac muscle cells.")
    ws = start(tmp_path, model=model, consent=False)
    ws.store.set_setting("consent:localhost", "2026-11-23T00:00:00")
    ws.write("specific-aims", "We study heart cells.", parent=None)
    with pytest.raises(NotReady, match="Agree to send text to example.test first"):
        ws.propose("specific-aims", "polish")
    assert model.seen == [] and ws.store.calls(ws.application_id) == []

def test_a_revise_prompt_holds_only_the_live_inputs_the_section_uses(tmp_path) -> None:
    ws = start(tmp_path, model=FakeModel("We map the heart."))
    ws.add_fact("aim", "Map the heart.")
    ws.retire_fact(ws.add_fact("aim", "Cure every disease.").id)
    ws.add_fact("team", "Dr. Okafor leads the lab.")
    ws.write("specific-aims", "We study heart cells.", parent=None)
    ws.propose("specific-aims", "revise", "Name the aim.")
    sent = ws.model.seen[0].user
    assert "Map the heart." in sent and "Cure every disease." not in sent and "Dr. Okafor" not in sent

def test_a_proposal_needs_a_model_saved_text_and_for_a_revise_an_instruction(tmp_path) -> None:
    model = FakeModel("We study cardiac muscle cells.")
    ws = start(tmp_path, model=model)
    with pytest.raises(NotReady, match="no text"):
        ws.propose("specific-aims", "polish")
    ws.write("specific-aims", "We study heart cells.", parent=None)
    with pytest.raises(NotReady, match="needs aim, hypothesis"):
        ws.propose("specific-aims", "draft")
    with pytest.raises(NotReady, match="what to change"):
        ws.propose("specific-aims", "revise", "  ")
    with pytest.raises(NotReady, match="Choose a model"):
        Workspace(ws.store, ws.application_id).propose("specific-aims", "polish")
    assert model.seen == []

def test_a_model_may_only_edit_the_introduction(tmp_path) -> None:
    ws = start(tmp_path, model=FakeModel("Reply."), resubmission=True)
    ws.write("introduction", "We answer the reviewers.", parent=None)
    with pytest.raises(NotReady, match="Introduction to Application"):
        ws.propose("introduction", "draft")
    assert ws.propose("introduction", "polish").text == "Reply."

def test_a_revision_counts_as_written_and_a_polish_as_polished(tmp_path) -> None:
    ws = start(tmp_path, model=FakeModel("Mice show this effect clearly."))
    ws.write("project-narrative", "We study heart cells.", parent=None)
    proposal = ws.propose("project-narrative", "revise", "Say what the mice show.")
    assert "Say what the mice show." in ws.model.seen[0].user and proposal.action == "revise"
    accepted = ws.accept(proposal.call_id)
    s = ws.view().section("project-narrative")
    assert accepted.action == "revise" and (s.attribution.written_words, s.attribution.polished_words) == (5, 0)
    assert "mostly-drafted" in {f.code for f in s.findings}

def test_a_proposal_is_checked_against_what_the_applicant_supplied(tmp_path) -> None:
    ws = start(tmp_path, model=FakeModel("We test 40 mice in 12 weeks.", "We test 40 mice in 12 weeks."))
    ws.write("specific-aims", "We test mice.", parent=None)
    first = ws.propose("specific-aims", "polish")
    assert [f.excerpt for f in first.findings if f.code == "number-not-in-inputs"] == ["40", "12"]
    ws.add_fact("method", "We test 40 mice over 12 weeks.")
    assert not [f for f in ws.pending("specific-aims").findings if f.code == "number-not-in-inputs"]

def test_a_pending_proposal_is_the_newest_that_can_still_be_accepted(tmp_path) -> None:
    ws = start(tmp_path, model=FakeModel("We study cardiac cells.", "We study cardiac muscle cells."))
    mine = ws.write("specific-aims", "We study heart cells.", parent=None)
    older, newer = ws.propose("specific-aims", "polish"), ws.propose("specific-aims", "polish")
    assert ws.pending("specific-aims") == newer and ws.pending("project-narrative") is None
    ws.discard(newer.call_id)
    assert ws.pending("specific-aims") == older
    with pytest.raises(WorkspaceError, match="discarded"):
        ws.accept(newer.call_id)
    ws.write("specific-aims", "We study heart cells in mice.", parent=mine.id)
    assert ws.pending("specific-aims") is None and "produce suggestions that I did not use (2)" in ws.view().disclosure

def test_a_second_accept_with_edits_returns_the_first_result(tmp_path) -> None:
    ws = start(tmp_path, model=FakeModel("We study cardiac muscle cells."))
    ws.write("specific-aims", "We study heart cells.", parent=None)
    call_id = ws.propose("specific-aims", "polish").call_id
    first = ws.accept(call_id, edited="We study cardiac cells.")
    assert ws.accept(call_id, edited="We study cardiac cells.") == ws.accept(call_id) == first and first.author == "applicant"
    with pytest.raises(StaleEdit):
        ws.accept(call_id, edited="Something else.")
    assert ws.view().section("specific-aims").text == "We study cardiac cells." and len(ws.view().log) == 3
    with pytest.raises(WorkspaceError, match="accepted"):
        ws.discard(call_id)
    assert "I edited the Specific Aims after I accepted model text." in ws.view().disclosure

def test_a_second_accept_after_the_section_changed_is_refused(tmp_path) -> None:
    ws = start(tmp_path, model=FakeModel("We study cardiac muscle cells."))
    mine = ws.write("specific-aims", "We study heart cells.", parent=None)
    call_id = ws.propose("specific-aims", "polish").call_id
    accepted = ws.accept(call_id)
    ws.restore("specific-aims", mine.id, accepted.id)
    with pytest.raises(WorkspaceError, match=f"accepted earlier as revision {accepted.id}, and the section has changed since"):
        ws.accept(call_id)
    assert ws.view().section("specific-aims").text == "We study heart cells." and len(ws.view().log) == 3

def test_a_workspace_mistake_is_a_workspace_error(tmp_path) -> None:
    ws = start(tmp_path)
    assert issubclass(WorkspaceError, ValueError)
    for mistake in (lambda: ws.write("budget", "x", parent=None), lambda: ws.accept(999), lambda: ws.discard(999), lambda: ws.add_fact("aims", "x")):
        with pytest.raises(WorkspaceError):
            mistake()

def test_the_export_holds_the_statement_only_while_it_is_on(tmp_path) -> None:
    ws = start(tmp_path)
    ws.write("project-narrative", "One. Two.", parent=None)
    statement = ws.export(tmp_path / "out") / "ai-use-statement.md"
    assert statement.read_text(encoding="utf-8") == ws.view().disclosure + "\n"
    ws.set_disclosure(False)
    ws.export(tmp_path / "out")
    assert not statement.exists()

def test_a_second_view_and_a_waiting_proposal_reuse_the_word_record(tmp_path, monkeypatch) -> None:
    from difflib import SequenceMatcher
    from nih_grant_matcher import provenance
    from nih_grant_matcher.store import OpportunityStore
    diffs = []
    class Counted(SequenceMatcher):
        def get_opcodes(self):
            diffs.append(1)
            return super().get_opcodes()
    monkeypatch.setattr(provenance, "SequenceMatcher", Counted)
    ws, words = start(tmp_path), [f"w{k}" for k in range(200)]
    store, app, parent = ws.store, ws.application_id, None
    for n in range(8):
        words[n * 7] = f"{tmp_path.name}-{n}"
        if n == 1:
            call = store.add_call(app, "research-strategy", "polish", "fake", "fake-1", "s", "p", " ".join(words), parent_id=parent)
            parent = store.add_revision(app, "research-strategy", parent, "model", "polish", " ".join(words), call.id).id
        else:
            parent = ws.write("research-strategy", " ".join(words), parent).id
        ws.view()
    # The page opens a new store and workspace on every rerun.
    again = Workspace(OpportunityStore(tmp_path / "g.sqlite3"), app)
    diffs.clear(); again.view()
    assert diffs == []
    store.add_call(app, "research-strategy", "polish", "fake", "fake-1", "s", "p", " ".join(words) + " more", parent_id=parent)
    diffs.clear(); assert again.pending("research-strategy") is not None
    assert len(diffs) == 1
    diffs.clear(); again.pending("research-strategy"); again.view()
    assert diffs == []
    parent = again.write("research-strategy", " ".join(words) + " saved", parent).id
    diffs.clear(); again.view()
    assert len(diffs) == 1
    again.restore("research-strategy", 3, parent)
    diffs.clear(); again.view()
    assert len(diffs) == 1

def test_a_model_share_that_rounds_to_zero_reads_less_than_1_percent_at_sign_off(tmp_path) -> None:
    ws, words = start(tmp_path), [f"w{k}" for k in range(300)]
    mine = ws.write("specific-aims", " ".join(words) + ".", None)
    words[0] = "polished"
    call = ws.store.add_call(ws.application_id, "specific-aims", "polish", "fake", "fake-1", "s", "p", " ".join(words) + ".", parent_id=mine.id)
    polished = ws.store.add_revision(ws.application_id, "specific-aims", mine.id, "model", "polish", " ".join(words) + ".", call.id)
    signed = ws.sign("specific-aims", "A. Applicant", polished.id)
    assert "0 percent of its words came from a model's draft or revision that I accepted, and less than 1 percent from a model's polish" in signed.attestation

def test_a_second_accept_with_edits_after_a_plain_accept_is_refused(tmp_path) -> None:
    ws = start(tmp_path, model=FakeModel("We study cardiac muscle cells."))
    ws.write("specific-aims", "We study heart cells.", parent=None)
    call_id = ws.propose("specific-aims", "polish").call_id
    first = ws.accept(call_id)
    assert ws.accept(call_id, edited="We study cardiac muscle cells.") == first
    with pytest.raises(StaleEdit):
        ws.accept(call_id, edited="We study our cardiac cells.")
    assert [r.text for r in ws.view().log] == ["We study heart cells.", "We study cardiac muscle cells."]

def test_the_exported_statement_names_a_suggestion_that_is_waiting(tmp_path) -> None:
    ws = start(tmp_path, model=FakeModel("We study cardiac muscle cells."))
    ws.write("specific-aims", "We study heart cells.", parent=None)
    ws.propose("specific-aims", "polish")
    statement = (ws.export(tmp_path / "out") / "ai-use-statement.md").read_text(encoding="utf-8")
    assert "A suggestion from fake-1 for the Specific Aims is waiting for my decision." in statement and "The Specific Aims was written without a model." in statement

def test_a_draft_is_refused_until_the_inputs_are_there_and_again_once_one_is_retired(tmp_path) -> None:
    ws = start(tmp_path, model=FakeModel("Aim 1.", "Aim 2."))
    with pytest.raises(NotReady):
        ws.propose("specific-aims", "draft")
    aim = ws.add_fact("aim", "Test whether drug X lowers pressure.")
    ws.add_fact("hypothesis", "Drug X lowers pressure.")
    assert ws.propose("specific-aims", "draft").text == "Aim 1."
    ws.retire_fact(aim.id)
    assert ws.view().section("specific-aims").gaps == ("aim",)
    with pytest.raises(NotReady, match="needs aim before"):
        ws.propose("specific-aims", "draft")

def test_an_accepted_draft_with_gaps_cannot_be_signed(tmp_path) -> None:
    ws = start(tmp_path, model=FakeModel("We enrolled 412 patients. [NEEDS INPUT: effect size]"), facts={"aim": "A pilot cohort.", "hypothesis": "It works."})
    ws.accept(ws.propose("specific-aims", "draft").call_id)
    codes = {f.code for f in ws.view().section("specific-aims").findings}
    assert {"placeholder", "number-not-in-inputs", "mostly-drafted"} <= codes
    with pytest.raises(NotReady):
        ws.sign("specific-aims", "A. Applicant", ws.view().section("specific-aims").revision_id)

def test_a_draft_goes_on_the_newest_revision_and_sends_only_the_inputs(tmp_path) -> None:
    ws = start(tmp_path, model=FakeModel("Aim 1.", "Aim 2."), facts={"aim": "Test drug X.", "hypothesis": "X lowers pressure.", "team": "TEAM-TEXT"})
    first = ws.propose("specific-aims", "draft")
    assert first.parent_id is None and "Test drug X." in ws.model.seen[0].user and "TEAM-TEXT" not in ws.model.seen[0].user
    mine = ws.write("specific-aims", "We test drug X.", parent=None)
    second = ws.propose("specific-aims", "draft")
    assert second.parent_id == mine.id and ws.pending("specific-aims").call_id == second.call_id and "We test drug X." not in ws.model.seen[1].user

def test_a_model_reads_sections_i_iv_and_v_and_each_item_names_its_call(tmp_path) -> None:
    ws = start(tmp_path, model=FakeModel(*READ_REPLIES))
    with pytest.raises(NotReady, match="Fetch the full announcement"):
        ws.extract_requirements()
    assert ws.model.seen == []
    ws.fetch_announcement(Guide(READ), Grants(""))
    found, dropped = ws.extract_requirements()
    calls = ws.store.calls(ws.application_id)
    assert [(c.purpose, c.section, c.parent_id) for c in calls] == [("extract", "", None)] * 3 and dropped == 1
    assert "Applicants must describe data sharing." in ws.model.seen[0].user and "Reviewers" not in ws.model.seen[0].user and "Section V" in ws.model.seen[2].user
    assert [(r.text, r.origin, r.call_id, r.confirmed) for r in found] == [("Describe data sharing.", "model", calls[0].id, None), ("State one hypothesis.", "model", calls[1].id, None), ("Rigor.", "model", calls[2].id, None)]
    assert list(found) == [r for r in ws.view().requirements if r.origin == "model"]
    assert "read the funding announcement's requirements" in ws.view().disclosure

def test_a_new_reading_keeps_a_decided_item_once_and_replaces_the_rest(tmp_path) -> None:
    ws = start(tmp_path, model=FakeModel(*READ_REPLIES, READ_I, "[]", "[]"))
    ws.fetch_announcement(Guide(READ), Grants(""))
    found, _ = ws.extract_requirements()
    ws.decide(found[0].id, True)
    again, dropped = ws.extract_requirements()
    assert [(r.text, r.confirmed, r.call_id) for r in again] == [("Describe data sharing.", True, found[0].call_id)] and dropped == 0

def test_a_draft_sends_a_model_requirement_only_once_the_applicant_confirms_it(tmp_path) -> None:
    undecided = json.dumps([item("must", "specific-aims", "Describe data sharing.", "Applicants must describe data sharing.")])
    ws = start(tmp_path, model=FakeModel(undecided, READ_REPLIES[1], "[]", "Aim 1."), facts={"aim": "Test drug X.", "hypothesis": "X lowers pressure."})
    ws.fetch_announcement(Guide(READ), Grants(""))
    found, _ = ws.extract_requirements()
    ws.decide(next(r.id for r in found if r.text == "State one hypothesis."), True)
    ws.propose("specific-aims", "draft")
    sent = ws.model.seen[-1].user
    assert "State one hypothesis. The announcement says: The Specific Aims must state one hypothesis." in sent and "data sharing" not in sent

def test_reading_needs_section_i_iv_or_v(tmp_path) -> None:
    ws = start(tmp_path, model=FakeModel("[]"))
    ws.fetch_announcement(Guide("A notice with no headings at all. " * 40), Grants(""))
    with pytest.raises(NotReady, match="none of Sections I, IV and V"):
        ws.extract_requirements()
    assert ws.model.seen == [] and ws.store.calls(ws.application_id) == []

def test_a_fetch_keeps_a_model_item_while_its_quote_is_in_the_text_and_names_a_dropped_decision(tmp_path) -> None:
    ws = start(tmp_path, model=FakeModel(*READ_REPLIES))
    ws.fetch_announcement(Guide(READ), Grants(""))
    found, _ = ws.extract_requirements()
    ws.decide(found[1].id, False)
    _, notes = ws.fetch_announcement(Guide(READ.replace("Applicants must describe data sharing.", "").replace("The Specific Aims must state one hypothesis.", "")), Grants(""))
    assert [r.text for r in ws.view().requirements if r.origin == "model"] == ["Rigor."]
    assert notes == ['Your decision on "State one hypothesis." was dropped, because the new text no longer has the sentence it came from.']

DRAFT_412 = "We enrolled 412 patients in the pilot cohort and it works."

def test_an_invented_number_stays_flagged_after_the_applicant_edits_the_draft_and_signs(tmp_path) -> None:
    facts = {"aim": "A pilot cohort.", "hypothesis": "It works."}
    flagged = lambda ws: "number-not-in-inputs" in {f.code for f in ws.view().section("specific-aims").findings}
    ws = start(tmp_path / "a", model=FakeModel(DRAFT_412), facts=facts)
    ws.accept(ws.propose("specific-aims", "draft").call_id)
    ws.write("specific-aims", DRAFT_412 + " Indeed.", ws.view().section("specific-aims").revision_id)
    assert flagged(ws)
    ws = start(tmp_path / "b", model=FakeModel(DRAFT_412), facts=facts)
    ws.accept(ws.propose("specific-aims", "draft").call_id, DRAFT_412.replace("it works", "it worked"))
    assert flagged(ws)
    assert "number-not-in-inputs" in ws.sign("specific-aims", "A. Applicant", ws.view().section("specific-aims").revision_id, True).findings

def test_a_number_the_applicant_wrote_before_a_model_touched_the_section_grounds_the_model(tmp_path) -> None:
    ws = start(tmp_path, model=FakeModel("We test (40) mice."))
    ws.write("specific-aims", "We test 40 mice.", parent=None)
    ws.accept(ws.propose("specific-aims", "polish").call_id)
    assert "number-not-in-inputs" not in {f.code for f in ws.view().section("specific-aims").findings}

def test_a_number_the_applicant_adds_after_a_draft_is_not_flagged(tmp_path) -> None:
    ws = start(tmp_path, model=FakeModel("We study a pilot cohort."), facts={"aim": "A pilot cohort.", "hypothesis": "It works."})
    accepted = ws.accept(ws.propose("specific-aims", "draft").call_id)
    ws.write("specific-aims", accepted.text + " We enrolled 30 patients.", accepted.id)
    assert "number-not-in-inputs" not in {f.code for f in ws.view().section("specific-aims").findings}

QUOTE = "The Specific Aims must state one hypothesis."

def test_a_new_reading_of_a_rejected_item_in_other_words_keeps_one_rejected_row(tmp_path) -> None:
    again = json.dumps([item("must", "specific-aims", "Aims state a single hypothesis.", QUOTE)])
    ws = start(tmp_path, model=FakeModel("[]", READ_REPLIES[1], "[]", "[]", again, "[]"))
    ws.fetch_announcement(Guide(READ), Grants(""))
    found, _ = ws.extract_requirements()
    ws.decide(found[0].id, False)
    again, _ = ws.extract_requirements()
    assert [(r.text, r.confirmed) for r in again] == [("State one hypothesis.", False)]

def test_one_reading_keeps_items_with_one_text_and_other_quotes_and_merges_items_with_one_quote(tmp_path) -> None:
    reply = json.dumps([item("must", "", "Same.", "Applicants must describe data sharing."), item("must", "", "Same.", "Reviewers will judge rigor."), item("must", "", "Other words.", "Reviewers will judge rigor.")])
    ws = start(tmp_path, model=FakeModel(reply, "[]", "[]"))
    ws.fetch_announcement(Guide(READ), Grants(""))
    found, dropped = ws.extract_requirements()
    assert [(r.text, r.quote) for r in found] == [("Same.", "Applicants must describe data sharing."), ("Same.", "Reviewers will judge rigor.")] and dropped == 0

def test_a_read_call_cannot_be_accepted_and_the_message_says_an_extract_call(tmp_path) -> None:
    ws = start(tmp_path, model=FakeModel("[]", "[]", "[]"))
    ws.fetch_announcement(Guide(READ), Grants(""))
    ws.extract_requirements()
    with pytest.raises(WorkspaceError, match="is an extract call"):
        ws.accept(ws.store.calls(ws.application_id)[0].id)

def test_the_no_section_iv_notice_holds_only_while_no_requirement_is_listed(tmp_path) -> None:
    text = "Section I. Notice of Funding Opportunity Description\nApplicants must describe data sharing.\nSection V. Application Review Information\nReviewers will judge rigor." + " More text." * 100
    ws = start(tmp_path, model=FakeModel(READ_I, "[]"))
    ws.fetch_announcement(Guide(text), Grants(""))
    assert ws.view().no_section_iv
    ws.extract_requirements()
    assert not ws.view().no_section_iv

def test_a_draft_accepted_over_the_applicants_text_is_all_the_models(tmp_path) -> None:
    mine = "Specific Aims\nHeart failure is a leading cause of death. The goal of the project is to study the role of the heart in the disease."
    drafted = "Specific Aims\nHeart failure is a major problem. The goal of the project is to test drug X in the mouse model of heart failure."
    ws = start(tmp_path, model=FakeModel(drafted), facts={"aim": "Test drug X in the mouse model of heart failure.", "hypothesis": "Drug X lowers pressure."})
    ws.write("specific-aims", mine, None)
    proposal = ws.propose("specific-aims", "draft")
    assert "mostly-drafted" in {f.code for f in proposal.findings}
    ws.accept(proposal.call_id)
    s = ws.view().section("specific-aims")
    assert s.attribution.written_share == 1.0 and "mostly-drafted" in {f.code for f in s.findings}

@pytest.mark.parametrize("reply", ["I'm sorry, I can't help with that.", READ_REPLIES[1][:-5]])
def test_a_reply_that_holds_no_list_fails_the_read_and_keeps_every_row(tmp_path, reply) -> None:
    ws = start(tmp_path, model=FakeModel(*READ_REPLIES, READ_I, reply))
    ws.fetch_announcement(Guide(READ), Grants(""))
    found, _ = ws.extract_requirements()
    ws.decide(found[0].id, True)
    with pytest.raises(ModelError, match="The reply for Section IV was not a list of requirements, so nothing was read. Nothing was changed"):
        ws.extract_requirements()
    assert [(r.text, r.confirmed) for r in ws.store.requirements(ws.application_id) if r.origin == "model"] == [(r.text, True if r.id == found[0].id else None) for r in found]
    assert [c.purpose for c in ws.store.calls(ws.application_id)] == ["extract"] * 5

def test_a_read_whose_later_call_fails_raises_and_keeps_every_row(tmp_path) -> None:
    ws = start(tmp_path, model=FakeModel(*READ_REPLIES, READ_I, ModelError("HTTP 500"), "[]"))
    ws.fetch_announcement(Guide(READ), Grants(""))
    found, _ = ws.extract_requirements()
    with pytest.raises(ModelError, match="HTTP 500"):
        ws.extract_requirements()
    assert tuple(r for r in ws.store.requirements(ws.application_id) if r.origin == "model") == found

def test_an_empty_list_from_each_section_leaves_only_the_decided_rows_and_says_so(tmp_path) -> None:
    ws = start(tmp_path, model=FakeModel(*READ_REPLIES, "[]", "[]", "[]"))
    ws.fetch_announcement(Guide(READ), Grants(""))
    found, _ = ws.extract_requirements()
    ws.decide(found[0].id, True)
    again, dropped = ws.extract_requirements()
    assert [(r.text, r.confirmed) for r in again] == [("Describe data sharing.", True)] and dropped == 0
    assert read_summary(again) == "The model read 0 requirements from the announcement that you have not decided. Your decision on 1 requirement read earlier still stands."

def test_a_failed_save_after_the_replies_says_the_text_was_sent_and_saves_nothing(tmp_path, monkeypatch) -> None:
    ws = start(tmp_path, model=FakeModel(*READ_REPLIES))
    ws.fetch_announcement(Guide(READ), Grants(""))
    def locked(*args, **kwargs): raise sqlite3.OperationalError("database is locked")
    monkeypatch.setattr(ws.store, "replace_requirements", locked)
    with pytest.raises(ModelError, match=r"sent to example\.test.*\(database is locked\)\. Nothing was saved, and asking again sends the text again\."):
        ws.extract_requirements()
    monkeypatch.undo()
    assert [c.purpose for c in ws.store.calls(ws.application_id)] == ["extract"] * 3 and not [r for r in ws.store.requirements(ws.application_id) if r.origin == "model"]


REVIEWED = json.dumps({"scores": {"importance": 3, "rigor": 4, "expertise": "appropriate"}, "points": []})

def test_the_reviewer_does_not_see_the_inputs(tmp_path) -> None:
    fake = FakeModel(json.dumps({"scores": {"importance": 3, "rigor": 4, "expertise": "appropriate"}, "points": []}))
    ws = start(tmp_path, model=fake, facts={"aim": "SECRET-AIM-TEXT", "hypothesis": "h"})
    ws.write("specific-aims", "Aim 1 is to test the drug.", parent=None)
    ws.review("specific-aims")
    assert "SECRET-AIM-TEXT" not in fake.seen[-1].user and "Rigor and Feasibility" in fake.seen[-1].user

def test_a_review_goes_stale_when_the_section_changes(tmp_path) -> None:
    ws = start(tmp_path, model=FakeModel(json.dumps({"scores": {"importance": 3, "rigor": 4, "expertise": "appropriate"}, "points": []})))
    first = ws.write("specific-aims", "Aim 1.", parent=None)
    ws.review("specific-aims")
    assert ws.view().section("specific-aims").review is not None
    ws.write("specific-aims", "Aim 1, revised.", parent=first.id)
    assert ws.view().section("specific-aims").review is None

def test_the_reviewer_sees_neither_the_profile_nor_a_writer_prompt_and_its_review_is_kept_with_its_call(tmp_path) -> None:
    point = {"factor": "importance", "kind": "strength", "text": "A clear aim.", "quote": "Aim 1 is to test the drug in mice."}
    fake = FakeModel("Aim 1 tests the drug in mice.", json.dumps({"scores": {"importance": 3, "rigor": 4, "expertise": "No team is named."}, "points": [point]}))
    ws = start(tmp_path, model=fake, profile=Profile(research_summary="SECRET-PROFILE-TEXT"))
    first = ws.write("specific-aims", "Aim 1 is to test the drug in mice.", parent=None)
    ws.propose("specific-aims", "polish")
    review = ws.review("specific-aims")
    seen = fake.seen[-1].system + fake.seen[-1].user
    assert "SECRET-PROFILE-TEXT" not in seen and "Change wording only" not in seen and "Aim 1 is to test the drug in mice." in fake.seen[-1].user
    call = ws.store.calls(ws.application_id)[-1]
    assert (call.purpose, call.parent_id) == ("review", first.id) and (review.revision_id, review.model, review.scores["expertise"], [p.text for p in review.points]) == (first.id, "fake-1", "No team is named.", ["A clear aim."])
    assert ws.view().section("specific-aims").review == review == ws.store.reviews(ws.application_id)[-1]

def test_a_section_with_no_text_is_not_sent_for_review(tmp_path) -> None:
    fake = FakeModel(REVIEWED)
    ws = start(tmp_path, model=fake)
    with pytest.raises(NotReady, match="no text"):
        ws.review("specific-aims")
    ws.write("specific-aims", "  ", parent=None)
    with pytest.raises(NotReady, match="no text"):
        ws.review("specific-aims")
    assert fake.seen == [] and ws.store.calls(ws.application_id) == []

def test_a_review_that_cannot_be_read_stays_in_the_log_and_saves_nothing(tmp_path) -> None:
    ws = start(tmp_path, model=FakeModel("I liked it."))
    first = ws.write("specific-aims", "Aim 1.", parent=None)
    with pytest.raises(ModelError, match="the call is in the log"):
        ws.review("specific-aims")
    assert [(c.purpose, c.parent_id) for c in ws.store.calls(ws.application_id)] == [("review", first.id)] and ws.store.reviews(ws.application_id) == []
    view = ws.view()
    assert view.section("specific-aims").review is None and "to review drafts against NIH's review criteria" in view.disclosure
