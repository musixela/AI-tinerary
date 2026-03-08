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
        "Doors": None
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
    
    # 1. Band Calendar (Private)
    if BAND_CALENDAR_ID:
        try:
            event_id = row.get("Band Event ID")
            if event_id:
                e = service.events().update(calendarId=BAND_CALENDAR_ID, eventId=event_id, body=event_body).execute()
                results.append(f"🔄 Band Calendar Updated: [Link]({e.get('htmlLink')})")
            else:
                e = service.events().insert(calendarId=BAND_CALENDAR_ID, body=event_body).execute()
                results.append(f"✅ Band Calendar Created: [Link]({e.get('htmlLink')})")
                row["Band Event ID"] = e.get("id")
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
                
                t_event_id = row.get("Travel Event ID")
                if t_event_id:
                    service.events().update(calendarId=BAND_CALENDAR_ID, eventId=t_event_id, body=travel_body).execute()
                    results.append("🚗 Travel block updated.")
                else:
                    te = service.events().insert(calendarId=BAND_CALENDAR_ID, body=travel_body).execute()
                    row["Travel Event ID"] = te.get("id")
                    results.append("🚗 Travel block created.")

        except Exception as e:
            results.append(f"❌ Band Cal Error: {e}")
            
    # 2. Public Calendar
    if PUBLIC_CALENDAR_ID:
        try:
            pub_body = event_body.copy()
            pub_body["description"] = public_desc
            event_id = row.get("Public Event ID")
            if event_id:
                e = service.events().update(calendarId=PUBLIC_CALENDAR_ID, eventId=event_id, body=pub_body).execute()
                results.append(f"🔄 Public Calendar Updated: [Link]({e.get('htmlLink')})")
            else:
                e = service.events().insert(calendarId=PUBLIC_CALENDAR_ID, body=pub_body).execute()
                results.append(f"✅ Public Calendar Created: [Link]({e.get('htmlLink')})")
                row["Public Event ID"] = e.get("id")
            row["Public Calendar Created"] = "True"
        except Exception as e:
            results.append(f"❌ Public Cal Error: {e}")

    return results

# ------------------------------------------------------------------
# Discord UI (Stages 5 & 7)
# ------------------------------------------------------------------

class ReviewView(discord.ui.View):
    def __init__(self, filepath: Path, action_type: str, changelog: dict = None):
        super().__init__(timeout=None)
        self.filepath = filepath
        self.action_type = action_type # "appended" or "updated"
        self.changelog = changelog

    @discord.ui.button(label="📝 Review", style=discord.ButtonStyle.primary, custom_id="review_btn")
    async def review(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.filepath.exists():
            await interaction.response.send_message("❌ File no longer exists.", ephemeral=True)
            return

        thread_name = f"{'🆕 New' if self.action_type == 'appended' else '📝 Update'}: {self.filepath.stem}"
        thread = await interaction.channel.create_thread(name=thread_name, type=discord.ChannelType.private_thread)
        await interaction.response.send_message(f"Started review in {thread.mention}", ephemeral=True)
        
        await run_review_process(thread, self.filepath, self.action_type, self.changelog)


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
        
        # 1. State: Processed
        self.row["Discord Finished"] = "True"
        
        # 2. Date/Time Pre-Processing
        infer_calendar_datetimes(self.row)
        
        # 3. MAPBOT Enrichment (Task 1 & 2)
        try:
            mapbot = get_mapbot_module()
            gigs = mapbot.get_sorted_gigs()
            # Calculate route for THIS row and update self.row object
            if await mapbot.plan_route_for_gig(self.row, gigs):
                await interaction.followup.send("🚚 MAPBOT: Routing and logistics calculated.")
        except Exception as e:
            logger.error(f"MAPBOT enrichment failed: {e}")

        # 4. Google Calendar (Task 1 & 3)
        # Create/Update events including the new Travel Block
        cal_results = []
        if self.row.get("Calendar Created") != "True" or self.needs_calendar_update:
            cal_results = await asyncio.to_thread(create_calendar_events, self.row, self.needs_calendar_update)
        
        # 5. Final Atomic Write (Task 1)
        # Save enriched row (IDs, Routing, Mileage) once
        result = update_master_csv(self.row, self.filepath.name)
        
        # 6. Archive & Cleanup
        try:
            shutil.move(str(self.filepath), str(PROCESSED_DIR / self.filepath.name))
            archive_msg = "📂 File archived."
        except Exception as e:
            archive_msg = f"⚠️ Archive failed: {e}"
            
        summary = "\n".join(cal_results)
        await interaction.followup.send(f"**Done!**\n{archive_msg}\n{summary}\n\n*Closing thread...*")
        await asyncio.sleep(5)
        try:
            await interaction.channel.edit(archived=True, locked=True)
        except:
            pass

async def run_review_process(thread: discord.Thread, filepath: Path, action_type: str, changelog: dict):
    """The interactive Q&A loop inside the thread."""
    row = read_csv_row(filepath)
    
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
    except asyncio.TimeoutError:
        await thread.send("⏱ Logistics timeout. Skipping.")

    # 3. Interactive loop for other fields
    while True:

        def check(m):
            return m.channel.id == thread.id and not m.author.bot
        
        try:
            msg = await bot.wait_for('message', check=check, timeout=600)
            content = msg.content.strip()
            
            if content.lower() == 'done' or content.lower() == 'confirm':
                break
            
            if ":" in content:
                key, val = content.split(":", 1)
                key = key.strip()
                val = val.strip()
                # Fuzzy match key to headers
                matches = difflib.get_close_matches(key, list(CSV_HEADERS), n=1, cutoff=0.6)
                if matches:
                    row[matches[0]] = val
                    await thread.send(f"✅ Set `{matches[0]}` to `{val}`")
                else:
                    await thread.send(f"❓ Could not find field matching `{key}`")
            else:
                await thread.send("Type `field: value` to update a field, or `done` to finish.")
                
        except asyncio.TimeoutError:
            await thread.send("⏱ Timeout.")
            return

    # Final review embed
    embed = discord.Embed(title="Final Review", color=0x2ecc71)
    for k, v in row.items():
        if v and k not in WORKFLOW_FIELDS:
            embed.add_field(name=k, value=v, inline=True)
    
    needs_cal = True if action_type == "appended" else (changelog.get("needs_calendar_update") if changelog else False)
    await thread.send(embed=embed, view=FinalizeView(filepath, row, action_type, needs_cal))

# ------------------------------------------------------------------
# Bot Setup
# ------------------------------------------------------------------

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

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
    await ctx.send(embed=embed)

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
    if not DISCORD_CHANNEL_ID or not str(DISCORD_CHANNEL_ID).isdigit():
        return
        
    channel = bot.get_channel(int(DISCORD_CHANNEL_ID))
    if not channel: return

    found_new = False
    # Read master rows for matching
    master_rows = []
    if MASTER_CSV.exists():
        with open(MASTER_CSV, "r", newline="", encoding="utf-8") as f:
            master_rows = list(csv.DictReader(f))

    for csv_file in BITS_DIR.glob("*.csv"):
        if csv_file.name in notified_files:
            continue
            
        new_row = read_csv_row(csv_file)
        if not new_row: continue

        # Stage 1: Match
        row_index = find_matching_row(master_rows, new_row)
        action_type = "appended"
        changelog = None
        
        if row_index >= 0:
            action_type = "updated"
            old_row = master_rows[row_index]
            merged = merge_fields(old_row, new_row)
            changelog = generate_changelog(old_row, merged)
            if not changelog:
                # No changes, mark as notified and skip
                notified_files.add(csv_file.name)
                continue

        venue = new_row.get("Venue") or "Unknown Venue"
        date = new_row.get("Starting Date") or "Unknown Date"
        
        embed = discord.Embed(
            title="📄 New Contract" if action_type == "appended" else "📝 Update Detected",
            description=f"**Gig:** {venue} on {date}",
            color=0xf1c40f if action_type == "appended" else 0x3498db
        )
        if changelog:
            embed.add_field(name="Changes", value=f"{len(changelog['changed_fields'])} fields", inline=True)
        
        await channel.send(embed=embed, view=ReviewView(csv_file, action_type, changelog))
        notified_files.add(csv_file.name)
        save_state()
        found_new = True

if __name__ == "__main__":
    if not DISCORD_TOKEN:
        logger.error("DISCORD_BOT_TOKEN missing in Master Config.txt")
    else:
        bot.run(DISCORD_TOKEN)
