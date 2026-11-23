import pytest
from helpers import Grants, Guide, start
from nih_grant_matcher import __version__
from nih_grant_matcher.clients import ApiError
from nih_grant_matcher.profile import Profile, Reference
from nih_grant_matcher.writer import NotReady, StaleEdit, Workspace

FOUR_PAGES = "Section IV. Application and Submission Information\nThe Research Strategy is limited to 4 pages.\nSection V. Review\nx"

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
    assert signed.revision_id == fixed.id and "0 percent" in signed.attestation
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
