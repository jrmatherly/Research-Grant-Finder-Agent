@echo off
cd /d "%~dp0"
uv run streamlit run streamlit_app.py --server.port 8501
pause
