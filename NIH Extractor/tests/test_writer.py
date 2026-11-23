from pathlib import Path
import pytest
from helpers import Grants, Guide, start
from nih_grant_matcher import __version__
from nih_grant_matcher.clients import ApiError
from nih_grant_matcher.profile import Profile, Reference
from nih_grant_matcher.writer import NotReady, StaleEdit, Workspace

FOUR_PAGES = "Section IV. Application and Submission Information\nThe Research Strategy is limited to 4 pages.\nSection V. Review\nx" + " More text." * 100
GRANTS_PAGE = "<p>Section IV. Application and Submission Information</p><p>The Research Strategy is limited to 4 pages, as in (NOT-OD-26-001).</p>" + "<p>Follow the guide.</p>" * 80

class GuideDown:
    def doctext(self, number): raise ApiError("timed out")

class GrantsDown:
    def full_announcement(self, opportunity_id): raise ApiError("HTTP 503")

DROPPED_FOUR = 'Your decision on "Research Strategy: at most 4 pages." was dropped, because the new text no longer has the sentence it came from.'
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

def test_a_confirmed_announcement_limit_replaces_the_standing_one(tmp_path) -> None:
    ws = start(tmp_path)
    ws.fetch_announcement(Guide(FOUR_PAGES), Grants(""))
    requirement = next(r for r in ws.view().requirements if r.kind == "limit")
    assert ws.view().section("research-strategy").limit.amount == 6
    ws.decide(requirement.id, True)
    assert ws.view().section("research-strategy").limit.amount == 4

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
    ws.write("specific-aims", "Aim 1, changed.", parent=first.id)
    restored = ws.restore("specific-aims", first.id)
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
