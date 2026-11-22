@echo off
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-NetTCPConnection -LocalPort 8501 -State Listen -ErrorAction SilentlyContinue | ForEach-Object { Get-Process -Id $_.OwningProcess } | Where-Object { $_.ProcessName -like 'python*' } | Stop-Process -Force"
uv run streamlit run streamlit_app.py --server.port 8501
pause
