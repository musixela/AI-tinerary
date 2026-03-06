#!/bin/bash
# setup.sh - AI-tinerary First-Time Setup Script
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
mkdir -p "$PROJECT_DIR/Outputs"
echo "✓ Directories created"
echo ""

# Create .env if it doesn't exist
if [ ! -f "$PROJECT_DIR/.env" ]; then
    echo "Creating .env file (template)..."
    cat > "$PROJECT_DIR/.env" << 'EOF'
# AI-tinerary Environment Configuration

# Ollama Settings
OLLAMA_URL=http://localhost:11434/api/generate
OLLAMA_MODEL=ministral-3:3b

# Home Base Address (where the band departs from)
HOME_BASE_ADDRESS=Johnson City, TN, United States

# OpenRouteService API Key (get one at https://openrouteservice.org/)
ORS_API_KEY=your_api_key_here

# Processing
MAX_THREADS=4
EOF
    echo "✓ .env template created (edit with your settings)"
else
    echo "✓ .env file already exists"
fi
echo ""

echo "================================"
echo "Setup Complete! ✓"
echo "================================"
echo ""
echo "Next steps:"
echo "1. Edit .env with your configuration:"
echo "   - Set OLLAMA_URL and OLLAMA_MODEL"
echo "   - Set HOME_BASE_ADDRESS"
echo "   - Set ORS_API_KEY (optional, for routing)"
echo ""
echo "2. Make sure Ollama is running:"
echo "   ollama serve"
echo ""
echo "3. To activate the environment in the future:"
echo "   source .venv/bin/activate"
echo ""
echo "4. Run the script:"
echo "   python AI-tinerary"
echo ""
echo "For more info, see README.md"
