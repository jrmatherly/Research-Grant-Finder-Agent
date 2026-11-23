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
