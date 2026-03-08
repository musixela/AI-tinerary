# 🎸 AI-tinerary: The Autonomous Tour Manager

**AI-tinerary** is an advanced, AI-driven suite of bots designed to automate the heavy lifting of tour management. From extracting contract data to planning complex driving routes and managing your calendar, AI-tinerary handles the logistics so you can focus on the music.

The system is composed of three primary engines:
1.  **Extraction Engine (`AI-tinerary-CSV.py`):** Converts raw PDFs and emails into structured data.
2.  **CALBOT (`AI-tinerary-CALBOT.py`):** The Discord-based coordinator for review, master CSV merging, and Google Calendar sync.
3.  **MAPBOT (`AI-tinerary-MAPBOT.py`):** The logistics specialist for routing, mileage, accommodations, and itinerary timing.

---

## ✨ System Architecture

### 🧠 AI Extraction (`AI-tinerary-CSV.py`)
- **Local AI:** Uses [Ollama](https://ollama.com/) (default: `ministral-3:3b`) to securely parse unstructured contracts into strict JSON.
- **Strict Schema:** Powered by Pydantic to ensure AI outputs perfectly match your target itinerary schema.
- **Multithreaded:** Processes batches of contracts simultaneously for high efficiency.

### 🤖 CALBOT: The Coordinator
- **Discord Interface:** Monitors your processed data and notifies your team when new contracts arrive.
- **Interactive Review:** Guides you through private Discord threads to fill missing details or use AI to extract info from pasted snippets.
- **Master Merge:** Intelligently merges updates into a `master-output.csv` with fuzzy venue matching and automated changelogs.
- **Calendar Sync:** Automatically creates and updates events on both **Private Band** and **Public Audience** Google Calendars.

### 🚚 MAPBOT: The Logistics Specialist
- **Smart Routing:** Calculates high-accuracy driving routes using **OpenRouteService** (with geodesic fallbacks).
- **Tour Context:** Automatically determines origins based on your tour schedule (Previous Gig -> Next Gig or Home Base -> Gig).
- **Accommodation Tracking:** Interactively asks about overnight stays and stores hotel/lodging addresses.
- **Precision Timing:** Estimates departure times based on driving duration and your required `Load In` or `Doors` time (includes a 30m safety buffer).

---

## 🚀 Getting Started

### 1. Installation

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

### 2. Configuration (`Master Config.txt`)

All settings are managed via `Master Config.txt`. Key sections include:

- **AI:** `OLLAMA_URL`, `OLLAMA_MODEL`.
- **Logistics:** `HOME_BASE_ADDRESS`, `ORS_API_KEY`.
- **Discord:** `DISCORD_BOT_TOKEN`, `DISCORD_CHANNEL_ID`.
- **Google:** `GOOGLE_SERVICE_ACCOUNT_FILE`, `BAND_CALENDAR_ID`, `PUBLIC_CALENDAR_ID`.

### 3. External Services
- **Ollama:** Must be running locally (`ollama serve`).
- **OpenRouteService:** Requires a free API key from [openrouteservice.org](https://openrouteservice.org/) or a local Docker instance.

---

## 💻 Usage Workflow

### Step 1: Ingestion
Place `.pdf` or `.eml` contracts into `Contracts/Incoming/`. Run the extractor:
```bash
python AI-tinerary-CSV.py
```
This generates a "Bit" (partial CSV) in `Outputs/Bits/`.

### Step 2: Discord Review (CALBOT + MAPBOT)
1. CALBOT detects the new Bit and posts a **"📝 Review"** button in Discord.
2. Clicking Review opens a private thread.
3. **Logistics Check:** MAPBOT asks if you're staying the night. If yes, provide the address.
4. **Data Review:** Fill in any missing contract fields.
5. **Finalize:** Click **"✅ Confirm & Publish"**.

### Step 3: Automation Payload
Upon finalization, the system automatically:
- Merges the data into the **Master Itinerary**.
- Calculates the **Route & Mileage** from the previous tour stop.
- Injects **Recommended Departure Times** into the gig notes.
- Pushes events to **Google Calendars**.
- Archives the raw files.

---

## 🤖 Bot Commands

| Command | Purpose |
| :--- | :--- |
| `!calbot status` | Show pending reviews and Master CSV stats. |
| `!calbot merge` | Manually trigger a scan of the `Bits/` folder. |
| `!mapbot status` | List gigs currently needing routing or mileage. |
| `!mapbot route all` | Recalculate routing for all gigs in the Master CSV. |
| `!mapbot route <date>` | Recalculate routing for a specific date (e.g., `!mapbot route 2025-06-15`). |

---

## 📄 License
Released under the **GNU General Public License v3.0**. See the `LICENSE` file for details.
