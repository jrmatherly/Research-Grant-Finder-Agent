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
