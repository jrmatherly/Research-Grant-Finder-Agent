#!/bin/sh
# Double-click in Finder to start the dashboard. Close the Terminal window to stop it.
cd "$(dirname "$0")" || exit 1
exec uv run streamlit run streamlit_app.py --server.port 8501
