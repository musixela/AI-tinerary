#!/usr/bin/env python3
"""
Process contract PDFs and EMLs and generate per‑show CSVs ready to paste into your AI template sheet.

Stack:
- Ollama (local model) for contract parsing.
- openrouteservice (FOSS routing engine + free API) for driving mileage.

Requirements (install once in your venv):
    pip install pypdf requests openrouteservice

Make sure Ollama is installed and running:
    https://ollama.com
    ollama serve
    ollama pull ministral-3:3b   # or another text-capable model you like
"""

import csv
import json
from pathlib import Path
from io import BytesIO
from email import policy
from email.parser import BytesParser

import requests
from pypdf import PdfReader
import openrouteservice

# ------------- CONFIGURATION -------------

# Project root and folders inside the project
ROOT_DIR = Path(__file__).resolve().parent
CONTRACTS_DIR = ROOT_DIR / "Contracts" / "Incoming"

# Output directories and files (import or copy into your AI template sheet)
OUTPUTS_DIR = ROOT_DIR / "Outputs"

# Completed contracts move here after processing
COMPLETE_DIR = ROOT_DIR / "Contracts" / "Complete"

# Ollama settings
OLLAMA_URL = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "ministral-3:3b"  # change to any installed text model

# Fixed home base for mileage estimation
HOME_BASE_ADDRESS = "714 E Watauga Ave, Johnson City, TN 37601, United States"

# openrouteservice settings (FOSS routing engine with free hosted API)
ORS_API_KEY = "YOUR_OPENROUTESERVICE_API_KEY_HERE"

# Column headers matching Shows-AI-Template-2.csv EXACTLY [file:181]
SHEET_COLUMNS = [
    "Starting Date",
    "Ending Date",
    "Venue",
    "Location",
    "Booking",
    "MGMT",
    "Door Deal",
    "DD Notes",
    "Hospitality",
    "Contact Name",
    "Contact Details",
    "Other Details",
    "Address",
    "Accomodations",
    "Accom Address",
    "Est. Mileage",
    "Time",
    "Doors",
    "Load In",
    "Pay",
    "Sound - Person",
    "Sound - System",
    "Other Expenses",
]

# ------------- HELPERS -------------


def read_pdf_text(pdf_path: Path) -> str:
    """Extract all text from a PDF file on disk."""
    reader = PdfReader(str(pdf_path))
    texts = []
    for page in reader.pages:
        try:
            texts.append(page.extract_text() or "")
        except Exception:
            continue
    return "\n\n".join(texts)


def read_pdf_bytes_text(pdf_bytes: bytes) -> str:
    """Extract text from a PDF provided as raw bytes (for email attachments)."""
    reader = PdfReader(BytesIO(pdf_bytes))
    texts = []
    for page in reader.pages:
        try:
            texts.append(page.extract_text() or "")
        except Exception:
            continue
    return "\n\n".join(texts)


def read_eml_contract_text(eml_path: Path) -> str:
    """
    Extract combined text from an .eml file:
    - Subject, From, Date
    - Plain-text (or HTML) body
    - Any attached PDFs' text
    """
    with open(eml_path, "rb") as f:
        msg = BytesParser(policy=policy.default).parse(f)

    parts = []

    subj = msg["subject"] or ""
    frm = msg["from"] or ""
    date = msg["date"] or ""
    header_block = f"Subject: {subj}\nFrom: {frm}\nDate: {date}"
    parts.append(header_block)

    body = msg.get_body(preferencelist=("plain", "html"))
    if body:
        try:
            parts.append(body.get_content())
        except Exception:
            pass

    for attachment in msg.iter_attachments():
        ctype = attachment.get_content_type()
        filename = attachment.get_filename() or ""
        if ctype == "application/pdf" or filename.lower().endswith(".pdf"):
            try:
                pdf_bytes = attachment.get_content()
                pdf_text = read_pdf_bytes_text(pdf_bytes)
                if pdf_text.strip():
                    parts.append(pdf_text)
            except Exception as e:
                parts.append(f"[Attachment {filename} could not be read as PDF: {e}]")

    return "\n\n".join(parts)


def call_ollama_extract(contract_text: str) -> dict:
    """
    Ask the local model to extract structured data for the Shows AI template.

    IMPORTANT:
    - It must always return ALL keys in SHEET_COLUMNS.
    - If it can't fill a field, it must use "" (empty string), NOT null.
    - All values must be JSON strings.
    """

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

    prompt = system_instructions.strip() + "\n\nCONTRACT / EMAIL TEXT:\n\n" + contract_text

    payload = {
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False,
        "format": "json",  # ask Ollama to emit pure JSON
    }

    resp = requests.post(OLLAMA_URL, json=payload, timeout=120)
    resp.raise_for_status()
    data = resp.json()

    if isinstance(data, dict) and "response" in data:
        return json.loads(data["response"])
    else:
        return data


def get_ors_client():
    """Create an openrouteservice client."""
    if not ORS_API_KEY:
        return None
    return openrouteservice.Client(key=ORS_API_KEY)


def geocode_address_ors(client, address: str):
    """
    Geocode an address string to (lon, lat) using openrouteservice.
    Returns (lon, lat) or None on failure.
    """
    try:
        resp = client.pelias_search(text=address, size=1)
        features = resp.get("features", [])
        if not features:
            return None
        coords = features[0]["geometry"]["coordinates"]  # [lon, lat]
        return coords[0], coords[1]
    except Exception as e:
        print(f"  Warning: geocoding failed for '{address}' ({e})")
        return None


def get_driving_distance_miles_ors(origin_addr: str, dest_addr: str) -> str:
    """
    Use openrouteservice directions to get ONE-WAY driving distance in miles
    between origin and destination addresses.

    Returns a string like "122.14" (miles, 2 decimal places) or "" on failure.
    """
    client = get_ors_client()
    if client is None:
        return ""

    origin_coords = geocode_address_ors(client, origin_addr)
    dest_coords = geocode_address_ors(client, dest_addr)

    if not origin_coords or not dest_coords:
        return ""

    try:
        coords = [origin_coords, dest_coords]  # [[lon, lat], [lon, lat]]
        route = client.directions(
            coordinates=coords,
            profile="driving-car",
            format="json",
        )
        distance_meters = route["routes"][0]["summary"]["distance"]
        miles = distance_meters / 1609.34
        return f"{miles:.2f}"
    except Exception as e:
        print(f"  Warning: routing failed ({e})")
        return ""


def ensure_output_dirs():
    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    CONTRACTS_DIR.mkdir(parents=True, exist_ok=True)
    COMPLETE_DIR.mkdir(parents=True, exist_ok=True)


# ------------- MAIN PIPELINE -------------


def process_contracts():
    ensure_output_dirs()

    # Process both PDFs and EMLs in the incoming folder
    files = sorted(CONTRACTS_DIR.glob("*"))
    if not files:
        print(f"No contract files (.pdf or .eml) found in {CONTRACTS_DIR}")
        return

    for file_path in files:
        suffix = file_path.suffix.lower()
        if suffix not in (".pdf", ".eml"):
            continue

        print(f"Processing: {file_path.name}")

        if suffix == ".pdf":
            text = read_pdf_text(file_path)
        else:  # .eml
            text = read_eml_contract_text(file_path)

        if not text.strip():
            print(f"  Warning: no text extracted from {file_path.name}, skipping.")
            continue

        try:
            extracted = call_ollama_extract(text)
        except Exception as e:
            print(f"  Error calling local model for {file_path.name}: {e}")
            extracted = {col: "" for col in SHEET_COLUMNS}
            if "Venue" in extracted:
                extracted["Venue"] = file_path.stem
            if "Other Details" in extracted:
                extracted["Other Details"] = f"Extraction failed: {e}"

        # Ensure ALL expected keys exist and are strings.
        for col in SHEET_COLUMNS:
            val = extracted.get(col, "")
            if val is None:
                val = ""
            if not isinstance(val, str):
                val = str(val)
            extracted[col] = val

        # Normalize booleans to "TRUE"/"FALSE" for Booking, MGMT, Door Deal.
        for flag_col in ("Booking", "MGMT", "Door Deal"):
            val = extracted.get(flag_col, "")
            if isinstance(val, str):
                v = val.strip().lower()
                if v in ("true", "yes", "y", "1"):
                    extracted[flag_col] = "TRUE"
                elif v in ("false", "no", "n", "0"):
                    extracted[flag_col] = "FALSE"
                elif v == "":
                    extracted[flag_col] = "FALSE"
                else:
                    extracted[flag_col] = val
            else:
                extracted[flag_col] = "FALSE"

        # Compute Est. Mileage using openrouteservice, overriding whatever the model put there.
        venue = extracted.get("Venue", "").strip()
        location = extracted.get("Location", "").strip()
        addr_field = extracted.get("Address", "").strip()
        destination_addr = addr_field or (f"{venue}, {location}" if location else "")

        if destination_addr and ORS_API_KEY:
            print(f"  Looking up driving distance to: {destination_addr}")
            est_mileage = get_driving_distance_miles_ors(
                HOME_BASE_ADDRESS, destination_addr
            )
            if est_mileage:
                extracted["Est. Mileage"] = est_mileage

        # Build row in the correct column order
        row = [extracted.get(col, "") for col in SHEET_COLUMNS]

        # Write a CSV just for this file, named after the file stem.
        csv_path = OUTPUTS_DIR / f"{file_path.stem}.csv"
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(SHEET_COLUMNS)
            writer.writerow(row)
        print(f"Wrote 1 row to {csv_path}")

        # Move the processed file to the complete folder.
        dest = COMPLETE_DIR / file_path.name
        try:
            file_path.rename(dest)
            print(f"Moved {file_path.name} to {dest}")
        except Exception as e:
            print(f"  Warning: failed to move {file_path.name} ({e})")

    print("\nAll done.")


if __name__ == "__main__":
    process_contracts()
