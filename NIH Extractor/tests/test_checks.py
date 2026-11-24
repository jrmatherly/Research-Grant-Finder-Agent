from time import perf_counter
import pytest
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

GOLDSMITH = Fact(2, "reference", "Goldsmith A. Heart cells in mice. 2021. doi:10.1000/xyz PMID 41234567", label="goldsmith2021")
STORED = Fact(3, "reference", "Lee K. A study.", label="lee", detail={"pmid": "998877", "doi": "10.5555/abc"})

def _model_cited(text: str) -> bool:
    words = tuple((word, "draft") for word in text.split())
    return any(f.code == "unknown-citation" for f in check_section(text, RULE["specific-aims"], Limit(1, "pages"), R21.page, (GOLDSMITH, STORED), "", words))

def test_a_model_wrote_citation_is_known_only_when_it_matches_a_reference_exactly() -> None:
    for made_up in ("Smith et al. 2021 held.", "Gold et al. (2021) held.", "PMID: 123 held.", "PMID: 2 held.", "See 10.1000/xy for it.", "Goldsmith et al. 2020 held."):
        assert _model_cited(made_up), made_up
    for known in ("Goldsmith et al. (2021) held.", "PMID 41234567 held.", "See 10.1000/xyz.", "PMID: 998877 held.", "See 10.5555/ABC for it."):
        assert not _model_cited(known), known

@pytest.mark.parametrize("text, seconds", [(" ".join(f"PMID: {n}" for n in range(4000)), 1), ("-".join(["Ab"] * 7000), 0.1)])
def test_a_section_full_of_model_citations_checks_quickly(text, seconds) -> None:
    started = perf_counter()
    check_section(text, RULE["specific-aims"], Limit(1, "pages"), R21.page, (GOLDSMITH,), "", tuple((word, "draft") for word in text.split()))
    assert perf_counter() - started < seconds

def test_a_roman_numeral_is_not_the_first_person() -> None:
    for text in ("The Phase I trial ends.", "Patients with type I diabetes enrol.", "MHC class I binds.", "Aim I tests the dose."):
        assert "first-person" not in _codes(text, key="project-summary"), text
    assert "first-person" in _codes("Then I will test it.", key="project-summary")

def test_the_mostly_drafted_message_is_two_sentences() -> None:
    (finding,) = [f for f in check_section("one two", RULE["specific-aims"], Limit(1, "pages"), R21.page, (), "", (("one", "draft"), ("two", "draft"))) if f.code == "mostly-drafted"]
    assert estimate(finding.message, "sentences", R21.page) == 2
    assert all(part in finding.message for part in ("NOT-OD-25-132", "not NIH's", "AI detector", "polished"))

def _known_to(reference: Fact, text: str) -> bool:
    words = tuple((word, "draft") for word in text.split())
    return not any(f.code == "unknown-citation" for f in check_section(text, RULE["specific-aims"], Limit(1, "pages"), R21.page, (reference,), "", words))

def test_a_real_citation_is_known_in_the_forms_an_applicant_stores_it() -> None:
    mcdonald = Fact(4, "reference", "McDonald M. 2021.", label="mcdonald")
    assert _known_to(mcdonald, "McDonald et al. 2021 held.") and _known_to(Fact(5, "reference", "DiMaggio J. 2019."), "DiMaggio et al. (2019) held.")
    assert not _known_to(mcdonald, "Donald et al. 2021 held.") and not _known_to(GOLDSMITH, "Smith et al. 2021 held.")
    for doi in ("https://doi.org/10.1000/xyz", "doi:10.1000/xyz"):
        assert _known_to(Fact(6, "reference", "Lee K.", detail={"doi": doi}), "See 10.1000/xyz for it.")
    for pmid in (" 41234567 ", "PMID: 41234567"):
        assert _known_to(Fact(7, "reference", "Lee K.", detail={"pmid": pmid}), "PMID: 41234567 held.")
    assert _known_to(Fact(8, "reference", "Lee K. pmid: 41234567"), "PMID: 41234567 held.") and _known_to(GOLDSMITH, "pmid 41234567 held.")
    assert not _known_to(GOLDSMITH, "pmid 123 held.")
    suffixed = Fact(9, "reference", "Goldsmith A. 2021a.")
    assert _known_to(suffixed, "Goldsmith et al. (2021a) held.") and _known_to(suffixed, "Goldsmith et al. 2021 held.")
    assert not _known_to(GOLDSMITH, "Goldsmith et al. (2021b) held.") and not _known_to(suffixed, "Goldsmith et al. (2021b) held.")

NARRATIVE = (RULE["project-narrative"], Limit(3, "sentences"))

@pytest.mark.parametrize("text, low, code", [
    ("Led by Prof. Smith we work. Two. Three.", 3, None), ("Work at St. Jude helps. Two. Three.", 3, None), ("Mr. Lee, Mrs. Lee, Ms. Ray, Jr. and Sr. staff at Mt. Sinai, Acme Inc. and lab No. 4 agree. Two. Three.", 3, None),
    ("We study hepatitis B. We test mice. We treat them. We count them.", 3, "sentence-count-unsure"), ("We use group A. Then we test. Two. Three.", 3, "sentence-count-unsure"),
    ('He said "stop." Then we left. Two. Three.', 3, "sentence-count-unsure"), ("We test it (in mice.) Then we stop. Two. Three.", 3, "sentence-count-unsure"),
    ("One. p53 is two. mTOR is three. 5 mice is four.", 1, "sentence-count-unsure"), ("One. Two. Three. Four.", 4, "over-limit")])
def test_the_sentence_count_reads_titles_initials_quotes_and_lower_case_starts(text, low, code) -> None:
    found = {f.code: f for f in check_section(text, *NARRATIVE, R21.page, (), "", tuple((w, "applicant") for w in text.split()))}
    assert estimate(text, "sentences", R21.page) == low
    assert {"over-limit", "sentence-count-unsure"} & set(found) == ({code} if code else set())
    if code:
        assert found[code].severity == ("error" if code == "over-limit" else "warning")

def test_an_unsure_sentence_count_gives_both_counts_and_says_to_count_by_hand() -> None:
    (finding,) = [f for f in check_section("One. p53 is two. mTOR is three. 5 mice is four.", *NARRATIVE, R21.page, (), "", ()) if f.code == "sentence-count-unsure"]
    assert all(part in finding.message for part in ("counts 1 sentence one way and 4 another", "abbreviation", "by hand")) and scan(finding.message) == ()

def test_a_citation_names_your_inputs() -> None:
    found = check_section("Aim [NEEDS INPUT: dose] as shown [@jones2020].", RULE["specific-aims"], Limit(1, "pages"), R21.page, (), "", ())
    assert all("fact" not in f.message and ("input" in f.message) for f in found if f.code in ("unknown-citation", "placeholder"))

def test_a_figure_line_in_the_research_strategy_is_allowed() -> None:
    assert "figure-not-allowed" not in _codes("Significance\nHeart cells fail.\nFigure 1. Heart cells in failure.", "research-strategy")
    assert "figure-not-allowed" in _codes("Aim 1.\nFigure 1. Heart cells in failure.")

def test_a_model_citation_in_the_other_author_year_forms_must_match_a_reference() -> None:
    for made_up in ("As Smith and Jones (2020) held.", "This held (Smith, 2020).", "As Müller et al. (2021) held.", "This held (Łukasiewicz, 2021).", "As Peña and Smith (2021) held."):
        assert _model_cited(made_up), made_up
    for known in ("As Goldsmith and Jones (2021) held.", "This held (Goldsmith, 2021).", "Boston, 2021 held.", "As Smith and Jones held in 2021."):
        assert not _model_cited(known), known
    muller = Fact(9, "reference", "Müller K. Heart cells. 2021.", label="muller2021")
    words = tuple((word, "polish") for word in "As Müller et al. (2021) held.".split())
    assert not [f for f in check_section("As Müller et al. (2021) held.", RULE["specific-aims"], Limit(1, "pages"), R21.page, (muller,), "", words) if f.code == "unknown-citation"]

@pytest.mark.parametrize("placeholder", ["[NEEDS INPUT: effect size]", "[needs input: effect size]", "[NEEDS INPUT]", "[NEEDS INPUT - effect size]", "[NEEDS INPUT : x]", "[ NEEDS INPUT ]"])
def test_a_placeholder_in_any_case_or_form_is_an_error(placeholder) -> None:
    found = check_section(f"Aim 1 tests {placeholder} today.", RULE["specific-aims"], Limit(1, "pages"), R21.page, (), "", ())
    assert [f.excerpt for f in found if f.code == "placeholder" and f.severity == "error"] == [placeholder]


def _found(title: str) -> dict:
    return {"lookup": {"service": "PubMed", "id": "PMID 123", "on": "2026-11-23", "title": title}}


@pytest.mark.parametrize("reference,said", [
    (Fact(1, "reference", "Smith J. Heart cells. 2021. PMID: 123", label="smith2021"), "not yet checked"),
    (Fact(1, "reference", "Smith J. Heart cells. 2021.", label="smith2021"), "no PMID or DOI"),
    (Fact(1, "reference", "Smith J. Heart cells. 2021.", label="smith2021", detail={"pmid": "123", **_found("")}), "PubMed has no record of PMID 123"),
], ids=["unchecked", "no-identifier", "not-found"])
def test_a_cited_reference_that_was_not_found_is_a_warning(reference, said) -> None:
    found = [f for f in check_section("As shown [@smith2021].", RULE["specific-aims"], Limit(1, "pages"), R21.page, (reference,), "", ()) if f.code == "unverified-reference"]
    assert [(f.severity, f.excerpt) for f in found] == [("warning", "[@smith2021]")] and said in found[0].message


def test_a_found_or_uncited_reference_raises_no_unverified_warning() -> None:
    found = Fact(1, "reference", "Smith J. Heart cells. 2021.", label="smith2021", detail={"pmid": "123", **_found("Heart cells.")})
    assert "unverified-reference" not in _codes("As shown [@smith2021].", facts=(found,))
    assert "unverified-reference" not in _codes("As shown before.", facts=(REFERENCE,))
