# AI-tinerary
AI-tinerary is a powerful, multithreaded Python utility designed to parse contract emails and PDFs, extract complex event details using local AI (Ollama), calculate driving mileages via routing APIs, and generate structured CSV outputs for band itinerary planning.

## 🚀 What's NewUnified CLI:

- Processing and combining CSVs is handled by a single aitinerary.py script.
- Environment Configuration: `Master Config.txt` file controls API keys and settings.
- Parallel Processing: Handles multiple files simultaneously, drastically speeding up data ingestion.
- Strict Validation: Uses Pydantic to ensure AI outputs perfectly match the target CSV spreadsheet schema.

## 📁 Repository Structure
```
AI-tinerary/
├── AI-tinerary              # Main application script
├── setup.sh                 # Automated setup for macOS/Linux
├── Dependencies.txt         # Python dependencies
├── Master Config.txt        # Master configuration (editable by user)
├── google_scripts/          # Google Apps Script helpers (see README section)
├── Contracts/               
│   ├── Incoming/            # Place raw .eml and .pdf contracts here
│   └── Complete/            # Processed files are automatically archived here
└── Outputs/                 # Generated individual CSVs and the master CSV
```

## 🛠️ Getting Started

### 📎 Google Apps Script Helper

A small Google Apps Script is included under `google_scripts/` to automatically save attachments
from labeled Gmail threads into a synced Google Drive folder. It is useful for grabbing contract
PDFs and `.eml` files before running the Python pipeline.

1. Open [Google Apps Script](https://script.google.com/) and create a new project.
2. Copy the contents of `google_scripts/label-exporter.gs` into your script editor.
3. Update the configuration constants (`SOURCE_LABEL_NAME`, `INCOMING_DRIVE_FOLDER_ID`, and
   `COMPLETE_DRIVE_FOLDER_ID`) to point at the two folders you sync locally. The first
   should mirror `Contracts/Incoming`, the second `Contracts/Complete`.
4. Set a time‑driven trigger (e.g. every 15 minutes) to run `saveConfirmedShowsAttachmentsToDrive`.

> **Cleanup step:**
> Once the Python pipeline has processed the incoming files and placed (or synced) them into the
> Complete folder, run `cleanupDriveFolder()` from the script editor or configure a second trigger
> (daily or whenever convenient). This helper will trash whatever is currently in the **complete**
> Drive folder, preventing the attachments from persisting anywhere other than the original email.
> It does not inspect creation dates or processing success, so ensure your local logic has
> finished before triggering it.

The Drive folder should be the same one that is synced to `Contracts/Incoming` locally.

---

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
- Generate a `Master Config.txt` configuration template

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

Edit the `Master Config.txt` file in the project root. This is the master configuration
file and is read by the Python script using dotenv semantics. The setup script
will generate it with defaults if it does not already exist.

```bash
# Ollama Settings
OLLAMA_URL=http://localhost:11434/api/generate
OLLAMA_MODEL=ministral-3:3b

# Home Base Address
HOME_BASE_ADDRESS=Johnson City, TN, United States

# OpenRouteService: you can either supply a public API key (optional) or
# point at a self-hosted server. The container defaults to
# http://localhost:8080/ors/v2 when run locally.
# Leave both values blank to disable mileage calculations entirely.
ORS_API_KEY=your_api_key_here
ORS_BASE_URL=http://localhost:8080/ors/v2
```

> 💡 On startup the script logs the values it read for `ORS_API_KEY` and `ORS_BASE_URL`.
> If you see `<empty>` next to both, check your Master Config file—env vars with
> the same names already set in your shell will take precedence and prevent
> the file from being reloaded unless you restart the process.

### OpenRouteService (optional)

If you prefer to run your own instance instead of using the public API, you
can launch the official Docker image:

```bash
docker run --rm -p 8080:8080 openrouteservice/openrouteservice
```

**Important clarification:** the vanilla ORS container only contains the
routing backend – it does **not** include any geocoding logic.  The public
`api.openrouteservice.org` endpoint feels unified because the provider runs a
separate geocoder (Pelias) behind a gateway, but the open‑source Docker image
has no internal handler for `/v2/geocode/*` endpoints.  Therefore requests
like `/ors/v2/geocode/search` return a `404 No static resource` error.  This
is the error you saw in the logs earlier.

To restore geocoding there are two approaches:

1. **Self‑host everything** – run a dedicated geocoder (e.g. [Photon](https://photon.komoot.io/) or Pelias) and put a reverse proxy in front that
   directs `/ors/v2/*` traffic to the ORS container and `/v2/geocode/*` traffic
   to the geocoder.  A sample `docker-compose.yml` and `nginx.conf` are provided
   in the project root; start them with `docker-compose up` and then point
   `ORS_BASE_URL` at `http://localhost:24701`.

2. **Use a public geocoder** – leave the local ORS instance running for routing
   only, and configure your application (or the `ORS_BASE_URL` variable) to
   hit a geocoding API such as Nominatim, Photon’s public API, or
   `https://api.openrouteservice.org/geocode/search` directly.

Either way, once a working geocoder is reachable you can test it with:

```bash
curl -X POST http://localhost:24701/ors/v2/geocode/search \
     -H 'Content-Type: application/json' \
     -d '{"text":"Johnson City, TN"}'
```

(Adjust host/port as appropriate for your setup.)

The **primary takeaway** is that routing and geocoding are separate services –
logging improvements, fallback logic, and documentation updates in this repo
now reflect that reality.
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

### 🤖 Discord Bot & Google Calendar Integration

A companion Discord bot (`AI-tinerary-CALBOT.py`) can read the CSVs produced in `Outputs/`, ask you interactively to fill in missing fields, and optionally create events on two Google Calendars (a private band calendar and a public-facing calendar).

To enable this feature you must:
1. Add the following variables to `Master Config.txt` (or via environment):
   ```ini
   DISCORD_BOT_TOKEN=your_discord_bot_token
   GOOGLE_SERVICE_ACCOUNT_FILE=/path/to/service-account.json
   BAND_CALENDAR_ID=your_band_calendar_id@group.calendar.google.com
   PUBLIC_CALENDAR_ID=your_public_calendar_id@group.calendar.google.com
   ```
2. Install the additional dependencies (they are already listed in `Dependencies.txt`).
3. Run the bot script with:
   ```bash
   python AI-tinerary-CALBOT.py
   ```

Once the bot is online you can use the following text commands in any server or
via DM with the bot:

- `!fill [filename]` – the bot will read the specified CSV (or all CSVs if you
  omit the filename), look for empty fields, and then start a conversa­tion in
  your DMs.  You can simply describe the show in plain English and the AI will
  attempt to populate as many blanks as possible; it will summarize its
  findings, ask follow‑ups for information it still needs, and finally ask any
  remaining specific questions until the sheet is complete.  This makes data
  entry feel like chatting with an assistant rather than filling out a form.
- `!event [filename]` – create calendar events based on the CSV row.  The bot will
  ask for start/end datetimes if not already supplied (these can also be filled
  during the `!fill` conversation).
- `!setconfig KEY VALUE` – write a key/value pair into `Master Config.txt` so
  you don’t have to open the file manually.

The logic that determines which fields to ask about is entirely data-driven
(`!fill` inspects the CSV to find blanks), so you can add new columns (for
example `Calendar Start`/`Calendar End`) and the bot will automatically
inquire about them without any code change.

The bot also includes a little heuristic to convert whatever date/time info
it gathers into ISO calendar datetimes.  That requires the `python-dateutil`
package (now listed in `Dependencies.txt`) which is installed by the setup
script.  If the AI has enough information it will pre‑fill `Calendar Start`
and `Calendar End` automatically for you when the conversation ends.

If you ever want to fine‑tune the phrasing or add extra fields, edit the
`QUESTION_SCRIPT` list inside `AI-tinerary-CALBOT.py` as noted in the source
comments; the conversational loop handles both automatic AI fills and explicit
value prompts.

---


**Advanced CLI Commands:**
```bash
python AI-tinerary --process-only  # Process files, but don't merge them
python AI-tinerary --combine-only  # Just merge existing CSVs into the master file
```

🧪 **Testing**

A small pytest suite exists under `tests/` that verifies routing
configuration logic.  After installing dependencies you can run:

```bash
pip install -r Dependencies.txt  # ensure pytest is available
pytest
```
## ⚙️ How it Works

1. Ingestion: Reads text directly from PDFs, .eml bodies, and .eml PDF attachments.
2. AI Extraction: Feeds text to the local LLM with strict formatting prompts.Validation: Pydantic validates the data structure. Missing keys are populated with defaults, protecting your CSV format.
3. Geocoding: OpenRouteService calculates the driving mileage from your home base to the venue.
4. Output: Writes individual <filename>.csv files and compiles everything into a master-output.csv.

## 📄 License

Released under the GPL License. See LICENSE for details.
