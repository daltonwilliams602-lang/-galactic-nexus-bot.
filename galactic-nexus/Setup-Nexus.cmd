@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  py -3 -m venv .venv
  if errorlevel 1 goto python_failed
)
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto dependencies_failed
".venv\Scripts\python.exe" -m unittest discover -s tests -q
if errorlevel 1 goto tests_failed
echo Setup passed. Open Start-Nexus.cmd next.
pause
exit /b 0
:python_failed
echo Python environment setup failed. Check that Python 3.12 or newer and the Python launcher are installed.
goto failed
:dependencies_failed
echo Dependency installation failed. Check the message above and your internet connection.
goto failed
:tests_failed
echo A self-test failed. Python is installed; do not reinstall it because of this message.
echo Keep the error message so the code issue can be corrected before startup.
goto failed
:failed
pause
exit /b 1
