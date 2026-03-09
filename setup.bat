@echo off
REM setup.bat - AI-tinerary First-Time Setup Script for Windows (Modern GUI Edition)
REM This script sets up the Python virtual environment and installs dependencies.

setlocal enabledelayedexpansion
cd /d "%~dp0"
set PROJECT_DIR=%cd%
set VENV_DIR=%PROJECT_DIR%\.venv

echo.
echo ================================
echo AI-tinerary Setup for Windows
echo ================================
echo.

REM Check if Python 3 is installed
python --version >nul 2>&1
if errorlevel 1 (
    echo Error: Python 3 is not installed or not in PATH.
    echo Please install Python 3 from https://www.python.org/downloads/
    echo Make sure to check "Add python.exe to PATH" during installation.
    pause
    exit /b 1
)

for /f "tokens=2" %%i in ('python --version 2^>^&1') do set PYTHON_VERSION=%%i
echo [OK] Python %PYTHON_VERSION% found
echo.

REM Remove existing venv if present
if exist "%VENV_DIR%" (
    echo Removing existing virtual environment...
    rmdir /s /q "%VENV_DIR%"
)

REM Create virtual environment
echo Creating virtual environment...
python -m venv "%VENV_DIR%"
if errorlevel 1 (
    echo Error: Failed to create virtual environment.
    pause
    exit /b 1
)
echo [OK] Virtual environment created at .venv
echo.

REM Activate virtual environment
echo Activating virtual environment...
call "%VENV_DIR%\Scripts\activate.bat"
if errorlevel 1 (
    echo Error: Failed to activate virtual environment.
    pause
    exit /b 1
)
echo [OK] Virtual environment activated
echo.

REM Check for Dependencies.txt
if not exist "%PROJECT_DIR%\Dependencies.txt" (
    echo Error: Dependencies.txt not found in %PROJECT_DIR%
    pause
    exit /b 1
)

REM Install dependencies
echo Installing dependencies from Dependencies.txt...
pip install --upgrade pip >nul 2>&1
pip install -r "%PROJECT_DIR%\Dependencies.txt"
if errorlevel 1 (
    echo Error: Failed to install dependencies.
    pause
    exit /b 1
)
echo [OK] Dependencies installed
echo.

REM Create required directories
echo Creating project directories...
if not exist "%PROJECT_DIR%\Contracts\Incoming" mkdir "%PROJECT_DIR%\Contracts\Incoming"
if not exist "%PROJECT_DIR%\Contracts\Complete" mkdir "%PROJECT_DIR%\Contracts\Complete"
if not exist "%PROJECT_DIR%\Outputs\Bits" mkdir "%PROJECT_DIR%\Outputs\Bits"
if not exist "%PROJECT_DIR%\Outputs\Backups" mkdir "%PROJECT_DIR%\Outputs\Backups"
if not exist "%PROJECT_DIR%\Outputs\Processed" mkdir "%PROJECT_DIR%\Outputs\Processed"
if not exist "%PROJECT_DIR%\Outputs\Itineraries" mkdir "%PROJECT_DIR%\Outputs\Itineraries"
if not exist "%PROJECT_DIR%\Logs" mkdir "%PROJECT_DIR%\Logs"
if not exist "%PROJECT_DIR%\Configs" mkdir "%PROJECT_DIR%\Configs"
if not exist "%PROJECT_DIR%\Keys" mkdir "%PROJECT_DIR%\Keys"
echo [OK] Directories created
echo.

REM Create Default config in Configs if it doesn't exist
if not exist "%PROJECT_DIR%\Configs\Default" (
    echo Creating Default configuration in Configs\...
    if exist "%PROJECT_DIR%\Master Config.txt" (
        copy "%PROJECT_DIR%\Master Config.txt" "%PROJECT_DIR%\Configs\Default" >nul
    ) else (
        (
            echo # AI-tinerary Default Configuration Profile
            echo HOME_BASE_ADDRESS=
            echo ORS_API_KEY=
            echo ORS_BASE_URL=
            echo OLLAMA_URL=http://localhost:11434/api/generate
            echo OLLAMA_MODEL=ministral-3:3b
            echo MAX_THREADS=4
            echo TIMEZONE=America/New_York
            echo DISCORD_BOT_TOKEN=
            echo DISCORD_CHANNEL_ID=
            echo GOOGLE_SERVICE_ACCOUNT_FILE=
            echo BAND_CALENDAR_ID=
            echo PUBLIC_CALENDAR_ID=
        ) > "%PROJECT_DIR%\Configs\Default"
    )
    echo [OK] Default config created
) else (
    echo [OK] Default config already exists
)
echo.

REM Create Master Config.txt if it doesn't exist
if not exist "%PROJECT_DIR%\Master Config.txt" (
    echo Creating Master Config.txt file (template)...
    (
        echo # AI-tinerary Master Configuration
        echo # Edit this file to control the Python scripts.  It uses dotenv format.
        echo.
        echo # Home Base Address (where the band departs from^)
        echo HOME_BASE_ADDRESS=
        echo.
        echo # OpenRouteService configuration (optional^)
        echo #   ORS_API_KEY=public key from https://openrouteservice.org/
        echo #   ORS_BASE_URL=http://localhost:8080/ors
        echo ORS_API_KEY=
        echo ORS_BASE_URL=
        echo.
        echo # Ollama Settings
        echo OLLAMA_URL=http://localhost:11434/api/generate
        echo OLLAMA_MODEL=ministral-3:3b
        echo.
        echo # Processing
        echo MAX_THREADS=4
        echo.
        echo # Default Timezone for Calendar events (e.g. America/New_York^)
        echo TIMEZONE=America/New_York
        echo.
        echo # Discord Bot (optional^)
        echo # Generate a bot application and paste the token here.
        echo DISCORD_BOT_TOKEN=
        echo DISCORD_CHANNEL_ID=
        echo.
        echo # Google Calendar configuration
        echo # Provide the path to your service account JSON and the calendar IDs
        echo GOOGLE_SERVICE_ACCOUNT_FILE=
        echo BAND_CALENDAR_ID=
        echo PUBLIC_CALENDAR_ID=
    ) > "%PROJECT_DIR%\Master Config.txt"
    echo [OK] Master Config.txt template created (edit with your settings^)
) else (
    echo [OK] Master Config.txt already exists
)
echo.

echo ================================
echo Setup Complete!
echo ================================
echo.
echo Next steps:
echo 1. Edit Master Config.txt with your configuration:
echo    - Set OLLAMA_URL and OLLAMA_MODEL
echo    - Set HOME_BASE_ADDRESS
echo    - Set ORS_API_KEY or ORS_BASE_URL (optional, for routing^)
echo.
echo 2. Make sure Ollama is running:
echo    ollama serve
echo.
echo 3. To activate the environment in the future:
echo    .venv\Scripts\activate
echo.
echo 4. Run the scripts:
echo    python AI-tinerary-CSV.py    # To process contracts
echo    python AI-tinerary-CALBOT.py # To start the Discord bot
echo.
echo For more info, see README.md
echo.
pause
