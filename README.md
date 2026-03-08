# 🎸 AI-tinerary

**AI-tinerary** is a powerful, multithreaded Python pipeline designed to automate tour management. It parses incoming contract emails and PDFs, extracts complex event details using local AI, calculates driving mileage, and generates structured CSV itineraries. 

Coupled with a custom **Discord Bot** and **Google Calendar integration**, it provides a seamless, interactive command center for your entire band or touring crew.

---

## ✨ Key Features

* **🧠 Local AI Extraction:** Uses [Ollama](https://ollama.com/) (default: `ministral-3:3b`) to securely parse unstructured contracts into strict JSON data.
* **🗺️ Smart Routing & Geocoding:** Integrates OpenRouteService and Nominatim to automatically calculate driving distances from your home base to the venue.
* **🤖 Discord Tour Manager Bot:** Meet "Cal," your AI assistant. Use the `!fill` command to interactively chat with your itinerary, naturally filling in missing data like load-in times or hospitality notes.
* **📅 Google Calendar Sync:** Automatically infers dates and times from natural language and pushes events directly to your band's private and public calendars.
* **📥 Automated Gmail Ingestion:** Includes a Google Apps Script to automatically sync contract attachments from labeled Gmail threads straight into your processing folder.
* **🛡️ Strict Validation:** Uses Pydantic to ensure AI outputs perfectly match your target CSV spreadsheet schema every time.

---

## 📁 Repository Structure

```text
AI-tinerary/
├── AI-tinerary-CSV.py       # Core data extraction & routing pipeline
├── AI-tinerary-CALBOT.py    # Discord Tour Manager Bot
├── setup.sh                 # Automated setup for macOS/Linux
├── setup.bat                # Automated setup for Windows
├── Dependencies.txt         # Python dependencies
├── Master Config.txt        # Master configuration (auto-generated on setup)
├── google_scripts/          # Gmail to Drive automation script
├── Contracts/               
│   ├── Incoming/            # Drop raw .eml and .pdf contracts here
│   └── Complete/            # Processed files are automatically archived here
└── Outputs/                 # Generated individual CSVs and the master CSV

```

---

## 🚀 Getting Started

### 1. Installation

**Option A: Automated Setup (Recommended)**

**macOS / Linux:**

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

*The setup scripts will create a virtual environment, install dependencies, create required directories, and generate your `Master Config.txt` file.*

**Option B: Manual Setup**

```bash
python3 -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r Dependencies.txt

```

### 2. Configuration (`Master Config.txt`)

All settings are managed via `Master Config.txt` in the root directory. Edit this file to configure your AI, Routing, Discord, and Google settings.

```ini
# Ollama Settings
OLLAMA_URL=http://localhost:11434/api/generate
OLLAMA_MODEL=ministral-3:3b

# Routing & Mileage (Optional)
HOME_BASE_ADDRESS=Johnson City, TN, United States
ORS_API_KEY=your_public_api_key
ORS_BASE_URL=http://localhost:8080/ors/v2 # For self-hosting

# Discord Bot (Optional)
DISCORD_BOT_TOKEN=your_discord_token_here

# Google Calendar (Optional)
GOOGLE_SERVICE_ACCOUNT_FILE=path/to/credentials.json
BAND_CALENDAR_ID=your_band_calendar_id@group.calendar.google.com
PUBLIC_CALENDAR_ID=your_public_calendar_id@group.calendar.google.com

```

### 3. Ensure Local Services are Running

Make sure you have Ollama installed and running before starting the pipeline:

```bash
ollama serve
ollama pull ministral-3:3b

```

---

## 💻 Usage & Workflows

### Phase 1: The Core Pipeline

Place your `.eml` or `.pdf` files into the `Contracts/Incoming/` directory, then run the CSV extractor:

```bash
# Process all files, calculate mileage, and combine into master-output.csv
python AI-tinerary-CSV.py

# Optional: Force update mileage on existing processed CSVs
python AI-tinerary-CSV.py --update-mileage

```

### Phase 2: The Discord Bot (CALBOT)

To run the interactive Tour Manager bot, keep this script running in a terminal or server:

```bash
python AI-tinerary-CALBOT.py

```

**Available Discord Commands:**

* `!status`: View a dashboard of upcoming gigs and see exactly which details (like Pay, Load In, or Hospitality) are missing.
* `!fill [filename]`: Initiates a DM conversation with the bot to intelligently fill in missing data using plain English.
* `!ask [question]`: Ask Cal, the Tour Manager persona, any general logistics question.
* `!combine`: Force the bot to re-compile the master CSV.
* `!list`: View a quick text list of all files and their missing field counts.

*(Note: Calendar events are created interactively via UI buttons inside the bot's DM interface once a file is finalized).*

---

## 📎 Gmail to Drive Automation (Optional)

We include a Google Apps Script to automate getting files into your `Incoming` folder.

1. Open [Google Apps Script](https://script.google.com/) and create a new project.
2. Copy the contents of `google_scripts/label-exporter.gs` into the editor.
3. Update `SOURCE_LABEL_NAME` and your Drive Folder IDs.
4. Set a time‑driven trigger (e.g., every 15 minutes) to run `saveConfirmedShowsAttachmentsToDrive`.
5. *Cleanup:* Run `cleanupDriveFolder()` occasionally to purge the sync folder after your Python script has successfully processed the files locally.

---

## 🗺️ Advanced: Self-Hosting OpenRouteService

If you prefer to run your own ORS instance instead of using the public API:

```bash
docker run --rm -p 8080:8080 openrouteservice/openrouteservice

```

**Note on Geocoding:** The vanilla ORS container handles *routing* but not *geocoding*. If you self-host, you must either run a dedicated geocoder (like Photon or Pelias) behind a reverse proxy, or leave `ORS_BASE_URL` blank and rely on the built-in Nominatim fallback for address resolution.

---

## 📄 License

Released under the **GNU General Public License v3.0**. See the `LICENSE` file for details.
