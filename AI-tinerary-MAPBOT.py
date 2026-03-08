#!/usr/bin/env python3
"""
AI-tinerary MAPBOT: Your Logistics-Driven AI Tour Manager

MAPBOT handles:
- Geocoding venue and accommodation addresses.
- Calculating driving routes, distances, and ETAs.
- Interactively managing accommodation details via Discord.
- Updating master-output.csv with Routing and Mileage info.
"""

import os
import csv
import json
import logging
import asyncio
import difflib
from pathlib import Path
from datetime import datetime, timedelta

import requests
import openrouteservice
from geopy.geocoders import Nominatim
from geopy.distance import geodesic
from dotenv import load_dotenv

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# ------------------------------------------------------------------
# Configuration & Paths
# ------------------------------------------------------------------

ROOT_DIR = Path(__file__).resolve().parent
OUTPUTS_DIR = ROOT_DIR / "Outputs"
MASTER_CSV = OUTPUTS_DIR / "master-output.csv"
BACKUPS_DIR = OUTPUTS_DIR / "Backups"

# Load Config
load_dotenv(override=True)
load_dotenv(dotenv_path=ROOT_DIR / "Master Config.txt", override=True)

HOME_BASE_ADDRESS = os.getenv("HOME_BASE_ADDRESS", "")
ORS_API_KEY = os.getenv("ORS_API_KEY", "")
ORS_BASE_URL = os.getenv("ORS_BASE_URL", "")

# Initialize Geocoder
geolocator = Nominatim(user_agent="ai-tinerary-mapbot")

# ------------------------------------------------------------------
# Routing Utilities (Ported/Enhanced from CSV Script)
# ------------------------------------------------------------------

def get_coords(address: str):
    """Resolve an address to [longitude, latitude] using Nominatim."""
    if not address or str(address).strip() == "": return None
    try:
        location = geolocator.geocode(address, timeout=10)
        if location:
            return [location.longitude, location.latitude]
    except Exception as e:
        logger.error(f"Geocoding error for '{address}': {e}")
    return None

def get_driving_data(dest_coords, origin_coords):
    """
    Get driving distance (miles) and duration (seconds) from ORS.
    Returns: (miles, duration_seconds) or (miles_fallback, None)
    """
    if not dest_coords or not origin_coords: return None, None
    
    kwargs = {"key": ORS_API_KEY}
    if not ORS_API_KEY and ORS_BASE_URL:
        kwargs["base_url"] = ORS_BASE_URL
    
    if ORS_API_KEY or ORS_BASE_URL:
        try:
            client = openrouteservice.Client(**kwargs)
            route = client.directions(
                coordinates=[origin_coords, dest_coords],
                profile="driving-car",
                format="json"
            )
            meters = route["routes"][0]["summary"]["distance"]
            duration = route["routes"][0]["summary"]["duration"] # Seconds
            return meters / 1609.34, duration
        except Exception as e:
            logger.error(f"ORS Routing failed: {e}")
    
    # Fallback to geodesic (straight-line) distance
    try:
        dist_miles = geodesic((origin_coords[1], origin_coords[0]), (dest_coords[1], dest_coords[0])).miles
        return dist_miles * 1.25, None # 25% overhead for driving
    except Exception as e:
        logger.error(f"Geodesic fallback failed: {e}")
    
    return None, None

# ------------------------------------------------------------------
# Tour Context Logic
# ------------------------------------------------------------------

def get_sorted_gigs():
    if not MASTER_CSV.exists(): return []
    try:
        with open(MASTER_CSV, "r", newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            # Sort by Starting Date
            rows.sort(key=lambda x: x.get("Starting Date", ""))
            return rows
    except Exception as e:
        logger.error(f"Failed to read master CSV for context: {e}")
        return []

def get_previous_gig(gigs, current_gig):
    current_date = current_gig.get("Starting Date")
    prev_gig = None
    for gig in gigs:
        if gig.get("Starting Date") < current_date:
            prev_gig = gig
        else:
            break
    return prev_gig

# ------------------------------------------------------------------
# MAPBOT Core Logic
# ------------------------------------------------------------------

async def plan_route_for_gig(gig, gigs):
    """
    1. Determine Origin (Prev gig or Home Base)
    2. Geocode Addresses
    3. Calculate Route/Mileage/ETA
    4. Store in Routing/Mileage fields
    """
    prev_gig = get_previous_gig(gigs, gig)
    
    origin_name = "Home"
    origin_address = HOME_BASE_ADDRESS
    
    if prev_gig:
        # Check if they stayed at an accommodation
        if prev_gig.get("Accom Address"):
            origin_name = f"Hotel ({prev_gig.get('Venue')})"
            origin_address = prev_gig.get("Accom Address")
        else:
            origin_name = prev_gig.get("Venue")
            origin_address = prev_gig.get("Address") or prev_gig.get("Location")

    dest_name = gig.get("Venue")
    dest_address = gig.get("Address") or gig.get("Location")
    
    logger.info(f"Routing for {dest_name}: {origin_name} -> {dest_name}")
    
    origin_coords = get_coords(origin_address)
    dest_coords = get_coords(dest_address)
    
    miles, duration = get_driving_data(dest_coords, origin_coords)
    
    if miles is not None:
        gig["Mileage"] = f"{miles:.2f}"
        routing_str = f"{origin_name} -> {dest_name}"
        
        if duration:
            hours = int(duration // 3600)
            minutes = int((duration % 3600) // 60)
            routing_str += f" ({hours}h {minutes}m)"
            
            # Calculate departure time if Load In exists
            load_in_str = gig.get("Load In")
            if load_in_str:
                try:
                    # Simple parser for "HH:MM" or "HH:MM AM/PM"
                    from dateutil import parser
                    load_in_time = parser.parse(load_in_str)
                    departure_time = load_in_time - timedelta(seconds=duration)
                    # Add buffer (e.g., 30 mins)
                    departure_time -= timedelta(minutes=30)
                    gig["Other Details"] = (gig.get("Other Details", "") + 
                        f"\n[MAPBOT]: Recommended Departure: {departure_time.strftime('%I:%M %p')} (includes 30m buffer)").strip()
                except:
                    pass
        
        gig["Routing"] = routing_str
        return True
    
    return False

# ------------------------------------------------------------------
# CSV Persistence (Shared with CALBOT pattern)
# ------------------------------------------------------------------

def update_master_csv_atomic(rows):
    """Atomically update master CSV."""
    if MASTER_CSV.exists():
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup_path = BACKUPS_DIR / f"master-output-mapbot-{timestamp}.csv"
        shutil.copy(MASTER_CSV, backup_path)

    # We need the full headers from CALBOT
    spec = importlib.util.spec_from_file_location("calbot", ROOT_DIR / "AI-tinerary-CALBOT.py")
    calbot = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(calbot)
    fieldnames = calbot.ALL_HEADERS

    temp_csv = MASTER_CSV.with_suffix(".tmp")
    try:
        with open(temp_csv, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction='ignore')
            writer.writeheader()
            writer.writerows(rows)
        temp_csv.replace(MASTER_CSV)
        return True
    except Exception as e:
        logger.error(f"Failed to update master CSV: {e}")
        return False

# ------------------------------------------------------------------
# Bot Interaction Glue
# ------------------------------------------------------------------

# This will be called by AI-tinerary-CALBOT.py or run standalone
if __name__ == "__main__":
    # Standalone mode: Process all pending gigs
    gigs = get_sorted_gigs()
    updated = False
    for gig in gigs:
        if not gig.get("Routing") or not gig.get("Mileage"):
            if asyncio.run(plan_route_for_gig(gig, gigs)):
                updated = True
    
    if updated:
        update_master_csv_atomic(gigs)
        print("MAPBOT: Routing updates complete.")
    else:
        print("MAPBOT: No pending routing found.")
