# 🎸 AI-tinerary: The Autonomous Tour Manager

**AI-tinerary** is an advanced, modular suite of AI-driven bots designed to handle the complex logistics of tour management. By combining local AI (Ollama), a robust Discord interface, and seamless Google Workspace integration, it transforms raw contract PDFs and emails into a fully synchronized touring ecosystem.

---

## 🏗️ System Architecture: The "Dream Team"

The system is powered by four specialized Python engines and two Google Apps Script (GAS) automations.

### 1. 🤖 CALBOT: The Central Coordinator (`AI-tinerary-CALBOT.py`)
CALBOT is the "brain" of the operation. It monitors the workflow and provides the primary interface for the band.
- **Discord Interaction:** Watches for new processed contracts and creates private threads for interactive review.
- **Data Guard:** Ensures no gig is added to the master schedule without human confirmation.
- **Google Calendar Sync:** Automatically manages three types of calendar entries:
    - **Private Band Calendar:** Detailed internal events with full contract notes.
    - **Public Audience Calendar:** Sanitized, "Live at [Venue]" events.
    - **Travel Blocks:** Yellow-coded blocks on the private calendar representing drive time, derived from MAPBOT's calculations.
- **Merge Engine:** Intelligently merges new data into the `master-output.csv` using fuzzy venue matching to prevent duplicates.

### 2. 🚚 MAPBOT: The Logistics Specialist (`AI-tinerary-MAPBOT.py`)
MAPBOT handles the physics of the tour—distance, time, and routing.
- **Smart Routing:** Uses **OpenRouteService (ORS)** to calculate high-accuracy driving routes and mileage.
- **Geocoding:** Resolves vague venue names or addresses into precise coordinates using **Nominatim**.
- **Dynamic Buffers:** Automatically calculates a "Recommended Departure Time" by adding a 15-minute buffer for every 2 hours of driving.
- **Conflict Detection:** Issues critical warnings in Discord if a drive time exceeds the window between the previous gig's end and the next gig's load-in.
- **Accommodation Logic:** Interactively tracks hotel/lodging addresses and adjusts next-day routing origins accordingly.

### 3. 📄 TINNYBOT: The Tour Packet Generator (`AI-tinerary-TINNYBOT.py`)
Operating as a Discord Cog within CALBOT, TINNYBOT generates the final "road-ready" documents.
- **Interactive Interview:** Conducts a brief Q&A in Discord to gather day-of details like Soundcheck and Dinner times.
- **Markdown Artifacts:** Generates beautiful, formatted `.md` tour packets containing the timeline, gig details, and venue contacts.
- **AI Survival Guide:** Uses Ollama to analyze the tour locations/weather and generate a customized packing list and "Survival Guide."

### 4. 🧠 Extraction Engine (`AI-tinerary-CSV.py`)
The gateway for all data.
- **Local AI Parsing:** Uses **Ollama** (default: `ministral-3:3b`) to securely parse unstructured PDFs and `.eml` files into structured JSON.
- **Pydantic Validation:** Enforces a strict schema to ensure all 20+ contract fields (Pay, Load-In, Contact info) are correctly captured.

---

## ☁️ Google Workspace Integration (Google Scripts)

The `google_scripts/` folder contains essential automations to bridge your local machine with the cloud.

### 📧 EMEX: Gmail Ingestion (`AI-tinerary-EMEX.gs`)
- **Automated Pull:** Scans your Gmail for messages labeled "Confirmed Shows."
- **Drive Sync:** Downloads PDF/EML attachments to a specific Google Drive folder.
- **Local Feed:** When your Google Drive is synced locally (to `Contracts/Incoming`), this creates a fully automated "Email-to-Bot" pipeline.

### 📊 SHSY: Sheets Synchronization (`AI-tinerary-SHSY.gs`)
- **Master Upsert:** Syncs your local `master-output.csv` (via Google Drive) into a formatted Google Sheet.
- **Preserve Formatting:** Uses a composite key (Date + Venue) to "upsert" data, allowing you to add manual columns or formatting in the sheet without it being overwritten by the bot.

---

## 🔄 The AI-tinerary Workflow

1.  **Ingest:** You label an email "Confirmed Shows" in Gmail. **EMEX** pulls the contract to Google Drive.
2.  **Extract:** Run `python AI-tinerary-CSV.py`. AI parses the contract into a "Bit" (CSV fragment) in `Outputs/Bits/`.
3.  **Review:** **CALBOT** detects the Bit and pings Discord. You click **Review**.
4.  **Enrich:** In the Discord thread, **MAPBOT** asks if you're staying the night. It then calculates routing from the previous stop.
5.  **Publish:** You click **Confirm & Publish**.
    - The **Master CSV** is updated.
    - **Google Calendars** are synced (including the **Travel Block**).
    - The **Google Sheet** is updated via **SHSY**.
6.  **Pack:** Run `!tinny generate` in Discord to get your beautiful Markdown **Tour Packet** and AI packing list.

---

## 🚀 Setup & Installation

### 1. Requirements
- **Python 3.10+**
- **Tkinter:** Required for the GUI manager (`AI-tinerary-GUI.py`).
  - **macOS (Homebrew):** `brew install python-tk@3.14` (or your Python version)
  - **Linux (Ubuntu/Debian):** `sudo apt-get install python3-tk`
- **Ollama:** Running locally with `ollama serve`.
- **OpenRouteService:** A free API key from [openrouteservice.org](https://openrouteservice.org/).
- **Discord Bot Token:** Created via the [Discord Developer Portal](https://discord.com/developers/applications).
- **Google Service Account:** A `.json` key file with "Calendar API" and "Drive API" enabled.

### 2. Quick Start
```bash
# Clone and Install
git clone <repo-url>
cd AI-tinerary
./setup.sh

# Launch the Management GUI (Recommended)
# This allows you to configure API keys and start/stop bots visually.
python AI-tinerary-GUI.py
```

### 3. Google Script Deployment
1. Go to [script.google.com](https://script.google.com/).
2. Create two projects: "AI-tinerary-EMEX" and "AI-tinerary-SHSY".
3. Paste the contents of the `.gs` files from `google_scripts/`.
4. Set the `FOLDER_ID` and `SPREADSHEET_ID` constants in the scripts.
5. Set time-based triggers (e.g., every 15 minutes) for the main functions.

---

## ⌨️ Bot Commands

| Command | Bot | Description |
| :--- | :--- | :--- |
| `!calbot status` | CALBOT | Show pending reviews and Master CSV stats. |
| `!calbot merge` | CALBOT | Manually scan `Outputs/Bits/` for new files. |
| `!mapbot status` | MAPBOT | List gigs missing routing or mileage data. |
| `!mapbot route all` | MAPBOT | Force recalculation of all routes in Master. |
| `!tinny generate <date>`| TINNYBOT| Start the interview for a specific gig date. |
| `!tinny generate <d1> <d2>`| TINNYBOT| Generate a multi-day tour packet. |

---

## 📄 License
This project is licensed under the **GNU General Public License v3.0**. See the `LICENSE` file for details.
