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
import shutil
import importlib.util
from pathlib import Path
from datetime import datetime, timedelta

import requests
import openrouteservice
from geopy.geocoders import Nominatim
from geopy.distance import geodesic
from dotenv import load_dotenv

# Import constants
from constants import (
    ROOT_DIR, OUTPUTS_DIR, MASTER_CSV, BACKUPS_DIR, ALL_HEADERS, get_master_lock
)

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# ------------------------------------------------------------------
# Configuration & Paths
# ------------------------------------------------------------------

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

def get_coords(address: str, venue: str = None, location: str = None):
    """
    Resolve an address to [longitude, latitude] using Nominatim.
    Implements fallbacks for venue and location.
    """
    queries = []
    if address: queries.append(address)
    if venue and location: queries.append(f"{venue}, {location}")
    if venue: queries.append(venue)
    
    for query in queries:
        if not query or str(query).strip() == "": continue
        try:
            location_res = geolocator.geocode(query, timeout=10)
            if location_res:
                logger.info(f"Resolved '{query}' to [{location_res.longitude}, {location_res.latitude}]")
                return [location_res.longitude, location_res.latitude]
        except Exception as e:
            logger.error(f"Geocoding error for '{query}': {e}")
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
    2. Geocode Addresses (with Fallbacks)
    3. Calculate Route/Mileage/ETA
    4. Apply Dynamic Buffer (15m per 2h)
    5. Detect Conflicts with Previous Gig
    6. Store in Routing/Mileage fields
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
    dest_loc = gig.get("Location")
    
    logger.info(f"Routing for {dest_name}: {origin_name} -> {dest_name}")
    
    # 2. Geocode with Fallbacks
    origin_coords = get_coords(origin_address)
    dest_coords = get_coords(dest_address, venue=dest_name, location=dest_loc)
    
    # 3. Get Data
    miles, duration = get_driving_data(dest_coords, origin_coords)
    
    if miles is not None:
        gig["Mileage"] = f"{miles:.2f}"
        routing_str = f"{origin_name} -> {dest_name}"
        
        if duration:
            hours_drive = duration / 3600
            # 4. Dynamic Buffer: 15 mins per 2 hours
            buffer_mins = int((hours_drive / 2.0) * 15)
            # Minimum 15m buffer if > 0
            if hours_drive > 0: buffer_mins = max(15, buffer_mins)
            
            total_duration_with_buffer = duration + (buffer_mins * 60)
            
            h = int(duration // 3600)
            m = int((duration % 3600) // 60)
            routing_str += f" ({h}h {m}m)"
            
            # 5. Conflict Detection
            from dateutil import parser
            load_in_str = gig.get("Load In")
            if load_in_str:
                try:
                    load_in_time = parser.parse(f"{gig.get('Starting Date')} {load_in_str}")
                    departure_time = load_in_time - timedelta(seconds=total_duration_with_buffer)
                    
                    # Check against prev gig end
                    if prev_gig:
                        prev_end_str = prev_gig.get("Calendar End")
                        if prev_end_str:
                            prev_end_dt = parser.parse(prev_end_str)
                            if departure_time < prev_end_dt:
                                warning = f"\n[CRITICAL WARNING: Drive time ({h}h {m}m + {buffer_mins}m buffer) exceeds available window!]"
                                if warning not in gig.get("Other Details", ""):
                                    gig["Other Details"] = (gig.get("Other Details", "") + warning).strip()
                    
                    gig["Other Details"] = (gig.get("Other Details", "") + 
                        f"\n[MAPBOT]: Recommended Departure: {departure_time.strftime('%I:%M %p')} (includes {buffer_mins}m dynamic buffer)").strip()
                except Exception as e:
                    logger.warning(f"Conflict detection failed for {dest_name}: {e}")
        
        gig["Routing"] = routing_str
        return True
    
    return False

# ------------------------------------------------------------------
# CSV Persistence (Shared with CALBOT pattern)
# ------------------------------------------------------------------

def update_master_csv_atomic(rows):
    """Atomically update master CSV with File Locking."""
    with get_master_lock():
        if MASTER_CSV.exists():
            timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            backup_path = BACKUPS_DIR / f"master-output-mapbot-{timestamp}.csv"
            shutil.copy(MASTER_CSV, backup_path)

        temp_csv = MASTER_CSV.with_suffix(".tmp")
        try:
            with open(temp_csv, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=ALL_HEADERS, extrasaction='ignore')
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
