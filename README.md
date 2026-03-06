AI-tineraryAI-tinerary is a powerful, multithreaded Python utility designed to parse contract emails and PDFs, extract complex event details using local AI (Ollama), calculate driving mileages via routing APIs, and generate structured CSV outputs for band itinerary planning.🚀 What's NewUnified CLI: Processing and combining CSVs is handled by a single aitinerary.py script.Environment Configuration: Secure .env file for API keys and configuration.Parallel Processing: Handles multiple files simultaneously, drastically speeding up data ingestion.Strict Validation: Uses Pydantic to ensure AI outputs perfectly match the target CSV spreadsheet schema.📁 Repository Structure
```
AI-tinerary/
├── AI-tinerary              # Main application script
├── setup.sh                 # Automated setup for macOS/Linux
├── Dependencies.txt         # Python dependencies
├── .env                     # Configuration (created by setup)
├── Contracts/               
│   ├── Incoming/            # Place raw .eml and .pdf contracts here
│   └── Complete/            # Processed files are automatically archived here
└── Outputs/                 # Generated individual CSVs and the master CSV
```

🛠️ Getting Started

### Option 1: Automated Setup (Recommended)

**macOS/Linux:**
```bash
git clone <your-repo-url>
cd AI-tinerary
./setup.sh
```

**Windows:**
```cmd
git clone <your-repo-url>
cd AI-tinerary
setup.bat
```

The setup scripts will:
- Create and activate a Python virtual environment
- Install all dependencies from `Dependencies.txt`
- Create required directories
- Generate a `.env` configuration template

### Option 2: Manual Setup

Clone the repository:
```bash
git clone <your-repo-url>
cd AI-tinerary
```

Create and activate the virtual environment:
```bash
python3 -m venv .venv
source .venv/bin/activate   # macOS/Linux
# OR on Windows:
# .venv\Scripts\activate
```

Install dependencies:
```bash
pip install -r Dependencies.txt
```

### Configure Settings

Edit the `.env` file (created by setup script or manually):
```bash
# Ollama Settings
OLLAMA_URL=http://localhost:11434/api/generate
OLLAMA_MODEL=ministral-3:3b

# Home Base Address
HOME_BASE_ADDRESS=Johnson City, TN, United States

# OpenRouteService API Key (optional, for mileage calculation)
ORS_API_KEY=your_api_key_here
```

### Ensure Ollama is Running

Make sure you have Ollama installed and running locally:
```bash
ollama serve
ollama pull ministral-3:3b
```
💻 Usage

Place your `.eml` or `.pdf` files into the `Contracts/Incoming/` directory.

**Standard Run** (Process all files & Combine CSVs):
```bash
python AI-tinerary
```

**Advanced CLI Commands:**
```bash
python AI-tinerary --process-only  # Process files, but don't merge them
python AI-tinerary --combine-only  # Just merge existing CSVs into the master file
```
⚙️ How it WorksIngestion: Reads text directly from PDFs, .eml bodies, and .eml PDF attachments.AI Extraction: Feeds text to the local LLM with strict formatting prompts.Validation: Pydantic validates the data structure. Missing keys are populated with defaults, protecting your CSV format.Geocoding: OpenRouteService calculates the driving mileage from your home base to the venue.Output: Writes individual <filename>.csv files and compiles everything into a master-output.csv.📄 LicenseReleased under the GPL License. See LICENSE for details.
