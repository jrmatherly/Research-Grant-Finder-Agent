from pathlib import Path


def test_streamlit_app_avoids_session_state_items_attribute() -> None:
    app_text = Path("streamlit_app.py").read_text(encoding="utf-8")

    assert "st.session_state.items" not in app_text
    assert 'st.session_state["scored_items"]' in app_text


def test_streamlit_app_guards_against_callable_session_value() -> None:
    app_text = Path("streamlit_app.py").read_text(encoding="utf-8")

    assert "def get_scored_items_from_session" in app_text
    assert "callable(value)" in app_text
    assert 'del st.session_state["items"]' in app_text


def test_streamlit_score_bins_use_string_labels() -> None:
    app_text = Path("streamlit_app.py").read_text(encoding="utf-8")

    assert 'score_labels = ["0-25", "25-35", "35-70", "70-100"]' in app_text
    assert "bins=[0, 25, 35, 70, 100]," in app_text
    assert "labels=score_labels" in app_text


def test_streamlit_app_reads_500_rows_by_default_and_warns_at_the_limit() -> None:
    app_text = Path("streamlit_app.py").read_text(encoding="utf-8")

    assert 'limit = st.slider("Rows per source", min_value=25, max_value=1000, value=500, step=25)' in app_text
    assert "if summary.capped:" in app_text
