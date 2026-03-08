#!/usr/bin/env python3
"""
AI-tinerary: Advanced Contract Processing Pipeline

Stack (Best Free Industry Practice):
- Ollama (local model) for contract parsing.
- geopy (Nominatim) for free, high-quality Geocoding.
- openrouteservice (Local container or Public API) for driving distance & ETAs.
- Pydantic for strict schema validation.
"""

import csv
import json
import logging
import argparse
import os
from pathlib import Path
from io import BytesIO
from email import policy
from email.parser import BytesParser
from collections import defaultdict

import requests
from pypdf import PdfReader
import openrouteservice
from geopy.geocoders import Nominatim
from geopy.exc import GeopyError
from geopy.distance import geodesic
from pydantic import BaseModel, Field, ValidationError, ConfigDict
from dotenv import load_dotenv

# ------------- CONFIGURATION & SETUP -------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger(__name__)

ROOT_DIR = Path(__file__).resolve().parent
CONTRACTS_DIR = ROOT_DIR / "Contracts" / "Incoming"
OUTPUTS_DIR = ROOT_DIR / "Outputs"
BITS_DIR = OUTPUTS_DIR / "Bits"
COMPLETE_DIR = ROOT_DIR / "Contracts" / "Complete"

# Load Master Config.txt with absolute priority
config_file = ROOT_DIR / "Master Config.txt"
if config_file.exists():
    logger.info(f"Loading Master Config from {config_file}")
    load_dotenv(dotenv_path=config_file, override=True)
else:
    load_dotenv(override=True)

# Env Vars
HOME_BASE_ADDRESS = os.getenv("HOME_BASE_ADDRESS", "")
ORS_API_KEY = os.getenv("ORS_API_KEY", "")
ORS_BASE_URL = os.getenv("ORS_BASE_URL", "")
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434/api/generate")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "ministral-3:3b")

# Explicit Routing Mode Logging
if ORS_API_KEY:
    logger.info("ROUTING MODE: Public API (Full US Maps enabled)")
else:
    logger.info(f"ROUTING MODE: Local Docker at {ORS_BASE_URL or 'http://localhost:8080'}")

logger.info(f"HOME_BASE: '{HOME_BASE_ADDRESS}'")

# Initialize Geocoder
geolocator = Nominatim(user_agent="ai-tinerary-tour-manager")

# ------------- SCHEMA VALIDATION -------------

class ContractData(BaseModel):
    """Pydantic model to strictly enforce the output schema and defaults."""
    model_config = ConfigDict(populate_by_name=True)

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
    accommodations: str = Field(default="", alias="Accomodations")
    accom_address: str = Field(default="", alias="Accom Address")
    est_mileage: str = Field(default="", alias="Est. Mileage")
    time: str = Field(default="", alias="Time")
    doors: str = Field(default="", alias="Doors")
    load_in: str = Field(default="", alias="Load In")
    pay: str = Field(default="", alias="Pay")
    sound_person: str = Field(default="", alias="Sound - Person")
    sound_system: str = Field(default="", alias="Sound - System")
    other_expenses: str = Field(default="", alias="Other Expenses")

CSV_HEADERS = [ContractData.model_fields[k].alias or k for k in ContractData.model_fields.keys()]

# ------------- SERVICES & LOGIC -------------

def get_coords(address: str):
    """Resolve an address to [longitude, latitude] using Nominatim."""
    if not address: return None
    try:
        location = geolocator.geocode(address, timeout=10)
        if location:
            logger.info(f"Resolved '{address}' to [{location.longitude}, {location.latitude}]")
            return [location.longitude, location.latitude]
        else:
            logger.warning(f"Could not resolve address: '{address}'")
    except Exception as e:
        logger.error(f"Geocoding error for '{address}': {e}")
    return None

def get_driving_miles(dest_coords, origin_coords):
    """Get driving distance from ORS (Public or Local). Fallback to straight-line distance if ORS fails."""
    if not dest_coords or not origin_coords: return ""
    
    # Try ORS first
    kwargs = {"key": ORS_API_KEY}
    if not ORS_API_KEY and ORS_BASE_URL:
        kwargs["base_url"] = ORS_BASE_URL
    
    # Only try ORS if we have a key or a local URL
    if ORS_API_KEY or ORS_BASE_URL:
        try:
            client = openrouteservice.Client(**kwargs)
            route = client.directions(
                coordinates=[origin_coords, dest_coords],
                profile="driving-car",
                format="json",
                radiuses=[5000, 5000]
            )
            meters = route["routes"][0]["summary"]["distance"]
            return f"{(meters / 1609.34):.2f}"
        except Exception as e:
            logger.error(f"ORS Routing failed: {e}")
    
    # Fallback to geodesic (straight-line) distance
    try:
        # geodesic takes (lat, lon)
        dist_miles = geodesic((origin_coords[1], origin_coords[0]), (dest_coords[1], dest_coords[0])).miles
        # Add 25% for estimated driving distance overhead
        est_driving = dist_miles * 1.25
        logger.info(f"Mileage fallback (Geodesic + 25%): {est_driving:.2f} miles")
        return f"{est_driving:.2f}"
    except Exception as e:
        logger.error(f"Geodesic fallback failed: {e}")
    
    return ""

def process_mileage(data: ContractData):
    """Coordinate the Geocoding and Routing workflow with fallbacks."""
    # 1. Resolve Home Base
    origin_coords = get_coords(HOME_BASE_ADDRESS)
    if not origin_coords:
        logger.warning("Mileage skipped: Home Base not found.")
        return

    # 2. Resolve Destination (Try multiple search strategies)
    dest_coords = None
    search_queries = [
        data.address,
        data.location,
        f"{data.venue}, {data.location}" if data.location else None
    ]
    
    for query in search_queries:
        if not query: continue
        dest_coords = get_coords(query)
        if dest_coords: break
    
    # 3. Get Distance
    if dest_coords:
        data.est_mileage = get_driving_miles(dest_coords, origin_coords)
    else:
        logger.warning("Mileage skipped: Destination not found.")

def call_ollama_extract(text: str) -> ContractData:
    """Extract show data via local AI with strict formatting."""
    system = f"""
Extract tour contract details into a JSON object with these EXACT keys: {json.dumps(CSV_HEADERS)}.
RULES:
1. Values must be simple strings.
2. Join multiple values with commas.
3. Return ONLY raw JSON.
"""
    try:
        r = requests.post(OLLAMA_URL, json={"model": OLLAMA_MODEL, "prompt": f"{system}\n\nTEXT:\n{text}", "stream": False, "format": "json"}, timeout=180)
        r.raise_for_status()
        raw_json = json.loads(r.json().get("response", "{}"))
        # Clean the dict to match Pydantic model (some LLMs might return aliases or attribute names)
        # We'll use populate_by_name=True in Pydantic Config to handle aliases.
        return ContractData(**raw_json)
    except Exception as e:
        logger.error(f"AI Extraction failed: {e}")
        return ContractData()

# ------------- CORE WORKFLOW -------------

def process_group(prefix, paths):
    logger.info(f"Processing group: {prefix}")
    
    try:
        # 1. Gather Text
        full_text = ""
        for p in sorted(paths):
            if p.suffix.lower() == ".pdf":
                reader = PdfReader(BytesIO(p.read_bytes()))
                full_text += "\n\n".join(page.extract_text() or "" for page in reader.pages)
            else:
                with open(p, "rb") as f:
                    msg = BytesParser(policy=policy.default).parse(f)
                    body = msg.get_body(preferencelist=('plain'))
                    if body:
                        full_text += f"{msg['subject']}\n{body.get_content()}"

        # 2. AI Extract
        data = call_ollama_extract(full_text)
        
        # 3. Mileage
        process_mileage(data)
        
        # 4. Save to Bits
        csv_path = BITS_DIR / f"{prefix}.csv"
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=CSV_HEADERS)
            writer.writeheader()
            writer.writerow(data.model_dump(by_alias=True))
            
        # 5. Archive
        for p in paths:
            p.rename(COMPLETE_DIR / p.name)
        logger.info(f"Success: {prefix}")
        return True
    except Exception as e:
        logger.error(f"Failed to process {prefix}: {e}")
        return False

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--update-mileage", action="store_true")
    args = parser.parse_args()

    for d in [CONTRACTS_DIR, OUTPUTS_DIR, BITS_DIR, COMPLETE_DIR]: d.mkdir(parents=True, exist_ok=True)

    if args.update_mileage:
        csv_paths = list(BITS_DIR.glob("*.csv"))
        for p in csv_paths:
            rows = []
            try:
                with open(p, "r", newline="", encoding="utf-8") as f:
                    reader = csv.DictReader(f)
                    rows = list(reader)
                
                updated = False
                for row in rows:
                    if not row.get("Est. Mileage") or row.get("Est. Mileage") == "0.00":
                        # Convert row to ContractData for process_mileage
                        data = ContractData(**row)
                        process_mileage(data)
                        # Update row from data
                        updated_row = data.model_dump(by_alias=True)
                        row.update(updated_row)
                        updated = True
                
                if updated:
                    with open(p, "w", newline="", encoding="utf-8") as f:
                        writer = csv.DictWriter(f, fieldnames=reader.fieldnames)
                        writer.writeheader()
                        writer.writerows(rows)
            except Exception as e:
                logger.error(f"Failed to update mileage for {p.name}: {e}")
    else:
        files = [p for p in CONTRACTS_DIR.glob("*") if p.suffix.lower() in (".pdf", ".eml")]
        if not files:
            logger.info("No files found in Incoming/")
            return
            
        groups = defaultdict(list)
        for f in files:
            prefix = f.name.split(" - ", 1)[0] if " - " in f.name else f.stem
            groups[prefix].append(f)
        
        # Simple loop for clarity during testing
        for pref, paths in groups.items():
            process_group(pref, paths)

if __name__ == "__main__":
    main()
