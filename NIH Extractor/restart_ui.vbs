Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
appDir = fso.GetParentFolderName(WScript.ScriptFullName)
shell.CurrentDirectory = appDir
shell.Run "powershell -NoProfile -ExecutionPolicy Bypass -Command ""Get-NetTCPConnection -LocalPort 8501 -State Listen -ErrorAction SilentlyContinue | ForEach-Object { Get-Process -Id $_.OwningProcess } | Where-Object { $_.ProcessName -like 'python*' } | Stop-Process -Force""", 0, True
shell.Run "cmd /c uv run streamlit run streamlit_app.py --server.port 8501", 0, False
WScript.Sleep 3000
shell.Run "http://localhost:8501", 1, False
