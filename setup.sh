#!/bin/bash
# setup.sh - AI-tinerary First-Time Setup Script (Modern GUI Edition)
# This script sets up the Python virtual environment and installs dependencies.
# Works on macOS and Linux.

set -e  # Exit on any error

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$PROJECT_DIR/.venv"

echo "================================"
echo "AI-tinerary Setup"
echo "================================"
echo ""

# Check if Python 3 is installed
if ! command -v python3 &> /dev/null; then
    echo "❌ Error: Python 3 is not installed."
    echo "Please install Python 3 from https://www.python.org/downloads/"
    exit 1
fi

PYTHON_VERSION=$(python3 --version | cut -d' ' -f2)
echo "✓ Python $PYTHON_VERSION found"
echo ""

# Remove existing venv if present
if [ -d "$VENV_DIR" ]; then
    echo "Removing existing virtual environment..."
    rm -rf "$VENV_DIR"
fi

# Create virtual environment
echo "Creating virtual environment..."
python3 -m venv "$VENV_DIR"
echo "✓ Virtual environment created at .venv"
echo ""

# Activate virtual environment
echo "Activating virtual environment..."
source "$VENV_DIR/bin/activate"
echo "✓ Virtual environment activated"
echo ""

# Check for Dependencies.txt
if [ ! -f "$PROJECT_DIR/Dependencies.txt" ]; then
    echo "❌ Error: Dependencies.txt not found in $PROJECT_DIR"
    exit 1
fi

# Check for tkinter (standard library but often missing on Homebrew Python)
echo "Checking for tkinter (required for GUI)..."
if ! python3 -c "import tkinter" &> /dev/null; then
    echo "⚠️ Warning: 'tkinter' is missing."
    if [[ "$OSTYPE" == "darwin"* ]]; then
        echo "It seems you're on macOS using Homebrew Python."
        echo "Try installing it with: brew install python-tk@$PYTHON_VERSION"
        echo ""
    else
        echo "On Linux, try: sudo apt-get install python3-tk"
        echo ""
    fi
else
    echo "✓ tkinter found"
    echo ""
fi

# Install dependencies
echo "Installing dependencies from Dependencies.txt..."
pip install --upgrade pip > /dev/null 2>&1
pip install -r "$PROJECT_DIR/Dependencies.txt"
echo "✓ Dependencies installed"
echo ""

# Create required directories
echo "Creating project directories..."
mkdir -p "$PROJECT_DIR/Contracts/Incoming"
mkdir -p "$PROJECT_DIR/Contracts/Complete"
mkdir -p "$PROJECT_DIR/Outputs/Bits"
mkdir -p "$PROJECT_DIR/Outputs/Backups"
mkdir -p "$PROJECT_DIR/Outputs/Processed"
mkdir -p "$PROJECT_DIR/Outputs/Itineraries"
mkdir -p "$PROJECT_DIR/Logs"
mkdir -p "$PROJECT_DIR/Configs"
mkdir -p "$PROJECT_DIR/Keys"
mkdir -p "$PROJECT_DIR/Prompts/Defaults"
echo "✓ Directories created"
echo ""

# Create Default config in Configs if it doesn't exist
if [ ! -f "$PROJECT_DIR/Configs/Default" ]; then
    echo "Creating Default configuration in Configs/..."
    cp "$PROJECT_DIR/Master Config.txt" "$PROJECT_DIR/Configs/Default" 2>/dev/null || cat > "$PROJECT_DIR/Configs/Default" << 'EOF'
# AI-tinerary Default Configuration Profile
HOME_BASE_ADDRESS=""
ORS_API_KEY=""
ORS_BASE_URL=""
OLLAMA_URL="http://localhost:11434/api/generate"
OLLAMA_MODEL="ministral-3:3b"
MAX_THREADS=4
TIMEZONE="America/New_York"
DISCORD_BOT_TOKEN=""
DISCORD_CHANNEL_ID=""
GOOGLE_SERVICE_ACCOUNT_FILE=""
BAND_CALENDAR_ID=""
PUBLIC_CALENDAR_ID=""
EOF
    echo "✓ Default config created"
else
    echo "✓ Default config already exists"
fi
echo ""

# Create Master Config.txt if it doesn't exist
if [ ! -f "$PROJECT_DIR/Master Config.txt" ]; then
    echo "Creating Master Config.txt file (template...)"
    cat > "$PROJECT_DIR/Master Config.txt" << 'EOF'
# AI-tinerary Master Configuration
# Edit this file to control the Python scripts.  It uses dotenv format.

# Home Base Address (where the band departs from)
HOME_BASE_ADDRESS=""

# OpenRouteService configuration (optional).
# - ORS_API_KEY: public key from https://openrouteservice.org/
# - ORS_BASE_URL: URL of a self‑hosted container (e.g. http://localhost:8080/ors)
ORS_API_KEY=""
ORS_BASE_URL=""

# Ollama Settings
OLLAMA_URL="http://localhost:11434/api/generate"
OLLAMA_MODEL="ministral-3:3b"

# Processing
MAX_THREADS=4

# Default Timezone for Calendar events (e.g. America/New_York)
TIMEZONE="America/New_York"

# Discord Bot (optional)
# Generate a bot application and paste the token here.
DISCORD_BOT_TOKEN=""
DISCORD_CHANNEL_ID=""

# Google Calendar configuration
# Provide the path to your service account JSON and the calendar IDs
GOOGLE_SERVICE_ACCOUNT_FILE=""
BAND_CALENDAR_ID=""
PUBLIC_CALENDAR_ID=""
EOF
    echo "✓ Master Config.txt template created (edit with your settings)"
else
    echo "✓ Master Config.txt already exists"
fi
echo ""

echo "================================"
echo "Setup Complete! ✓"
echo "================================"
echo ""
echo "Next steps:"
echo "1. Edit Master Config.txt with your configuration:"
echo "   - Set OLLAMA_URL and OLLAMA_MODEL"
echo "   - Set HOME_BASE_ADDRESS"
echo "   - Set ORS_API_KEY or ORS_BASE_URL (optional, for routing)"
echo ""
echo "2. Make sure Ollama is running:"
echo "   ollama serve"
echo ""
echo "3. To activate the environment in the future:"
echo "   source .venv/bin/activate"
echo ""
echo "4. Run the scripts:"
echo "   python AI-tinerary-CSV.py    # To process contracts"
echo "   python AI-tinerary-CALBOT.py # To start the Discord bot"
echo ""
echo "For more info, see README.md"
