@echo off
REM setup.bat - AI-tinerary First-Time Setup Script for Windows
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
if not exist "%PROJECT_DIR%\Outputs" mkdir "%PROJECT_DIR%\Outputs"
echo [OK] Directories created
echo.

REM Create .env if it doesn't exist
if not exist "%PROJECT_DIR%\.env" (
    echo Creating .env file (template)...
    (
        echo # AI-tinerary Environment Configuration
        echo.
        echo # Ollama Settings
        echo OLLAMA_URL=http://localhost:11434/api/generate
        echo OLLAMA_MODEL=ministral-3:3b
        echo.
        echo # Home Base Address (where the band departs from^)
        echo HOME_BASE_ADDRESS=Johnson City, TN, United States
        echo.
        echo # OpenRouteService API Key (get one at https://openrouteservice.org/^)
        echo ORS_API_KEY=your_api_key_here
        echo.
        echo # Processing
        echo MAX_THREADS=4
    ) > "%PROJECT_DIR%\.env"
    echo [OK] .env template created (edit with your settings^)
) else (
    echo [OK] .env file already exists
)
echo.

echo ================================
echo Setup Complete!
echo ================================
echo.
echo Next steps:
echo 1. Edit .env with your configuration:
echo    - Set OLLAMA_URL and OLLAMA_MODEL
echo    - Set HOME_BASE_ADDRESS
echo    - Set ORS_API_KEY (optional, for routing^)
echo.
echo 2. Make sure Ollama is running:
echo    ollama serve
echo.
echo 3. To activate the environment in the future:
echo    .venv\Scripts\activate
echo.
echo 4. Run the script:
echo    python AI-tinerary
echo.
echo For more info, see README.md
echo.
pause
