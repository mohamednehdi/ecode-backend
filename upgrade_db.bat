@echo off
REM Applies the database migrations (step 1: security fixes, step 2: scan_history.page for PDF, step 3: API tokens)
cd /d "%~dp0"
call venv\Scripts\activate.bat
echo Current database revision:
flask --app run db current
echo.
echo Upgrading...
flask --app run db upgrade
echo.
echo New database revision (should be c7e4f3b9a120):
flask --app run db current
echo.
pause
