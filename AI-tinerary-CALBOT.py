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
from pathlib import Path
from datetime import datetime
import importlib.util

import requests
from dotenv import load_dotenv

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# Suppress noisy libraries
class _VoiceFilter(logging.Filter):
    def filter(self, record):
        msg = record.getMessage()
        return not ("PyNaCl is not installed" in msg or "davey is not installed" in msg)
logging.getLogger().addFilter(_VoiceFilter())
logging.getLogger('discord').setLevel(logging.CRITICAL)
logging.getLogger('discord.voice_client').setLevel(logging.CRITICAL)

# Import discord safely
import sys
_orig_stdout = sys.stdout
_orig_stderr = sys.stderr
with open(os.devnull, 'w') as devnull:
    sys.stdout = devnull
    sys.stderr = devnull
    try:
        import discord
        from discord.ext import commands, tasks
    finally:
        sys.stdout = _orig_stdout
        sys.stderr = _orig_stderr

# Google Calendar Imports
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

# ------------------------------------------------------------------
# Configuration & Paths
# ------------------------------------------------------------------

ROOT_DIR = Path(__file__).resolve().parent
OUTPUTS_DIR = ROOT_DIR / "Outputs"
BITS_DIR = OUTPUTS_DIR / "Bits"
PROCESSED_DIR = BITS_DIR / "Processed"
MASTER_CSV = OUTPUTS_DIR / "master-output.csv"
STATE_FILE = OUTPUTS_DIR / "bot_state.json"

# Load Config
load_dotenv(override=True)
load_dotenv(dotenv_path=ROOT_DIR / "Master Config.txt", override=True)

DISCORD_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
DISCORD_CHANNEL_ID = os.getenv("DISCORD_CHANNEL_ID")
GOOGLE_SERVICE_ACCOUNT_FILE = os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE")
BAND_CALENDAR_ID = os.getenv("BAND_CALENDAR_ID")
PUBLIC_CALENDAR_ID = os.getenv("PUBLIC_CALENDAR_ID")

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434/api/generate")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "ministral-3:3b")

SCOPES = ["https://www.googleapis.com/auth/calendar"]

# Import headers from CSV script to ensure consistency
_csv_spec = importlib.util.spec_from_file_location("aitin_csv", ROOT_DIR / "AI-tinerary-CSV.py")
_ai_csv = importlib.util.module_from_spec(_csv_spec)
_csv_spec.loader.exec_module(_ai_csv)
CSV_HEADERS = _ai_csv.CSV_HEADERS
call_ollama_extract = _ai_csv.call_ollama_extract

# Ensure directories exist
PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

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

def create_calendar_events(row: dict):
    """Creates events on configured calendars."""
    if not GOOGLE_SERVICE_ACCOUNT_FILE:
        return ["⚠️ Google Calendar not configured (no service account)."]

    try:
        creds = Credentials.from_service_account_file(GOOGLE_SERVICE_ACCOUNT_FILE, scopes=SCOPES)
        service = build("calendar", "v3", credentials=creds)
    except Exception as e:
        return [f"❌ Google Auth Failed: {e}"]

    summary = f"{row.get('Venue', 'Gig')} ({row.get('Location', '')})"
    description = "\n".join([f"{k}: {v}" for k, v in row.items() if v])
    
    event_body = {
        "summary": summary,
        "description": description,
        "location": row.get("Address", ""),
        "start": {"dateTime": row.get("Calendar Start"), "timeZone": "America/New_York"},
        "end": {"dateTime": row.get("Calendar End"), "timeZone": "America/New_York"}
    }
    
    # Fallback for full day if parsing failed
    if not row.get("Calendar Start"):
         event_body["start"] = {"date": datetime.now().strftime("%Y-%m-%d")}
         event_body["end"] = {"date": datetime.now().strftime("%Y-%m-%d")}

    results = []
    
    # Band Calendar
    if BAND_CALENDAR_ID:
        try:
            e = service.events().insert(calendarId=BAND_CALENDAR_ID, body=event_body).execute()
            results.append(f"✅ Band Calendar: [Link]({e.get('htmlLink')})")
        except Exception as e:
            results.append(f"❌ Band Cal Error: {e}")
            
    # Public Calendar (Sanitize sensitive info if needed, currently copying same)
    if PUBLIC_CALENDAR_ID:
        try:
            # Maybe strip Pay/Contact for public?
            pub_body = event_body.copy()
            pub_body["description"] = f"Live at {row.get('Venue')}"
            e = service.events().insert(calendarId=PUBLIC_CALENDAR_ID, body=pub_body).execute()
            results.append(f"✅ Public Calendar: [Link]({e.get('htmlLink')})")
        except Exception as e:
            results.append(f"❌ Public Cal Error: {e}")

    return results

# ------------------------------------------------------------------
# Discord UI
# ------------------------------------------------------------------

class ReviewView(discord.ui.View):
    def __init__(self, filepath: Path):
        super().__init__(timeout=None)
        self.filepath = filepath

    @discord.ui.button(label="📝 Review & Finalize", style=discord.ButtonStyle.primary, custom_id="review_btn")
    async def review(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Check if file still exists (might have been moved/deleted)
        if not self.filepath.exists():
            await interaction.response.send_message("❌ File no longer exists in `Bits/`. It may have been processed already.", ephemeral=True)
            return

        # Create a private thread for the review
        thread_name = f"Review: {self.filepath.stem}"
        thread = await interaction.channel.create_thread(name=thread_name, type=discord.ChannelType.private_thread)
        await interaction.response.send_message(f"Started review in thread: {thread.mention}", ephemeral=True)
        
        # Start the interactive process in the thread
        await run_review_process(thread, self.filepath)


class FinalizeView(discord.ui.View):
    def __init__(self, filepath: Path, row: dict):
        super().__init__(timeout=None)
        self.filepath = filepath
        self.row = row

    @discord.ui.button(label="✅ Approve & Publish", style=discord.ButtonStyle.success)
    async def approve(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        
        # 1. Infer Dates
        infer_calendar_datetimes(self.row)
        
        # 2. Update CSV on disk
        write_csv_row(self.filepath, self.row)
        
        # 3. Append to Master
        append_to_master_csv(self.row)
        
        # 4. Calendar
        cal_results = await asyncio.to_thread(create_calendar_events, self.row)
        
        # 5. Archive
        try:
            shutil.move(str(self.filepath), str(PROCESSED_DIR / self.filepath.name))
            archive_msg = "📂 Moved file to `Processed/`"
        except Exception as e:
            archive_msg = f"⚠️ Failed to move file: {e}"
            
        summary = "\n".join(cal_results)
        await interaction.followup.send(f"**Deployment Complete!**\n{archive_msg}\n{summary}\n\n*Closing thread in 5s...*")
        await asyncio.sleep(5)
        try:
            await interaction.channel.edit(archived=True, locked=True)
        except Exception as e:
            logger.error(f"Failed to archive thread: {e}")

async def run_review_process(thread: discord.Thread, filepath: Path):
    """The interactive Q&A loop inside the thread."""
    row = read_csv_row(filepath)
    
    # Intro
    await thread.send(f"**Reviewing:** `{filepath.name}`\nI'll guide you through filling in the missing details.")
    
    # 1. Identify Missing Fields
    ignore_fields = ["Calendar Start", "Calendar End", "Est. Mileage"] # Don't ask about these
    missing = [k for k, v in row.items() if not v and k not in ignore_fields]
    
    if not missing:
        await thread.send("✨ No missing fields detected!")
    else:
        await thread.send(f"**Missing Fields:** {', '.join(missing)}")
        
        for field in missing:
            await thread.send(f"❓ **{field}**: (Type answer, 'skip', or 'auto' to try AI extraction from a pasted email)")
            
            def check(m):
                return m.channel.id == thread.id and not m.author.bot
            
            try:
                msg = await bot.wait_for('message', check=check, timeout=300)
                content = msg.content.strip()
                
                if content.lower() == 'skip':
                    continue
                
                if content.lower() == 'auto':
                    await thread.send("Paste the text/email snippet below:")
                    snippet_msg = await bot.wait_for('message', check=check, timeout=300)
                    # AI Call
                    extraction = await asyncio.to_thread(call_ollama_extract, snippet_msg.content)
                    val = extraction.model_dump(by_alias=True).get(field, "")
                    if val:
                        row[field] = val
                        await thread.send(f"💡 AI extracted: `{val}`")
                    else:
                        await thread.send("⚠️ AI couldn't find it. Skipping.")
                else:
                    row[field] = content
                    
            except asyncio.TimeoutError:
                await thread.send("⏱ Timeout. Stopping review.")
                return

    # Show Summary & Finalize Button
    embed = discord.Embed(title="Final Review", description="Check the details below before publishing.", color=0x00ff00)
    for k, v in row.items():
        if v: embed.add_field(name=k, value=v, inline=True)
        
    await thread.send(embed=embed, view=FinalizeView(filepath, row))


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
        with open(STATE_FILE, "w") as f:
            json.dump({"notified_files": list(notified_files)}, f)
    except Exception as e:
        logger.error(f"Failed to save state: {e}")

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
        logger.warning("DISCORD_CHANNEL_ID is not set or invalid in Master Config.txt. Skipping watch loop.")
        return
        
    channel = bot.get_channel(int(DISCORD_CHANNEL_ID))
    if not channel:
        logger.warning(f"Could not find channel {DISCORD_CHANNEL_ID}. Ensure the bot has access.")
        return

    found_new = False
    # Check Bits folder
    for csv_file in BITS_DIR.glob("*.csv"):
        if csv_file.name in notified_files:
            continue
            
        row = read_csv_row(csv_file)
        if not row: continue

        venue = row.get("Venue") or "Unknown Venue"
        date = row.get("Starting Date") or "Unknown Date"
        missing_count = sum(1 for k, v in row.items() if not v and k not in ["Calendar Start", "Calendar End", "Est. Mileage"])
        
        embed = discord.Embed(
            title="📄 New Contract Processed",
            description=f"**File:** `{csv_file.name}`\n**Gig:** {venue} on {date}",
            color=0xf1c40f
        )
        embed.add_field(name="Status", value=f"{missing_count} missing fields", inline=True)
        embed.set_footer(text="Click below to review and finalize.")
        
        try:
            await channel.send(embed=embed, view=ReviewView(csv_file))
            notified_files.add(csv_file.name)
            found_new = True
        except Exception as e:
            logger.error(f"Failed to send notification for {csv_file.name}: {e}")

    if found_new:
        save_state()

if __name__ == "__main__":
    if not DISCORD_TOKEN:
        logger.error("DISCORD_BOT_TOKEN missing in Master Config.txt")
        print("CRITICAL: Please set DISCORD_BOT_TOKEN and DISCORD_CHANNEL_ID in Master Config.txt")
    else:
        try:
            bot.run(DISCORD_TOKEN)
        except Exception as e:
            logger.error(f"Bot failed to run: {e}")
