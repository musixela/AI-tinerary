#!/usr/bin/env python3
"""
AI-tinerary CALBOT: Your Event-Driven AI Tour Manager

This rewritten bot watches your `Outputs/Bits` folder for new contract CSVs.
When a new file appears, it notifies a specific Discord channel. You can then
interactively review and fill missing details in a thread before finalizing.

Workflow:
1.  Watch `Outputs/Bits` for new .csv files.
2.  Post "New Contract Found" message in configured channel.
3.  User clicks "Review" -> Bot creates a Thread.
4.  Bot asks for missing fields (interactive Q&A).
5.  User confirms -> Bot appends to `master-output.csv`, creates Calendar events,
    and moves file to `Outputs/Bits/Processed`.
"""

import os
import csv
import json
import asyncio
import logging
import shutil
import difflib
from pathlib import Path
from datetime import datetime
import importlib.util

import requests
from dotenv import load_dotenv

# Import constants
from constants import (
    ROOT_DIR, OUTPUTS_DIR, BITS_DIR, PROCESSED_DIR, MASTER_CSV,
    STATE_FILE, BACKUPS_DIR, LOGS_DIR, ALL_HEADERS, CSV_HEADERS,
    WORKFLOW_FIELDS, get_master_lock
)

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# Suppress noisy libraries
logging.getLogger('discord').setLevel(logging.WARNING)
logging.getLogger('discord.voice_client').setLevel(logging.ERROR)

import discord
from discord.ext import commands, tasks

# Google Calendar Imports
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

# ------------------------------------------------------------------
# Configuration & Paths
# ------------------------------------------------------------------

# Load Config
load_dotenv(override=True)
load_dotenv(dotenv_path=ROOT_DIR / "Master Config.txt", override=True)

DISCORD_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
DISCORD_CHANNEL_ID = os.getenv("DISCORD_CHANNEL_ID")
GOOGLE_SERVICE_ACCOUNT_FILE = os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE")
BAND_CALENDAR_ID = os.getenv("BAND_CALENDAR_ID")
PUBLIC_CALENDAR_ID = os.getenv("PUBLIC_CALENDAR_ID")
TIMEZONE = os.getenv("TIMEZONE", "America/New_York")

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434/api/generate")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "ministral-3:3b")

SCOPES = ["https://www.googleapis.com/auth/calendar"]

# Import extraction logic from CSV script
_csv_spec = importlib.util.spec_from_file_location("aitin_csv", ROOT_DIR / "AI-tinerary-CSV.py")
_ai_csv = importlib.util.module_from_spec(_csv_spec)
_csv_spec.loader.exec_module(_ai_csv)
call_ollama_extract = _ai_csv.call_ollama_extract

# Import mapbot module
_map_spec = importlib.util.spec_from_file_location("mapbot", ROOT_DIR / "AI-tinerary-MAPBOT.py")
mapbot = importlib.util.module_from_spec(_map_spec)
_map_spec.loader.exec_module(mapbot)


# ------------------------------------------------------------------
# Stage 1: Row Matching
# ------------------------------------------------------------------

def find_matching_row(master_rows: list, new_row: dict) -> int:
    """
    Matching logic (in order of priority):
    1. Exact match: Same Event Date + exact Venue string
    2. Fuzzy match: Same Event Date + fuzzy Venue (>80% similarity)
    3. Fallback: Same Event Date + same City + same Contact Name
    Returns: Row index in master_rows, or -1 if new gig
    """
    new_date = new_row.get("Starting Date")
    new_venue = new_row.get("Venue")
    new_location = new_row.get("Location", "") # Often City, State
    new_contact = new_row.get("Contact Name", "")

    if not new_date:
        return -1

    for i, row in enumerate(master_rows):
        row_date = row.get("Starting Date")
        row_venue = row.get("Venue")
        row_location = row.get("Location", "")
        row_contact = row.get("Contact Name", "")

        if row_date != new_date:
            continue

        # 1. Exact Venue Match
        if row_venue == new_venue:
            # Check Start Time to disambiguate multiple shows same day
            new_time = new_row.get("Time")
            row_time = row.get("Time")
            if new_time and row_time and new_time != row_time:
                # Might be a different show on the same day?
                # For now, if venue and date match, we'll consider it a match 
                # unless times are explicitly different and both present.
                pass
            return i

        # 2. Fuzzy Venue Match
        if row_venue and new_venue:
            similarity = difflib.SequenceMatcher(None, row_venue, new_venue).ratio()
            if similarity > 0.8:
                return i

        # 3. Fallback: Same Date + Location + Contact
        if row_location == new_location and row_contact == new_contact and new_location and new_contact:
            return i

    return -1

# ------------------------------------------------------------------
# Stage 2: Field Merge Logic
# ------------------------------------------------------------------

def merge_fields(existing: dict, new: dict) -> dict:
    """
    CALBOT-managed fields (merge rules):
    Field Rule: Newest non-empty
    Preserve existing: Routing, Mileage, Workflow states
    Returns: Merged row dict
    """
    merged = existing.copy()
    
    # Fields that CALBOT manages (overwrite if new is non-empty)
    managed_fields = list(CSV_HEADERS)
    
    # Remove fields that should be preserved (MAPBOT or Workflow managed)
    to_preserve = ["Routing", "Mileage", "Est. Mileage", "Discord Finished", "Calendar Created", "Public Calendar Created"]
    
    for field in managed_fields:
        if field in to_preserve:
            continue
        
        new_val = new.get(field)
        if new_val and str(new_val).strip():
            merged[field] = new_val

    # Special handling for Notes/Other Details (Append)
    new_notes = new.get("Other Details")
    old_notes = existing.get("Other Details")
    if new_notes and str(new_notes).strip() and new_notes != old_notes:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if old_notes:
            merged["Other Details"] = f"{old_notes}\n[{timestamp} UPDATE]: {new_notes}"
        else:
            merged["Other Details"] = new_notes

    return merged

# ------------------------------------------------------------------
# Stage 3: Changelog Generation
# ------------------------------------------------------------------

def generate_changelog(old: dict, merged: dict) -> dict:
    """
    Purpose: Human-readable summary of changes for Discord notification
    Returns None if no meaningful changes detected
    """
    changed_fields = []
    summary_lines = []
    needs_mapbot = False
    needs_calendar_update = False

    # Fields to monitor for changes
    monitor_fields = {
        "Starting Date": "needs_calendar_update",
        "Ending Date": "needs_calendar_update",
        "Time": "needs_calendar_update",
        "Venue": "needs_calendar_update",
        "Address": "needs_mapbot",
        "Location": "needs_mapbot",
        "Pay": None,
        "Contact Name": None,
        "Load In": None,
        "Doors": None,
        "Accomodations": None,
        "Accom Address": "needs_mapbot"
    }

    for field, effect in monitor_fields.items():
        old_val = str(old.get(field, "")).strip()
        new_val = str(merged.get(field, "")).strip()

        if new_val and old_val != new_val:
            # Ignore "empty -> value" for some fields if we want, 
            # but usually first-time population is fine to skip in "changelog" 
            # if we are in "Update" mode.
            if not old_val:
                continue

            changed_fields.append(field)
            summary_lines.append(f"{field}: {old_val} -> {new_val}")
            
            if effect == "needs_mapbot":
                needs_mapbot = True
            if effect == "needs_calendar_update":
                needs_calendar_update = True

    if not changed_fields:
        return None

    return {
        "changed_fields": changed_fields,
        "summary_lines": summary_lines,
        "needs_mapbot": needs_mapbot,
        "needs_calendar_update": needs_calendar_update
    }

# ------------------------------------------------------------------
# Stage 4: CSV Persistence
# ------------------------------------------------------------------

def update_master_csv(new_row: dict, source_file: str) -> dict:
    """
    Atomic write process with File Locking:
    1. Lock master CSV
    2. Backup master CSV
    3. Load current rows
    4. Match & Merge
    5. Write temp & rename
    6. Log action
    """
    with get_master_lock():
        # 2. Backup
        if MASTER_CSV.exists():
            timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            backup_path = BACKUPS_DIR / f"master-output-{timestamp}.csv"
            shutil.copy(MASTER_CSV, backup_path)

        # 3. Load
        master_rows = []
        if MASTER_CSV.exists():
            try:
                with open(MASTER_CSV, "r", newline="", encoding="utf-8") as f:
                    reader = csv.DictReader(f)
                    master_rows = list(reader)
            except Exception as e:
                logger.error(f"Failed to read master CSV: {e}")

        # 4. Match
        row_index = find_matching_row(master_rows, new_row)
        
        action = "appended"
        changelog = None
        needs_mapbot = False
        needs_calendar_update = False
        merged_row = new_row.copy()

        if row_index >= 0:
            action = "updated"
            old_row = master_rows[row_index]
            merged_row = merge_fields(old_row, new_row)
            changelog = generate_changelog(old_row, merged_row)
            
            if changelog:
                needs_mapbot = changelog.get("needs_mapbot", False)
                needs_calendar_update = changelog.get("needs_calendar_update", False)
            else:
                # No changes detected
                action = "ignored"
            
            master_rows[row_index] = merged_row
        else:
            # Append new row, ensure all headers are present
            full_new_row = {h: "" for h in ALL_HEADERS}
            full_new_row.update(new_row)
            master_rows.append(full_new_row)
            merged_row = full_new_row

        # 5. Write
        temp_csv = MASTER_CSV.with_suffix(".tmp")
        try:
            with open(temp_csv, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=ALL_HEADERS, extrasaction='ignore')
                writer.writeheader()
                writer.writerows(master_rows)
            temp_csv.replace(MASTER_CSV)
        except Exception as e:
            logger.error(f"Failed to write master CSV: {e}")
            return {"action": "failed", "error": str(e)}

    # 6. Log Action
    log_entry = {
        "timestamp": datetime.now().isoformat(),
        "source": source_file,
        "action": action,
        "row_index": row_index if row_index >= 0 else len(master_rows)-1,
        "needs_mapbot": needs_mapbot,
        "needs_calendar_update": needs_calendar_update
    }
    with open(LOGS_DIR / "calbot-updates.jsonl", "a") as f:
        f.write(json.dumps(log_entry) + "\n")

    return {
        "action": action,
        "row_index": row_index if row_index >= 0 else len(master_rows)-1,
        "changelog": changelog,
        "needs_mapbot": needs_mapbot,
        "needs_calendar_update": needs_calendar_update,
        "merged_row": merged_row
    }

# ------------------------------------------------------------------
# Utilities
# ------------------------------------------------------------------

def read_csv_row(path: Path):
    try:
        with open(path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            return next(reader)
    except Exception as e:
        logger.error(f"Failed to read CSV {path}: {e}")
        return {}

def write_csv_row(path: Path, row: dict):
    # Ensure all original headers plus calendar fields are present
    fieldnames = list(CSV_HEADERS)
    if "Calendar Start" not in fieldnames: fieldnames.append("Calendar Start")
    if "Calendar End" not in fieldnames: fieldnames.append("Calendar End")
    
    # Merge existing row keys if they are extra (dynamic fields)
    for k in row.keys():
        if k not in fieldnames:
            fieldnames.append(k)
            
    try:
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerow(row)
    except Exception as e:
        logger.error(f"Failed to write CSV {path}: {e}")

def append_to_master_csv(row: dict):
    # Determine Master Headers (superset)
    fieldnames = list(CSV_HEADERS)
    if "Calendar Start" not in fieldnames: fieldnames.append("Calendar Start")
    if "Calendar End" not in fieldnames: fieldnames.append("Calendar End")

    file_exists = MASTER_CSV.exists()
    
    # Check if headers need updating or if file ends without newline
    if file_exists:
        try:
            with open(MASTER_CSV, "r", encoding="utf-8") as f:
                header_line = f.readline().strip()
                existing_headers = header_line.split(",")
                
                # Check if file ends with newline
                f.seek(0, os.SEEK_END)
                if f.tell() > 0:
                    f.seek(f.tell() - 1, os.SEEK_SET)
                    last_char = f.read(1)
                else:
                    last_char = "\n"
        except Exception as e:
            logger.error(f"Failed to check master CSV: {e}")
            last_char = "\n"
            existing_headers = []
    else:
        last_char = "\n"
        existing_headers = []

    try:
        mode = "a"
        # If headers are missing, we might need to rewrite or just append carefully
        # For simplicity, we'll append. If headers were different, it's a bit messy.
        with open(MASTER_CSV, mode, newline="", encoding="utf-8") as f:
            # Ensure we start on a new line
            if last_char != "\n":
                f.write("\n")
                
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction='ignore')
            if not file_exists or not existing_headers:
                writer.writeheader()
            writer.writerow(row)
        logger.info(f"Appended to {MASTER_CSV}")
        return True
    except Exception as e:
        logger.error(f"Append Master failed: {e}")
        return False

# ------------------------------------------------------------------
# Calendar Logic
# ------------------------------------------------------------------

def infer_calendar_datetimes(row: dict):
    """Refined date parsing logic."""
    from dateutil import parser
    
    start_date = row.get("Starting Date")
    if not start_date: return

    # Start Time
    start_time = row.get("Time") or row.get("Doors") or "19:00"
    # Clean up time strings like "7:00pm (Doors)" -> "7:00pm"
    if "(" in start_time: start_time = start_time.split("(")[0].strip()
    
    try:
        dt_start = parser.parse(f"{start_date} {start_time}")
        row["Calendar Start"] = dt_start.isoformat()
    except:
        pass

    # End Time (Default to start date + 4 hours if not specified)
    end_date = row.get("Ending Date") or start_date
    # Simple heuristic: if end date is same as start, assume late night
    try:
        dt_end = parser.parse(f"{end_date} 23:30") 
        row["Calendar End"] = dt_end.isoformat()
    except:
        pass

def create_calendar_events(row: dict, needs_update: bool = False):
    """
    Creates or updates events on configured calendars.
    Includes Travel Time blocking on Band Calendar.
    """
    if not GOOGLE_SERVICE_ACCOUNT_FILE:
        return ["⚠️ Google Calendar not configured (no service account)."]

    try:
        creds = Credentials.from_service_account_file(GOOGLE_SERVICE_ACCOUNT_FILE, scopes=SCOPES)
        service = build("calendar", "v3", credentials=creds)
    except Exception as e:
        return [f"❌ Google Auth Failed: {e}"]

    # Prepare Event Data
    venue = row.get('Venue', 'Gig')
    location_str = row.get('Location', '')
    summary = f"{venue} ({location_str})"
    
    # Private Description: Full details
    private_desc = "\n".join([f"{k}: {v}" for k, v in row.items() if v and k not in WORKFLOW_FIELDS])
    
    # Public Description: Sanitized
    public_desc = f"Live at {venue}"

    event_body = {
        "summary": summary,
        "description": private_desc,
        "location": row.get("Address", ""),
        "start": {"dateTime": row.get("Calendar Start"), "timeZone": TIMEZONE},
        "end": {"dateTime": row.get("Calendar End"), "timeZone": TIMEZONE}
    }
    
    # Fallback for full day if parsing failed
    if not row.get("Calendar Start"):
         event_body["start"] = {"date": datetime.now().strftime("%Y-%m-%d")}
         event_body["end"] = {"date": datetime.now().strftime("%Y-%m-%d")}

    results = []
    
    def upsert_event(calendar_id, event_id_key, body, event_type="Event"):
        # 0. Handle manual Deletion (Replace)
        delete_id = row.get("Delete Event ID")
        if delete_id:
            try:
                service.events().delete(calendarId=calendar_id, eventId=delete_id).execute()
                logger.info(f"Deleted stale event {delete_id} from {event_type}")
                results.append(f"🗑️ Deleted stale event from {event_type}.")
            except Exception as d_e:
                if "404" not in str(d_e):
                    logger.warning(f"Failed to delete event {delete_id} from {event_type}: {d_e}")
                    results.append(f"⚠️ Failed to delete stale event from {event_type}: {d_e}")

        existing_id = row.get(event_id_key)
        
        # 1. Try Update if ID exists
        if existing_id:
            try:
                e = service.events().update(calendarId=calendar_id, eventId=existing_id, body=body).execute()
                return f"🔄 {event_type} Updated: [Link]({e.get('htmlLink')})", existing_id
            except Exception as e:
                if "404" in str(e):
                    logger.warning(f"{event_type} ID {existing_id} not found (404).")
                    existing_id = None
                else:
                    return f"❌ {event_type} Update Error: {e}", existing_id

        # 2. Insert new (NO AUTO-LINKING)
        try:
            e = service.events().insert(calendarId=calendar_id, body=body).execute()
            return f"✅ {event_type} Created: [Link]({e.get('htmlLink')})", e.get("id")
        except Exception as e:
             return f"❌ {event_type} Creation Error: {e}", None

    # 1. Band Calendar (Private)
    if BAND_CALENDAR_ID and row.get("Calendar Created") != "Skip":
        msg, new_id = upsert_event(BAND_CALENDAR_ID, "Band Event ID", event_body, "Band Calendar")
        results.append(msg)
        if new_id:
            row["Band Event ID"] = new_id
            row["Calendar Created"] = "True"

        # Travel Blocking (Task 3)
        dep_time = row.get("Departure Time")
        if dep_time:
            from dateutil import parser
            travel_start = dep_time
            # End of travel is either Load In or Calendar Start
            travel_end = row.get("Calendar Start")
            if row.get("Load In"):
                try:
                    travel_end = parser.parse(f"{row.get('Starting Date')} {row.get('Load In')}").isoformat()
                except: pass
            
            travel_body = {
                "summary": f"🚗 Travel to {venue}",
                "description": f"Driving from previous location to {venue}.",
                "start": {"dateTime": travel_start, "timeZone": TIMEZONE},
                "end": {"dateTime": travel_end, "timeZone": TIMEZONE},
                "colorId": "5" # Yellow/Banana for travel
            }
            
            t_msg, t_id = upsert_event(BAND_CALENDAR_ID, "Travel Event ID", travel_body, "Travel Block")
            results.append(t_msg)
            if t_id: row["Travel Event ID"] = t_id

    # 2. Public Calendar
    if PUBLIC_CALENDAR_ID and row.get("Public Calendar Created") != "Skip":
        pub_body = event_body.copy()
        pub_body["description"] = public_desc
        msg, new_id = upsert_event(PUBLIC_CALENDAR_ID, "Public Event ID", pub_body, "Public Calendar")
        results.append(msg)
        if new_id:
            row["Public Event ID"] = new_id
            row["Public Calendar Created"] = "True"

    if not results:
        results.append("ℹ️ No calendar changes required or all skipped.")

    return results

# ------------------------------------------------------------------
# Discord UI (Stages 5 & 7)
# ------------------------------------------------------------------

class DuplicateSelectView(discord.ui.View):
    def __init__(self, matches: list):
        super().__init__(timeout=300)
        self.matches = matches
        self.selected_id = None
        self.delete_id = None
        self.choice = None # 'merge', 'replace', 'duplicate', 'disregard'

        # Show Merge/Replace for up to 2 matches to keep UI clean
        for i, match in enumerate(self.matches[:2]):
            m_btn = discord.ui.Button(label=f"Merge: {match['summary'][:25]}", style=discord.ButtonStyle.success)
            m_btn.callback = self.make_callback(match['id'], 'merge')
            self.add_item(m_btn)
            
            r_btn = discord.ui.Button(label=f"Replace: {match['summary'][:25]}", style=discord.ButtonStyle.secondary)
            r_btn.callback = self.make_callback(match['id'], 'replace')
            self.add_item(r_btn)
        
        dup_btn = discord.ui.Button(label="➕ Create New (Duplicate)", style=discord.ButtonStyle.primary)
        dup_btn.callback = self.duplicate_callback
        self.add_item(dup_btn)

        skip_btn = discord.ui.Button(label="🚫 Skip Calendar", style=discord.ButtonStyle.danger)
        skip_btn.callback = self.skip_callback
        self.add_item(skip_btn)

    def make_callback(self, event_id, choice):
        async def callback(interaction: discord.Interaction):
            if choice == 'merge': self.selected_id = event_id
            if choice == 'replace': self.delete_id = event_id
            self.choice = choice
            self.stop()
            msg = f"🔗 Linking with `{event_id}`" if choice == 'merge' else f"♻️ Replacing `{event_id}`"
            await interaction.response.send_message(msg, ephemeral=True)
        return callback

    async def duplicate_callback(self, interaction: discord.Interaction):
        self.choice = 'duplicate'
        self.stop()
        await interaction.response.send_message("🆕 Creating a separate new event.", ephemeral=True)

    async def skip_callback(self, interaction: discord.Interaction):
        self.choice = 'disregard'
        self.stop()
        await interaction.response.send_message("⏭ Skipping calendar creation for this gig.", ephemeral=True)

class ReviewView(discord.ui.View):
    def __init__(self, filepath: Path, action_type: str, row: dict, changelog: dict = None):
        super().__init__(timeout=None)
        self.filepath = filepath
        self.action_type = action_type # "appended" or "updated"
        self.row = row
        self.changelog = changelog

    @discord.ui.button(label="📝 Review", style=discord.ButtonStyle.primary, custom_id="review_btn")
    async def review(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.filepath.exists():
            await interaction.response.send_message("❌ File no longer exists.", ephemeral=True)
            return

        thread_name = f"{'🆕 New' if self.action_type == 'appended' else '📝 Update'}: {self.filepath.stem}"
        thread = await interaction.channel.create_thread(name=thread_name, type=discord.ChannelType.private_thread)
        await interaction.response.send_message(f"Started review in {thread.mention}", ephemeral=True)
        
        await run_review_process(thread, self.filepath, self.action_type, self.row, self.changelog)


class FinalizeView(discord.ui.View):
    def __init__(self, filepath: Path, row: dict, action_type: str, needs_calendar_update: bool = False):
        super().__init__(timeout=None)
        self.filepath = filepath
        self.row = row
        self.action_type = action_type
        self.needs_calendar_update = needs_calendar_update

    @discord.ui.button(label="✅ Confirm & Publish", style=discord.ButtonStyle.success)
    async def approve(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        
        try:
            # 1. State: Processed
            self.row["Discord Finished"] = "True"
            
            # 2. Date/Time Pre-Processing
            infer_calendar_datetimes(self.row)
            
            # 3. MAPBOT Enrichment (Task 1 & 2)
            try:
                mapbot = get_mapbot_module()
                gigs = mapbot.get_sorted_gigs()
                if await mapbot.plan_route_for_gig(self.row, gigs):
                    await interaction.followup.send("🚚 MAPBOT: Routing and logistics calculated.", ephemeral=True)
            except Exception as e:
                logger.error(f"MAPBOT enrichment failed: {e}")

            # 4. Google Calendar Management (Interactive Step)
            proceed_to_calendar = True
            if GOOGLE_SERVICE_ACCOUNT_FILE and BAND_CALENDAR_ID:
                try:
                    creds = Credentials.from_service_account_file(GOOGLE_SERVICE_ACCOUNT_FILE, scopes=SCOPES)
                    service = build("calendar", "v3", credentials=creds)
                    
                    venue = self.row.get("Venue", "")
                    dt_str = self.row.get("Calendar Start")
                    
                    matches = []
                    if dt_str:
                        try:
                            dt = datetime.fromisoformat(dt_str)
                            tmin = (dt - timedelta(hours=12)).isoformat() + "Z"
                            tmax = (dt + timedelta(hours=12)).isoformat() + "Z"
                            
                            request = service.events().list(calendarId=BAND_CALENDAR_ID, timeMin=tmin, timeMax=tmax, singleEvents=True, q=venue)
                            res = await asyncio.to_thread(request.execute)
                            
                            for item in res.get('items', []):
                                if venue.lower() in item.get('summary', '').lower():
                                    prefix = "[LINKED] " if item['id'] == self.row.get("Band Event ID") else ""
                                    matches.append({"id": item['id'], "summary": prefix + item['summary']})
                        except: pass
                    
                    # If we found matches or have an existing ID, we MUST ask
                    if matches or self.row.get("Band Event ID"):
                        if not matches and self.row.get("Band Event ID"):
                            matches.append({"id": self.row.get("Band Event ID"), "summary": "[STALE LINK] Existing Event"})

                        view = DuplicateSelectView(matches)
                        match_msg = await interaction.followup.send("🗓️ **Calendar Match Found.** How should I handle this gig on your calendar?", view=view)
                        
                        # Wait for the user to make a choice
                        if await view.wait():
                            # This returns True if it timed out
                            await interaction.followup.send("⚠️ Calendar choice timed out. Finalization cancelled. Please try again.", ephemeral=True)
                            proceed_to_calendar = False
                        elif view.choice is None:
                            # User closed or something went wrong
                            await interaction.followup.send("❌ No calendar choice made. Finalization cancelled.", ephemeral=True)
                            proceed_to_calendar = False
                        else:
                            # Handle choices
                            if view.choice == 'merge' and view.selected_id:
                                self.row["Band Event ID"] = view.selected_id
                                # We keep Public Event ID as-is (if it's linked, it updates; if not, it stays empty)
                            elif view.choice == 'replace' and view.delete_id:
                                self.row["Delete Event ID"] = view.delete_id
                                self.row["Band Event ID"] = ""
                                self.row["Public Event ID"] = ""
                            elif view.choice == 'duplicate':
                                self.row["Band Event ID"] = ""
                                self.row["Public Event ID"] = ""
                                self.row["Force Duplicate"] = "True"
                            elif view.choice == 'disregard':
                                self.row["Calendar Created"] = "Skip"
                                self.row["Public Calendar Created"] = "Skip"
                        
                        try: await match_msg.delete()
                        except: pass

                except Exception as e:
                    logger.warning(f"Calendar check failed: {e}")
                    await interaction.followup.send(f"⚠️ Calendar check error: {e}. Proceeding carefully...", ephemeral=True)

            if not proceed_to_calendar:
                return

            # 5. Execute Calendar Updates
            cal_results = []
            if self.row.get("Calendar Created") != "Skip":
                cal_results = await asyncio.to_thread(create_calendar_events, self.row, self.needs_calendar_update)
            
            # 6. Final Atomic Write (Threaded)
            result = await asyncio.to_thread(update_master_csv, self.row, self.filepath.name)
            
            # 7. Archive & Cleanup
            try:
                shutil.move(str(self.filepath), str(PROCESSED_DIR / self.filepath.name))
                archive_msg = "📂 File archived."
            except Exception as e:
                archive_msg = f"⚠️ Archive failed: {e}"
                
            summary = "\n".join(cal_results) if cal_results else "ℹ️ No calendar updates performed."
            await interaction.followup.send(f"**Done!**\n{archive_msg}\n{summary}\n\n*Closing thread...*")
            await asyncio.sleep(5)
            try:
                await interaction.channel.edit(archived=True, locked=True)
            except:
                pass
        except Exception as e:
            logger.error(f"Error in approve: {e}", exc_info=True)
            await interaction.followup.send(f"❌ An error occurred during processing: {e}")

async def run_review_process(thread: discord.Thread, filepath: Path, action_type: str, row: dict, changelog: dict):
    """The interactive Q&A loop inside the thread."""
    # We use the row passed in (which is merged with master data if an update)
    # instead of re-reading from Bits which would lose IDs.
    
    if action_type == "appended":
        await thread.send(f"🆕 **New Gig Detected!**\nVenue: `{row.get('Venue')}`\nDate: `{row.get('Starting Date')}`")
    else:
        await thread.send(f"📝 **Update Detected!**\nVenue: `{row.get('Venue')}`\nDate: `{row.get('Starting Date')}`")
        if changelog:
            changes = "\n".join([f"- {line}" for line in changelog['summary_lines']])
            await thread.send(f"**Changes:**\n{changes}")
            if changelog.get('needs_mapbot'):
                await thread.send("⚠️ Location changed—MAPBOT will need to recalculate.")

    # Identify Missing Details
    ignore = ["Calendar Start", "Calendar End", "Est. Mileage"] + WORKFLOW_FIELDS
    missing = [k for k, v in row.items() if not v and k not in ignore]

    if missing:
        await thread.send(f"**Missing Details:** {', '.join(missing)}\nReply with `field: value` to update, or `done` to finish.")

    # 2. Logistics Questions (MAPBOT)
    await thread.send("🚚 **Logistics Check:** Are we staying the night after this gig? (Yes/No)")
    try:
        def check_bot(m): return m.channel.id == thread.id and not m.author.bot
        msg = await bot.wait_for('message', check=check_bot, timeout=300)
        if "yes" in msg.content.lower():
            row["Accomodations"] = "TRUE"
            await thread.send("🏨 Where are we staying? (Address or 'skip')")
            addr_msg = await bot.wait_for('message', check=check_bot, timeout=300)
            if addr_msg.content.lower() != "skip":
                row["Accom Address"] = addr_msg.content.strip()
                await thread.send(f"✅ Set accommodation address to `{row['Accom Address']}`")
        else:
            row["Accomodations"] = "FALSE"
            
        # Step 2: Pit-stop Proposing
        try:
            gigs = mapbot.get_sorted_gigs()
            # Pass what we have to MAPBOT to check drive time
            if await mapbot.plan_route_for_gig(row, gigs):
                if row.get("needs_pitstop"):
                    await thread.send(f"🚚 *I see a long drive to {row.get('Venue')}. Do you want to add any food stops or attractions along the way?*")
                    pitstop_msg = await bot.wait_for('message', check=check_bot, timeout=300)
                    if pitstop_msg.content.lower() not in ["no", "none", "skip"]:
                        stops = pitstop_msg.content.strip()
                        # Recalculate with waypoints
                        if await mapbot.plan_route_for_gig(row, gigs, waypoints_text=stops):
                            row["Other Details"] = (row.get("Other Details", "") + f"\n[Stops]: {stops}").strip()
                            await thread.send(f"✅ Route updated with stops: {stops}")
        except Exception as e:
            logger.error(f"Pit-stop check failed: {e}")

    except asyncio.TimeoutError:
        await thread.send("⏱ Logistics timeout. Skipping.")

    # 3. Interactive loop for other fields (Step 1: Refactor to Ollama)
    while True:

        def check(m):
            return m.channel.id == thread.id and not m.author.bot
        
        try:
            msg = await bot.wait_for('message', check=check, timeout=600)
            content = msg.content.strip()
            
            if content.lower() == 'done' or content.lower() == 'confirm':
                break
            
            # Send to Ollama for extraction
            extracted = await asyncio.to_thread(call_ollama_extract, content, missing)
            
            updates = []
            extracted_dict = extracted.model_dump(by_alias=True)
            for k, v in extracted_dict.items():
                if v and k in missing:
                    row[k] = v
                    updates.append(f"- **{k}**: {v}")
            
            if updates:
                await thread.send("✅ **I've understood and updated the following:**\n" + "\n".join(updates))
                # Refresh missing list
                missing = [k for k, v in row.items() if not v and k not in ignore]
                if missing:
                    await thread.send(f"**Still Missing:** {', '.join(missing)}")
                else:
                    await thread.send("🎉 All details filled! Type `confirm` to finish.")
            else:
                # Fallback to manual if AI fails or user used old format
                if ":" in content:
                    key, val = content.split(":", 1)
                    matches = difflib.get_close_matches(key.strip(), list(CSV_HEADERS), n=1, cutoff=0.6)
                    if matches:
                        row[matches[0]] = val.strip()
                        await thread.send(f"✅ Set `{matches[0]}` to `{val.strip()}`")
                        # Refresh missing list
                        missing = [k for k, v in row.items() if not v and k not in ignore]
                    else:
                        await thread.send(f"❓ Could not find field matching `{key}`")
                else:
                    await thread.send("I didn't catch any new details. You can just talk to me, or use `field: value`!")
                
        except asyncio.TimeoutError:
            await thread.send("⏱ **Review Timeout:** No activity detected for 10 minutes.")
            return

    # Final review embed
    embed = discord.Embed(title="Final Review", color=0x2ecc71)
    for k, v in row.items():
        if v and k not in WORKFLOW_FIELDS:
            embed.add_field(name=k, value=v, inline=True)
    
    needs_cal = True if action_type == "appended" else (changelog.get("needs_calendar_update") if changelog else False)
    await thread.send(embed=embed, view=FinalizeView(filepath, row, action_type, needs_cal))

# ------------------------------------------------------------------
# Bot Setup & Cog Integration
# ------------------------------------------------------------------

class AItineraryBot(commands.Bot):
    async def setup_hook(self):
        # Dynamically load the TINNYBOT cog when the bot starts
        try:
            spec = importlib.util.spec_from_file_location("tinnybot", ROOT_DIR / "AI-tinerary-TINNYBOT.py")
            tinny = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(tinny)
            
            # This calls the async setup(bot) function at the bottom of TINNYBOT
            await tinny.setup(self)
            logger.info("✅ TINNYBOT Cog successfully loaded.")
        except Exception as e:
            logger.error(f"❌ Failed to load TINNYBOT Cog: {e}")

intents = discord.Intents.default()
intents.message_content = True

# Initialize using our custom subclass
bot = AItineraryBot(command_prefix="!", intents=intents)

# Persistence logic
notified_files = set()

def load_state():
    global notified_files
    if STATE_FILE.exists():
        try:
            with open(STATE_FILE, "r") as f:
                data = json.load(f)
                notified_files = set(data.get("notified_files", []))
                logger.info(f"Loaded {len(notified_files)} notified files from state.")
        except Exception as e:
            logger.error(f"Failed to load state: {e}")

def save_state():
    try:
        temp_state = STATE_FILE.with_suffix(".tmp")
        with open(temp_state, "w") as f:
            json.dump({"notified_files": list(notified_files)}, f)
        temp_state.replace(STATE_FILE)
    except Exception as e:
        logger.error(f"Failed to save state: {e}")

# ------------------------------------------------------------------
# Command Interface (Stage 7)
# ------------------------------------------------------------------

@bot.group(name="calbot", invoke_without_command=True)
async def calbot_cmd(ctx):
    """CALBOT base command."""
    await ctx.send("Usage: `!calbot status`, `!calbot process <file>`, `!calbot merge`")

@calbot_cmd.command(name="status")
async def calbot_status(ctx):
    """Show pending reviews and stats."""
    pending = list(BITS_DIR.glob("*.csv"))
    master_count = 0
    if MASTER_CSV.exists():
        with open(MASTER_CSV, "r") as f:
            master_count = sum(1 for line in f) - 1
            
    embed = discord.Embed(title="CALBOT Status", color=0x3498db)
    embed.add_field(name="Pending Reviews", value=len(pending), inline=True)
    embed.add_field(name="Master Gigs", value=master_count, inline=True)
    
    processed = list(PROCESSED_DIR.glob("*.csv"))
    if processed:
        embed.add_field(name="Processed Files", value=len(processed), inline=True)
        
    await ctx.send(embed=embed)

@calbot_cmd.command(name="reprocess")
async def calbot_reprocess(ctx, filename: str = None):
    """Move a file from Processed back to Bits for re-review."""
    if not filename:
        processed_files = sorted(list(PROCESSED_DIR.glob("*.csv")), key=os.path.getmtime, reverse=True)
        if not processed_files:
            await ctx.send("❌ No files in Processed folder.")
            return
        file_list = "\n".join([f"- `{f.name}`" for f in processed_files[:10]])
        await ctx.send(f"Usage: `!calbot reprocess <filename>`\nRecent processed files:\n{file_list}")
        return

    source = PROCESSED_DIR / filename
    dest = BITS_DIR / filename
    
    if source.exists():
        try:
            shutil.move(str(source), str(dest))
            if filename in notified_files:
                notified_files.remove(filename)
                save_state()
            await ctx.send(f"✅ Moved `{filename}` back to Bits for reprocessing. Run `!calbot merge` to trigger notification.")
            logger.info(f"🔄 Reprocessing triggered for {filename}")
        except Exception as e:
            await ctx.send(f"❌ Failed to move file: {e}")
    else:
        await ctx.send(f"❌ File `{filename}` not found in Processed folder.")

@calbot_cmd.command(name="merge")
async def calbot_merge(ctx):
    """Manually trigger folder watch."""
    await ctx.send("Checking `Outputs/Bits` for new contracts...")
    await watch_folder()

def get_mapbot_module():
    spec = importlib.util.spec_from_file_location("mapbot", ROOT_DIR / "AI-tinerary-MAPBOT.py")
    mapbot = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mapbot)
    return mapbot

# ------------------------------------------------------------------
# MAPBOT Commands
# ------------------------------------------------------------------

@bot.group(name="mapbot", invoke_without_command=True)
async def mapbot_cmd(ctx):
    """MAPBOT base command."""
    await ctx.send("Usage: `!mapbot status`, `!mapbot route all`, `!mapbot base <address>`")

@mapbot_cmd.command(name="status")
async def mapbot_status(ctx):
    """Show gigs needing routing."""
    mapbot = get_mapbot_module()
    gigs = mapbot.get_sorted_gigs()
    pending = [g for g in gigs if not g.get("Routing") or not g.get("Mileage")]
    
    embed = discord.Embed(title="MAPBOT Status", color=0xe67e22)
    embed.add_field(name="Gigs Needing Routing", value=len(pending), inline=True)
    if pending:
        list_str = "\n".join([f"- {g['Starting Date']}: {g['Venue']}" for g in pending[:10]])
        embed.add_field(name="Next Gigs", value=list_str, inline=False)
    await ctx.send(embed=embed)

@mapbot_cmd.command(name="route")
async def mapbot_route(ctx, arg="all"):
    """Trigger routing calculation."""
    await ctx.send("🚚 MAPBOT is recalculating routes...")
    mapbot = get_mapbot_module()
    gigs = mapbot.get_sorted_gigs()
    updated = False
    for gig in gigs:
        if arg == "all" or arg in gig.get("Starting Date", ""):
            if await mapbot.plan_route_for_gig(gig, gigs):
                updated = True
    
    if updated:
        mapbot.update_master_csv_atomic(gigs)
        await ctx.send("✅ Routing updates complete and saved to master CSV.")
    else:
        await ctx.send("ℹ️ No updates needed or routing failed for requested gigs.")

@bot.event
async def on_ready():
    logger.info(f"Bot logged in as {bot.user}")
    load_state()
    if not watch_folder.is_running():
        watch_folder.start()

@tasks.loop(seconds=60)
async def watch_folder():
    """Poller to check for new CSVs."""
    logger.info("👀 CALBOT: Checking for new CSVs in Bits/ folder...")
    if not DISCORD_CHANNEL_ID or not str(DISCORD_CHANNEL_ID).isdigit():
        logger.error(f"❌ Invalid DISCORD_CHANNEL_ID: {DISCORD_CHANNEL_ID}")
        return
        
    channel = bot.get_channel(int(DISCORD_CHANNEL_ID))
    if not channel:
        logger.warning(f"⚠️ Channel {DISCORD_CHANNEL_ID} not found in cache. Attempting to fetch...")
        try:
            channel = await bot.fetch_channel(int(DISCORD_CHANNEL_ID))
        except Exception as e:
            logger.error(f"❌ Failed to fetch channel {DISCORD_CHANNEL_ID}: {e}")
            return

    found_new = False
    # Read master rows for matching (Threaded)
    def read_master():
        if not MASTER_CSV.exists(): return []
        with open(MASTER_CSV, "r", newline="", encoding="utf-8") as f:
            return list(csv.DictReader(f))
    
    try:
        master_rows = await asyncio.to_thread(read_master)
    except Exception as e:
        logger.error(f"❌ Failed to read master CSV: {e}")
        return

    csv_files = list(BITS_DIR.glob("*.csv"))
    logger.info(f"📂 Found {len(csv_files)} CSV files in {BITS_DIR}")

    for csv_file in csv_files:
        if csv_file.name in notified_files:
            continue
            
        logger.info(f"📄 Processing new file: {csv_file.name}")
        new_row = read_csv_row(csv_file)
        if not new_row:
            logger.warning(f"⚠️ Empty or invalid CSV: {csv_file.name}")
            continue

        # Stage 1: Match
        row_index = find_matching_row(master_rows, new_row)
        action_type = "appended"
        changelog = None
        
        if row_index >= 0:
            action_type = "updated"
            old_row = master_rows[row_index]
            merged = merge_fields(old_row, new_row)
            changelog = generate_changelog(old_row, merged)

        venue = new_row.get("Venue") or "Unknown Venue"
        date = new_row.get("Starting Date") or "Unknown Date"
        
        embed = discord.Embed(
            title="📄 New Contract" if action_type == "appended" else "📝 Update Detected",
            description=f"**Gig:** {venue} on {date}",
            color=0xf1c40f if action_type == "appended" else 0x3498db
        )
        if changelog:
            embed.add_field(name="Changes", value=f"{len(changelog['changed_fields'])} fields", inline=True)
        elif action_type == "updated":
            embed.add_field(name="Note", value="Matched existing gig (no core changes detected).", inline=True)
        
        try:
            # Important: Pass the merged row (which has IDs) if updated, else new_row
            row_to_pass = merged if action_type == "updated" else new_row
            await channel.send(embed=embed, view=ReviewView(csv_file, action_type, row_to_pass, changelog))
            logger.info(f"✅ Notified Discord about {csv_file.name}")
            notified_files.add(csv_file.name)
            save_state()
            found_new = True
        except Exception as e:
            logger.error(f"❌ Failed to send notification for {csv_file.name}: {e}")

    if not found_new:
        logger.info("😴 No new contracts to notify.")

if __name__ == "__main__":
    if not DISCORD_TOKEN:
        logger.error("DISCORD_BOT_TOKEN missing in Master Config.txt")
    else:
        bot.run(DISCORD_TOKEN)