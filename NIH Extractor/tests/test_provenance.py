from datetime import datetime
from nih_grant_matcher.models import Revision, Signoff
from nih_grant_matcher.provenance import attribution, head, section_state, share

NOW = datetime(2026, 11, 23)
def _rev(id, parent, author, text, call=None) -> Revision:
    return Revision(id, "specific-aims", parent, author, "write" if author == "applicant" else "polish", text, call, NOW)

LOG = (_rev(1, None, "applicant", "We study heart cells."), _rev(2, 1, "model", "We study cardiac muscle cells.", call=7), _rev(3, 2, "applicant", "We study cardiac muscle cells in mice."))

def test_each_word_keeps_the_author_who_first_wrote_it() -> None:
    assert attribution(LOG, 3) == (("We", "applicant"), ("study", "applicant"), ("cardiac", "polish"), ("muscle", "polish"), ("cells", "applicant"), ("in", "applicant"), ("mice.", "applicant"))
    counted = share(attribution(LOG, 3))
    assert (counted.polished_words, counted.written_words, counted.model_words) == (2, 0, 2) and round(counted.polished_share, 2) == 0.29

def test_drafted_words_are_counted_apart_from_polished_words() -> None:
    log = (Revision(1, "specific-aims", None, "model", "draft", "Aim one tests the drug.", 5, NOW), Revision(2, "specific-aims", 1, "applicant", "write", "Aim one tests our drug.", None, NOW), Revision(3, "specific-aims", 2, "model", "polish", "Aim one evaluates our drug.", 6, NOW))
    counted = share(attribution(log, 3))
    assert (counted.written_words, counted.polished_words, counted.applicant_words) == (3, 1, 1) and counted.written_share == 0.6

def test_restoring_an_old_revision_restores_its_authors() -> None:
    restored = LOG + (_rev(4, 1, "applicant", "We study heart cells."),)
    assert {author for _, author in attribution(restored, 4)} == {"applicant"}

def test_a_section_is_final_only_while_a_signoff_names_its_head() -> None:
    signed = (Signoff("specific-aims", 2, "A. Applicant", "I wrote this.", (), "0.3.0", NOW),)
    assert section_state(LOG[:2], signed, "specific-aims") == "final"
    assert section_state(LOG, signed, "specific-aims") == "draft"
    assert section_state((), (), "specific-aims") == "empty" and head(LOG, "specific-aims").id == 3

def test_an_unknown_origin_is_refused() -> None:
    import pytest
    with pytest.raises(ValueError, match="edit"):
        share((("We", "applicant"), ("study", "edit")))

def test_a_parent_outside_the_log_is_named() -> None:
    import pytest
    with pytest.raises(ValueError, match="parent 1"):
        attribution(LOG[1:], 3)

def test_a_run_of_applicant_revisions_before_a_model_one_keeps_each_author() -> None:
    log = (_rev(1, None, "applicant", "We study heart cells."), _rev(2, 1, "applicant", "We study heart cells in mice."), _rev(3, 2, "model", "We study cardiac cells in mice.", call=7), _rev(4, 3, "applicant", "We study cardiac cells in old mice."))
    assert attribution(log, 4) == (("We", "applicant"), ("study", "applicant"), ("cardiac", "polish"), ("cells", "applicant"), ("in", "applicant"), ("old", "applicant"), ("mice.", "applicant"))

def test_a_long_chain_of_applicant_saves_is_read_quickly() -> None:
    import random, time
    rng = random.Random(7)
    vocabulary = [f"w{k}" for k in range(3000)]
    words = rng.choices(vocabulary, weights=[1 / (k + 1) for k in range(3000)], k=6000)
    log = []
    for n in range(1, 31):
        for at in rng.sample(range(len(words)), 20):
            words[at] = rng.choice(vocabulary)
        log.append(_rev(n, n - 1 or None, "applicant", " ".join(words)))
    began = time.perf_counter()
    found = attribution(log, 30)
    assert time.perf_counter() - began < 2 and len(found) == 6000 and {origin for _, origin in found} == {"applicant"}

def test_the_statement_has_a_sentence_for_each_thing_the_log_holds() -> None:
    from nih_grant_matcher.models import Application, Fact, ModelCall
    from nih_grant_matcher.provenance import disclosure_statement
    from nih_grant_matcher.rules import GRANT_TYPES
    def call(id, section, purpose, model="fake-1", parent=None):
        return ModelCall(id, section, purpose, "fake", model, "s", "p", "r", 1, 1, NOW, parent)
    app = Application(1, "PAR-1", "NIH:R21", "t", False, True, NOW)
    log = (*LOG, Revision(4, "project-narrative", None, "applicant", "write", "One.", None, NOW), Revision(5, "project-summary", None, "applicant", "write", "Two.", None, NOW), Revision(6, "research-strategy", None, "model", "revise", "Three words here.", 9, NOW))
    calls = (call(7, "specific-aims", "polish", parent=1), call(8, "", "extract"), call(9, "research-strategy", "revise", "other-2"), call(10, "", "review"), call(11, "specific-aims", "failed", parent=3), call(12, "specific-aims", "polish", parent=1))
    signed = (Signoff("project-narrative", 4, "A. Applicant", "a", (), "0.3.0", NOW), Signoff("specific-aims", 2, "A. Applicant", "a", (), "0.3.0", NOW))
    statement = disclosure_statement(app, GRANT_TYPES["NIH:R21"], log, calls, signed, (Fact(1, "hypothesis", "h"), Fact(2, "reference", "r"), Fact(3, "aim", "a")), ())
    assert statement.startswith("AI use in this application, from the record that Grant Matcher ") and statement.endswith("This record covers work done in Grant Matcher. It does not cover text that I wrote or edited elsewhere.")
    for sentence in ("I entered the aims, hypotheses and references of this application myself.", "I used fake-1 (fake) to polish the Specific Aims.", "I used other-2 (fake) to revise the Research Strategy.",
                     "I edited the Specific Aims after I accepted model text.", "By the tool's word-level record, 0 percent of the Specific Aims text came from a model's draft or revision that I accepted, and 29 percent from a model's polish of my own text.",
                     "100 percent of the Research Strategy text came from a model's draft or revision", "The Project Summary/Abstract and Project Narrative were written without a model.",
                     "I also sent text to fake-1 to read the funding announcement's requirements, review drafts against NIH's review criteria and produce suggestions that I did not use (2).", "I read and signed off the Project Narrative."):
        assert sentence in statement, sentence
    assert "No AI model" not in statement and "signed off the Specific Aims" not in statement

def test_a_statement_with_no_model_call_says_so_and_ends() -> None:
    from nih_grant_matcher.models import Application, Fact
    from nih_grant_matcher.provenance import disclosure_statement
    from nih_grant_matcher.rules import GRANT_TYPES
    statement = disclosure_statement(Application(1, "PAR-1", "NIH:R21", "t", False, True, NOW), GRANT_TYPES["NIH:R21"], LOG[:1], (), (), (Fact(1, "aim", "a"),), ())
    assert statement.split(". ", 1)[1] == "No AI model was used on this application in Grant Matcher. This record covers work done in Grant Matcher. It does not cover text that I wrote or edited elsewhere."

def test_a_proposal_still_waiting_is_not_counted() -> None:
    from nih_grant_matcher.models import Application, ModelCall
    from nih_grant_matcher.provenance import disclosure_statement
    from nih_grant_matcher.rules import GRANT_TYPES
    waiting = ModelCall(8, "specific-aims", "polish", "fake", "fake-1", "s", "p", "r", 1, 1, NOW, 1)
    statement = disclosure_statement(Application(1, "PAR-1", "NIH:R21", "t", False, True, NOW), GRANT_TYPES["NIH:R21"], LOG[:1], (waiting,), (), (), (8,))
    assert "No AI model" not in statement and "I also sent" not in statement and "The Specific Aims was written without a model." in statement

def test_a_share_above_zero_that_rounds_to_zero_reads_less_than_one_percent() -> None:
    from nih_grant_matcher.models import Application, ModelCall
    from nih_grant_matcher.provenance import disclosure_statement
    from nih_grant_matcher.rules import GRANT_TYPES
    words = [f"w{n}" for n in range(300)]
    log = (_rev(1, None, "applicant", " ".join(words)), _rev(2, 1, "model", " ".join(["polished", *words[1:]]), call=7))
    polish = ModelCall(7, "specific-aims", "polish", "fake", "fake-1", "s", "p", "r", 1, 1, NOW, 1)
    statement = disclosure_statement(Application(1, "PAR-1", "NIH:R21", "t", False, True, NOW), GRANT_TYPES["NIH:R21"], log, (polish,), (), (), ())
    assert "0 percent of the Specific Aims text came from a model's draft or revision that I accepted, and less than 1 percent from a model's polish of my own text." in statement

def test_a_section_restored_to_text_from_before_a_model_says_no_model_text_remains() -> None:
    from nih_grant_matcher.models import Application, ModelCall
    from nih_grant_matcher.provenance import disclosure_statement
    from nih_grant_matcher.rules import GRANT_TYPES
    log = (*LOG[:2], _rev(3, 1, "applicant", "We study heart cells."), Revision(4, "project-narrative", None, "applicant", "write", "One.", None, NOW))
    polish = ModelCall(7, "specific-aims", "polish", "fake", "fake-1", "s", "p", "r", 1, 1, NOW, 1)
    statement = disclosure_statement(Application(1, "PAR-1", "NIH:R21", "t", False, True, NOW), GRANT_TYPES["NIH:R21"], log, (polish,), (), (), ())
    assert "I used fake-1 (fake) to polish the Specific Aims." in statement and "No model text remains in the Specific Aims." in statement
    assert "The Project Narrative was written without a model." in statement and "Specific Aims was written without a model" not in statement
