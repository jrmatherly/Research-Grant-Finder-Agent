from nih_grant_matcher.checks import check_section, estimate
from nih_grant_matcher.models import Fact
from nih_grant_matcher.prose import scan
from nih_grant_matcher.rules import GRANT_TYPES, Limit

R21 = GRANT_TYPES["NIH:R21"]
RULE = {section.key: section for section in R21.sections}
REFERENCE = Fact(1, "reference", "Smith J. Heart cells. 2021.", label="smith2021")

def _codes(text, key="specific-aims", facts=(), grounding="", words=None, limit=None) -> set[str]:
    words = words if words is not None else tuple((word, "applicant") for word in text.split())
    return {f.code for f in check_section(text, RULE[key], limit or RULE[key].limit, R21.page, facts, grounding, words)}

def test_a_placeholder_and_an_unknown_citation_are_errors() -> None:
    found = check_section("Aim 1 [NEEDS INPUT: effect size] as shown [@jones2020] and [@smith2021].", RULE["specific-aims"], Limit(1, "pages"), R21.page, (REFERENCE,), "", ())
    assert {(f.code, f.severity) for f in found} >= {("placeholder", "error"), ("unknown-citation", "error")}
    assert sum(f.code == "unknown-citation" for f in found) == 1

def test_the_narrative_is_at_most_three_sentences() -> None:
    assert "over-limit" in _codes("One. Two. Three. Four.", key="project-narrative")
    assert "over-limit" not in _codes("One. Two. Three.", key="project-narrative")

def test_a_page_estimate_warns_and_never_blocks() -> None:
    long = "word " * 2000
    found = [f for f in check_section(long, RULE["specific-aims"], Limit(1, "pages"), R21.page, (), "", ()) if f.code == "over-limit"]
    assert found[0].severity == "warning" and "estimate" in found[0].message and estimate(long, "pages", R21.page) > 1

def test_research_strategy_needs_its_three_headings() -> None:
    assert "missing-part" in _codes("Significance\nx\nApproach\ny", key="research-strategy")

def test_a_number_only_a_model_wrote_is_flagged() -> None:
    text = "We enrolled 412 patients."
    model = tuple((word, "draft") for word in text.split())
    assert "number-not-in-inputs" in _codes(text, words=model, grounding="A pilot cohort.")
    assert "number-not-in-inputs" not in _codes(text, words=model, grounding="We enrolled 412 patients in the pilot.")
    assert "number-not-in-inputs" not in _codes(text, grounding="A pilot cohort.")
    assert "number-not-in-inputs" not in _codes("As shown [@smith2021].", words=(("As", "draft"), ("shown", "draft"), ("[@smith2021].", "draft")), facts=(REFERENCE,))

def test_a_section_that_a_model_mostly_drafted_gets_the_warning_and_a_polished_one_does_not() -> None:
    text = "one two three four"
    mostly = lambda origin: _codes(text, words=(("one", "applicant"),) + tuple((w, origin) for w in text.split()[1:]))
    assert "mostly-drafted" in mostly("draft") and "mostly-drafted" in mostly("revise") and "mostly-drafted" not in mostly("polish")

def test_the_abstract_flags_the_first_person_and_a_url() -> None:
    assert {"first-person", "url"} <= _codes("We will test this. See https://example.org.", key="project-summary")

def test_a_labelled_heading_on_its_own_line_counts_as_present() -> None:
    assert "missing-part" not in _codes("A. Significance\nx\nB) innovation:\ny\n3. APPROACH\nz", key="research-strategy")
    assert "missing-part" in _codes("Significance of the work\nInnovation\nApproach", key="research-strategy")

def test_an_abbreviation_does_not_end_a_sentence() -> None:
    assert estimate("We used e.g. mice. Dr. Smith et al. agreed with J. Doe. The U.S. sample held", "sentences", R21.page) == 3

def test_a_citation_a_model_wrote_must_match_a_reference() -> None:
    text = "As Smith et al., 2021 and Jones et al. (2020) showed, PMID: 123 held."
    model = tuple((word, "draft") for word in text.split())
    found = check_section(text, RULE["specific-aims"], Limit(1, "pages"), R21.page, (REFERENCE,), "2021 2020 123", model)
    assert sorted(f.excerpt for f in found if f.code == "unknown-citation") == ["Jones et al. (2020)", "PMID: 123"]
    assert "unknown-citation" not in _codes(text, facts=(REFERENCE,))

def test_a_retired_reference_no_longer_backs_a_citation() -> None:
    from datetime import datetime, timezone
    retired = Fact(1, "reference", "Smith J. Heart cells. 2021.", label="smith2021", retired_at=datetime(2026, 11, 1, tzinfo=timezone.utc))
    assert "unknown-citation" in _codes("As shown [@smith2021].", facts=(retired,))

def test_an_estimate_above_ninety_percent_warns_that_it_is_near_the_limit() -> None:
    codes = _codes("A short line.\n" * 55)
    assert "near-limit" in codes and "over-limit" not in codes

def test_every_finding_has_a_plain_message_and_errors_come_first() -> None:
    summary = "We will test this [NEEDS INPUT: dose] [@jones2020] at https://example.org.\n![plot](a.png)\n" + "Another line of the abstract.\n" * 30
    summary += "Jones et al. 2019 found 412 cells. The aim is clear: we test it."
    model = tuple((word, "draft") for word in summary.split())
    found = check_section(summary, RULE["project-summary"], RULE["project-summary"].limit, R21.page, (), "", model)
    found += check_section("Significance", RULE["research-strategy"], RULE["research-strategy"].limit, R21.page, (), "", ())
    found += check_section("One. Two. Three. Four.", RULE["project-narrative"], RULE["project-narrative"].limit, R21.page, (), "", ())
    found += check_section("A line.\n" * 55, RULE["specific-aims"], RULE["specific-aims"].limit, R21.page, (), "", ())
    assert {f.code for f in found} >= {"placeholder", "missing-part", "figure-not-allowed", "unknown-citation", "over-limit", "near-limit", "url", "first-person", "number-not-in-inputs", "mostly-drafted", "prose-14"}
    assert [(f.code, f.message) for f in found if scan(f.message)] == []
    first = check_section(summary, RULE["project-summary"], RULE["project-summary"].limit, R21.page, (), "", model)
    assert [f.severity for f in first] == sorted((f.severity for f in first), key=lambda s: s != "error")
