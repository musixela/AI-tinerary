#!/usr/bin/env python3
"""
AI-tinerary: Advanced Contract Processing Pipeline

Stack:
- Ollama (local model) for contract parsing.
- openrouteservice (FOSS routing engine) for driving mileage.
- Pydantic for strict schema validation.
- ThreadPoolExecutor for parallel processing.
"""

import csv
import json
import logging
import argparse
from pathlib import Path
from io import BytesIO
from email import policy
from email.parser import BytesParser
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import defaultdict

import requests
from pypdf import PdfReader
import openrouteservice
from pydantic import BaseModel, Field, ValidationError
from dotenv import load_dotenv
import os

# ------------- CONFIGURATION & SETUP -------------

# NOTE: ROOT_DIR is defined further down, so loading dotenv must wait until
# after we compute it.  We'll call this after the path variables block below.

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger(__name__)

# Project Paths
ROOT_DIR = Path(__file__).resolve().parent
CONTRACTS_DIR = ROOT_DIR / "Contracts" / "Incoming"
OUTPUTS_DIR = ROOT_DIR / "Outputs"
COMPLETE_DIR = ROOT_DIR / "Contracts" / "Complete"
MASTER_CSV = OUTPUTS_DIR / "master-output.csv"

# Load configuration from the master file (`Master Config.txt`) then fallback to
# a conventional `.env` if present.  Doing this here ensures ROOT_DIR is
# already defined.
load_dotenv(dotenv_path=ROOT_DIR / "Master Config.txt")
load_dotenv()

# Env Vars
HOME_BASE_ADDRESS = os.getenv("HOME_BASE_ADDRESS", "Johnson City, TN, United States")
ORS_API_KEY = os.getenv("ORS_API_KEY", "")
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434/api/generate")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "ministral-3:3b")
MAX_THREADS = int(os.getenv("MAX_THREADS", 4))

# ------------- SCHEMA VALIDATION -------------

class ContractData(BaseModel):
    """Pydantic model to strictly enforce the output schema and defaults."""
    starting_date: str = Field(default="", alias="Starting Date")
    ending_date: str = Field(default="", alias="Ending Date")
    venue: str = Field(default="", alias="Venue")
    location: str = Field(default="", alias="Location")
    booking: str = Field(default="FALSE", alias="Booking")
    mgmt: str = Field(default="FALSE", alias="MGMT")
    door_deal: str = Field(default="FALSE", alias="Door Deal")
    dd_notes: str = Field(default="", alias="DD Notes")
    hospitality: str = Field(default="", alias="Hospitality")
    contact_name: str = Field(default="", alias="Contact Name")
    contact_details: str = Field(default="", alias="Contact Details")
    other_details: str = Field(default="", alias="Other Details")
    address: str = Field(default="", alias="Address")
    accommodations: str = Field(default="", alias="Accomodations") # Keeping typo from original sheet
    accom_address: str = Field(default="", alias="Accom Address")
    est_mileage: str = Field(default="", alias="Est. Mileage")
    time: str = Field(default="", alias="Time")
    doors: str = Field(default="", alias="Doors")
    load_in: str = Field(default="", alias="Load In")
    pay: str = Field(default="", alias="Pay")
    sound_person: str = Field(default="", alias="Sound - Person")
    sound_system: str = Field(default="", alias="Sound - System")
    other_expenses: str = Field(default="", alias="Other Expenses")

    class Config:
        populate_by_name = True

SHEET_COLUMNS = list(ContractData.model_fields.keys())
# Map attribute names back to original CSV aliases for writing
CSV_HEADERS = [ContractData.model_fields[k].alias or k for k in SHEET_COLUMNS]


# ------------- TEXT EXTRACTION -------------

def read_pdf_bytes_text(pdf_bytes: bytes) -> str:
    reader = PdfReader(BytesIO(pdf_bytes))
    return "\n\n".join(page.extract_text() or "" for page in reader.pages)

def read_file_text(file_path: Path) -> str:
    """Extracts text from PDF or EML appropriately."""
    if file_path.suffix.lower() == ".pdf":
        return read_pdf_bytes_text(file_path.read_bytes())
    
    # EML Processing
    with open(file_path, "rb") as f:
        msg = BytesParser(policy=policy.default).parse(f)

    parts = [
        f"Subject: {msg['subject'] or ''}\nFrom: {msg['from'] or ''}\nDate: {msg['date'] or ''}"
    ]

    body = msg.get_body(preferencelist=("plain", "html"))
    if body:
        try:
            parts.append(body.get_content())
        except Exception:
            pass

    for attachment in msg.iter_attachments():
        filename = attachment.get_filename() or ""
        if attachment.get_content_type() == "application/pdf" or filename.lower().endswith(".pdf"):
            try:
                parts.append(read_pdf_bytes_text(attachment.get_content()))
            except Exception as e:
                logger.warning(f"Could not read attachment {filename}: {e}")

    return "\n\n".join(parts)


# ------------- AI & API SERVICES -------------

def call_ollama_extract(contract_text: str) -> ContractData:
    """Calls Ollama and maps the output securely to the Pydantic model."""
    system_instructions = f"""
You are helping a band ingest show contracts into a structured spreadsheet.

The band always departs from this fixed home base:
"{HOME_BASE_ADDRESS}"

The input text may be:
- A contract PDF converted to text
- An email offer / confirmation
- An email that also includes attached PDFs

You must consider ALL of this text together to infer the show details.

You must output a single JSON OBJECT with EXACTLY these keys
(spelling and capitalization must match exactly):

{json.dumps(SHEET_COLUMNS, indent=2)}

Rules for values:
- If you can infer a value from the contract/email, fill it.
- If you CANNOT infer the value, set it to an empty string "".
- NEVER omit a key.
- NEVER use null, None, true, false, numbers, or any non-string type.
- All values must be JSON strings (the CSV is purely text).

Field meanings and formatting (examples based on a typical contract) [file:98][file:181]:

- "Starting Date":
  - First performance date covered by the contract or email.
  - Prefer US M/D format with no leading zero and no year, e.g. "5/8" for May 8th, 2026.
  - If multiple dates are given, use the earliest one.

- "Ending Date":
  - Last performance date covered by the contract/email.
  - If it is a single-date show, set this to "".
  - For multi‑day runs or festivals with a clear date range, put the final date in the same M/D style, e.g. "5/10".

- "Venue":
  - Name of the physical venue or location, e.g. "Downtown Commons".
  - If there's a series name plus a place (e.g. "SAILS Original Music Series – downtown commons - Hickory, NC"),
    use the place as Venue ("Downtown Commons") and mention the series in "Other Details".

- "Location":
  - City and state in one string, like "Hickory, NC".

- "Booking":
  - "TRUE" if there is a booking contact / talent buyer / booking agent clearly specified
    (in the email or contract).
  - Otherwise "FALSE".

- "MGMT":
  - "TRUE" if there is a manager or management company mentioned.
  - Otherwise "FALSE".

- "Door Deal":
  - "TRUE" if pay is described as a door deal or percentage of ticket sales
    (e.g. "60% of door", "70/30 split").
  - "FALSE" if it is a flat guarantee only.

- "DD Notes":
  - Extra notes related to the door deal if present (minimums, caps, splits).
  - Otherwise "".

- "Hospitality":
  - Food, drinks, and hospitality in short sentences.
  - Example: "Food: Healthy snacks provided pre-show. Drinks: N/A".

- "Contact Name":
  - Name of the main day-of-show contact or primary email sign‑off person.
  - Example: "Bob Sinclair".

- "Contact Details":
  - Contact methods (phone, email) in one string.
  - Example: "828.320.4131, bobsinclairmusic@gmail.com".

- "Other Details":
  - Any other clauses or notes useful to the band:
    radius clauses, series names, weather plan, press info, parking notes, etc.

- "Address":
  - Best available full street address of the venue, including city, state, and zip if present.
  - Example: "238 Union Square NW, Hickory, NC 28601".

- "Accomodations":
  - Short description of lodging arrangements such as number/type of rooms.
  - Example: "4 double rooms".

- "Accom Address":
  - Full address of the lodging/hotel if it is clearly specified anywhere.
  - Otherwise "".

- "Est. Mileage":
  - Leave as "" (this will be filled later by a routing API, not by you).

- "Time":
  - Main show start time as it appears, e.g. "7:00 PM".

- "Doors":
  - Door time if specified, e.g. "6:30 PM".
  - Else "".

- "Load In":
  - Load-in time, e.g. "4:30 PM".

- "Pay":
  - Guaranteed fee or pay terms, as a string with currency formatting if obvious.
  - Example: "$950.00".

- "Sound - Person":
  - Sound tech person or company if clearly specified.
  - Otherwise "".

- "Sound - System":
  - Short description of PA, such as "Provided", "House PA", "None", etc.

- "Other Expenses":
  - Any clearly specified extra expenses the band must pay (parking fees, marketing fees).
  - Otherwise "".

Return ONLY the JSON object. Do NOT wrap it in markdown, do NOT add explanations.
"""
    try:
        resp = requests.post(
            OLLAMA_URL, 
            json={"model": OLLAMA_MODEL, "prompt": system_instructions + "\n\nTEXT:\n" + contract_text, "stream": False, "format": "json"}, 
            timeout=180
        )
        resp.raise_for_status()
        data = resp.json()
        
        # Parse output securely through Pydantic
        raw_json = json.loads(data.get("response", "{}"))
        return ContractData(**raw_json)
        
    except (requests.RequestException, json.JSONDecodeError, ValidationError) as e:
        logger.error(f"AI Extraction failed. Returning empty struct. Error: {e}")
        return ContractData() # Returns all empty defaults

def get_driving_distance_miles(dest_addr: str) -> str:
    """Calculate driving distance using OpenRouteService."""
    if not ORS_API_KEY or not dest_addr:
        return ""

    client = openrouteservice.Client(key=ORS_API_KEY)
    try:
        # Geocode origin and destination
        origin = client.pelias_search(text=HOME_BASE_ADDRESS, size=1)["features"][0]["geometry"]["coordinates"]
        dest = client.pelias_search(text=dest_addr, size=1)["features"][0]["geometry"]["coordinates"]
        
        # Route
        route = client.directions(coordinates=[origin, dest], profile="driving-car", format="json")
        miles = route["routes"][0]["summary"]["distance"] / 1609.34
        return f"{miles:.2f}"
    except Exception as e:
        logger.warning(f"Routing failed for '{dest_addr}': {e}")
        return ""

# ------------- WORKFLOW LOGIC -------------

def process_single_file(file_path: Path):
    """Process a single document from start to finish."""
    logger.info(f"Processing: {file_path.name}")
    
    # 1. Extract Text
    text = read_file_text(file_path)
    if not text.strip():
        logger.warning(f"No text found in {file_path.name}, skipping.")
        return False

    # 2. AI Extraction
    extracted_data = call_ollama_extract(text)
    
    # 3. Post-process (Booleans & Mileage)
    for attr in ['booking', 'mgmt', 'door_deal']:
        val = getattr(extracted_data, attr).strip().upper()
        setattr(extracted_data, attr, "TRUE" if val in ("TRUE", "YES", "Y", "1") else "FALSE")
    
    dest_addr = extracted_data.address or (f"{extracted_data.venue}, {extracted_data.location}" if extracted_data.location else "")
    if dest_addr:
        extracted_data.est_mileage = get_driving_distance_miles(dest_addr)
    
    if not extracted_data.venue:
        extracted_data.venue = file_path.stem

    # 4. Save to CSV
    csv_path = OUTPUTS_DIR / f"{file_path.stem}.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_HEADERS)
        writer.writeheader()
        writer.writerow(extracted_data.model_dump(by_alias=True))
        
    # 5. Archive
    file_path.rename(COMPLETE_DIR / file_path.name)
    logger.info(f"Successfully processed and archived {file_path.name}")
    return True

def combine_csvs():
    """Combines all individual CSVs in Outputs into one master CSV.

    Unlike the original implementation, headers are discovered dynamically
    from the CSV files currently in the folder.  This allows auxiliary
    tools (e.g. the Discord bot) to add extra columns such as calendar
    start/end times without breaking the merge step.
    """
    logger.info("Combining CSV files...")
    csv_paths = [p for p in OUTPUTS_DIR.glob("*.csv") if not p.name.lower().startswith("master")]
    
    if not csv_paths:
        logger.info("No CSV files to combine.")
        return

    # gather all rows and headers
    all_rows = []
    headers = set()
    for path in sorted(csv_paths):
        with open(path, newline="", encoding="utf-8") as in_f:
            reader = csv.DictReader(in_f)
            if reader.fieldnames:
                headers.update(reader.fieldnames)
            for row in reader:
                all_rows.append(row)

    headers = sorted(headers)

    with open(MASTER_CSV, "w", newline="", encoding="utf-8") as out_f:
        writer = csv.DictWriter(out_f, fieldnames=headers)
        writer.writeheader()
        for row in all_rows:
            # ensure all headers are present
            out_row = {h: row.get(h, "") for h in headers}
            writer.writerow(out_row)

    logger.info(f"Combined {len(csv_paths)} file(s) into {MASTER_CSV.name}")

def setup_dirs():
    for d in [CONTRACTS_DIR, OUTPUTS_DIR, COMPLETE_DIR]:
        d.mkdir(parents=True, exist_ok=True)


def group_files_by_prefix(files):
    """
    Group .pdf and .eml files that belong to the same event.
    Assumes filenames look like:
    YYYYMMDD_HHMMSS - Subject ... .ext
    We use everything up to the first ' - ' as the group key.
    """
    groups = defaultdict(list)
    for path in files:
        name = path.name
        parts = name.split(" - ", 1)
        if len(parts) == 2:
            prefix = parts[0]  # e.g. '20260307_221530'
        else:
            # Fallback: stem without extension
            prefix = path.stem
        groups[prefix].append(path)
    return groups


def process_group(prefix: str, file_paths: list[Path]):
    """Process all files belonging to a single event (EML + PDFs)."""
    logger.info(f"Processing group {prefix} with {len(file_paths)} files")

    # 1. Extract and concatenate text from all files
    texts = []
    for fp in sorted(file_paths):
        try:
            t = read_file_text(fp)
            if t.strip():
                texts.append(f"===== FILE: {fp.name} =====\n{t}")
        except Exception as e:
            logger.warning(f"Failed to read {fp.name}: {e}")
    if not texts:
        logger.warning(f"No text found for group {prefix}, skipping.")
        return False

    combined_text = "\n\n".join(texts)

    # 2. AI Extraction once per group
    extracted_data = call_ollama_extract(combined_text)

    # 3. Post-process (Booleans & Mileage)
    for attr in ['booking', 'mgmt', 'door_deal']:
        val = getattr(extracted_data, attr).strip().upper()
        setattr(extracted_data, attr, "TRUE" if val in ("TRUE", "YES", "Y", "1") else "FALSE")

    # Prefer explicit address; else venue + location
    dest_addr = extracted_data.address or (
        f"{extracted_data.venue}, {extracted_data.location}"
        if extracted_data.location else ""
    )
    if dest_addr:
        extracted_data.est_mileage = get_driving_distance_miles(dest_addr)

    # Fallback venue name based on prefix if missing
    if not extracted_data.venue:
        extracted_data.venue = prefix

    # 4. Save single CSV row for the whole group
    csv_path = OUTPUTS_DIR / f"{prefix}.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_HEADERS)
        writer.writeheader()
        writer.writerow(extracted_data.model_dump(by_alias=True))

    # 5. Archive all files in the group
    for fp in file_paths:
        target = COMPLETE_DIR / fp.name
        try:
            fp.rename(target)
        except Exception as e:
            logger.warning(f"Could not move {fp} to {target}: {e}")

    logger.info(f"Successfully processed group {prefix}")
    return True

def main():
    parser = argparse.ArgumentParser(description="AI-tinerary Contract Processor")
    parser.add_argument("--process-only", action="store_true", help="Only process files, do not combine CSVs")
    parser.add_argument("--combine-only", action="store_true", help="Only combine existing CSVs, do not process files")
    args = parser.parse_args()

    setup_dirs()

    if not args.combine_only:
        files = [p for p in CONTRACTS_DIR.glob("*") if p.suffix.lower() in (".pdf", ".eml")]
        if not files:
            logger.info(f"No contract files found in {CONTRACTS_DIR}")
        else:
            groups = group_files_by_prefix(files)
            group_items = list(groups.items())
            logger.info(
                f"Found {len(files)} files in {len(group_items)} group(s). "
                f"Starting processing with {MAX_THREADS} threads..."
            )

            with ThreadPoolExecutor(max_workers=MAX_THREADS) as executor:
                futures = {
                    executor.submit(process_group, prefix, paths): prefix
                    for prefix, paths in group_items
                }
                for future in as_completed(futures):
                    future.result()

    if not args.process_only:
        combine_csvs()
        
    logger.info("Workflow complete.")

if __name__ == "__main__":
    main()