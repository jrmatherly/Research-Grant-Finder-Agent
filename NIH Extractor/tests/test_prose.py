from nih_grant_matcher.prose import PROSE_RULES, scan

def test_each_patterned_rule_fires_on_its_own_example() -> None:
    examples = {3: "We ran the assay, highlighting its range.", 7: "This is a pivotal step.", 8: "The assay serves as a control.", 9: "This is not just a screen, but a test.", 13: "The result — a surprise — held.", 14: "The aim is clear: we will test it.", 19: "The “new” assay held.", 20: "I hope this helps!", 23: "In order to test this, we ran it.", 24: "This may possibly work.", 31: "We will utilize the cohort."}
    for number, text in examples.items():
        assert f"prose-{number}" in {finding.code for finding in scan(text)}, number

def test_plain_prose_passes() -> None:
    assert scan("We will test whether the drug lowers blood pressure in mice.") == ()

def test_every_rule_has_a_hint_and_the_numbers_are_unique() -> None:
    assert all(rule.hint for rule in PROSE_RULES) and len({rule.number for rule in PROSE_RULES}) == len(PROSE_RULES)
    assert {rule.number for rule in PROSE_RULES if rule.pattern is None} >= {5, 10, 25, 29}

def test_a_finding_is_a_warning_that_shows_the_text_it_found() -> None:
    (finding,) = scan("The aim is clear: we will test it.")
    assert (finding.code, finding.severity, finding.excerpt) == ("prose-14", "warning", "clear: we")

def test_a_colon_after_a_heading_or_in_a_time_or_a_ratio_is_not_a_joined_clause() -> None:
    for text in ("Significance:\nwe will test it.", "The dose is [NEEDS INPUT: dose in mg].","A. Approach: we will test it.", "The session starts at 10:30 and ends at noon.", "We mixed the cells 1:2 with controls."):
        assert "prose-14" not in {finding.code for finding in scan(text)}, text

def test_only_the_em_dash_and_curly_quotes_are_flagged() -> None:
    assert scan("The range was 10–20 mice in a well-known strain.") == ()
    assert scan('The "new" assay held.') == ()

def test_the_hints_pass_their_own_rules() -> None:
    assert [rule.number for rule in PROSE_RULES if scan(rule.hint)] == []
