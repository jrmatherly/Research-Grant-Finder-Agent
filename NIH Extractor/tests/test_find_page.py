from nih_grant_matcher.ui.find_page import picked_option

OPTIONS = ["PAR-1 | One", "PAR-2 | Two", "PAR-3 | Three"]

def _cells(*cells):
    return {"selection": {"cells": list(cells), "rows": [], "columns": []}}

def test_a_clicked_cell_picks_the_option_of_its_row() -> None:
    assert picked_option(_cells((2, "Title")), OPTIONS) == "PAR-3 | Three"

def test_no_clicked_cell_picks_nothing() -> None:
    assert picked_option(_cells(), OPTIONS) is None
    assert picked_option(None, OPTIONS) is None
    assert picked_option({}, OPTIONS) is None

def test_a_cell_of_a_row_that_a_filter_removed_picks_nothing() -> None:
    assert picked_option(_cells((3, "Title")), OPTIONS) is None
    assert picked_option(_cells((0, "Title")), []) is None

def test_the_highlight_follows_the_row_that_details_shows() -> None:
    from nih_grant_matcher.ui.find_page import selection_for
    assert selection_for(None, OPTIONS, "PAR-2 | Two") == _cells((1, "Title"))
    assert selection_for(_cells((0, "Score")), OPTIONS, "PAR-3 | Three") == _cells((2, "Title"))

def test_a_highlight_already_on_that_row_is_left_alone() -> None:
    from nih_grant_matcher.ui.find_page import selection_for
    assert selection_for(_cells((1, "Score")), OPTIONS, "PAR-2 | Two") is None
    assert selection_for(None, [], None) is None

def test_a_choice_that_a_filter_removed_puts_the_highlight_on_the_first_row() -> None:
    from nih_grant_matcher.ui.find_page import selection_for
    assert selection_for(_cells((2, "Title")), OPTIONS[:2], "PAR-3 | Three") == _cells((0, "Title"))
    assert selection_for(_cells((2, "Title")), [], "PAR-3 | Three") == _cells()
