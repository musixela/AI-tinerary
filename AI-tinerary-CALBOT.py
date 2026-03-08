#!/usr/bin/env python3
"""
AI-tinerary CALBOT: Your AI Tour Manager

This bot acts as a professional assistant for the band, bridging the gap between
the AI-tinerary CSV pipeline and your team's Discord server.

Upgrades from the basic script:
* Discord UI elements (Select Menus, Buttons) for a modern experience.
* `!status` dashboard for a quick tour readiness overview.
* `!ask` command for general Tour Manager persona chats.
* Smart asynchronous blocking (prevents bot freezes during AI/API calls).
* Automated intelligent datetime parsing for Google Calendar.
"""

import os
import csv
import json
import asyncio
import logging
from pathlib import Path
from datetime import datetime
import requests

# configure logging early so discord.py's import-time warnings can be silenced
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)
# drop the common voice warnings emitted by discord.py at import time
class _VoiceFilter(logging.Filter):
    def filter(self, record):
        msg = record.getMessage()
        if "PyNaCl is not installed" in msg or "davey is not installed" in msg:
            return False
        return True
logging.getLogger().addFilter(_VoiceFilter())
# raise discord loggers to CRITICAL before import
logging.getLogger('discord').setLevel(logging.CRITICAL)
logging.getLogger('discord.voice_client').setLevel(logging.CRITICAL)
logging.getLogger('discord.opus').setLevel(logging.CRITICAL)

# import discord libraries while silencing all output (including low-level C writes)
import sys, os
# temporarily redirect stdout/stderr file descriptors to /dev/null
_orig_stdout_fd = os.dup(1)
_orig_stderr_fd = os.dup(2)
_devnull_fd = os.open(os.devnull, os.O_RDWR)
os.dup2(_devnull_fd, 1)
os.dup2(_devnull_fd, 2)
try:
    import discord
    from discord.ext import commands
finally:
    # restore original descriptors
    os.dup2(_orig_stdout_fd, 1)
    os.dup2(_orig_stderr_fd, 2)
    os.close(_devnull_fd)
from dotenv import load_dotenv


# Google calendar imports
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

ROOT_DIR = Path(__file__).resolve().parent

# Load configuration: .env first (low priority), then Master Config.txt (high priority)
load_dotenv(override=True)
load_dotenv(dotenv_path=ROOT_DIR / "Master Config.txt", override=True)

DISCORD_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
GOOGLE_SERVICE_ACCOUNT_FILE = os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE")
BAND_CALENDAR_ID = os.getenv("BAND_CALENDAR_ID")
PUBLIC_CALENDAR_ID = os.getenv("PUBLIC_CALENDAR_ID")
SCOPES = ["https://www.googleapis.com/auth/calendar"]

OUTPUTS_DIR = ROOT_DIR / "Outputs"

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434/api/generate")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "ministral-3:3b")

# ------------------------------------------------------------------
# Import AI-tinerary Pipeline Logic dynamically
# ------------------------------------------------------------------
import importlib.util

_csv_spec = importlib.util.spec_from_file_location("aitin_csv", ROOT_DIR / "AI-tinerary-CSV.py")
_ai_csv = importlib.util.module_from_spec(_csv_spec)
_csv_spec.loader.exec_module(_ai_csv)

call_ollama_extract = _ai_csv.call_ollama_extract
CSV_HEADERS = _ai_csv.CSV_HEADERS

# --------------------------------------------------
# Helper Utilities
# --------------------------------------------------

def update_master_config(key: str, value: str):
    """Write or update a dotenv-style key/value in the master config file."""
    config_path = ROOT_DIR / "Master Config.txt"
    lines = []
    found = False

    if config_path.exists():
        with open(config_path, "r") as f:
            for line in f:
                if line.strip().startswith(f"{key}="):
                    lines.append(f'{key}="{value}"\n')
                    found = True
                else:
                    lines.append(line)
    if not found:
        lines.append(f'{key}="{value}"\n')

    with open(config_path, "w") as f:
        f.writelines(lines)

def list_csv_files():
    return sorted(p for p in OUTPUTS_DIR.glob("*.csv") if not p.name.lower().startswith("master"))

def read_csv_row(path: Path):
    try:
        with open(path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            return next(reader)
    except Exception as e:
        logger.error(f"Failed to read CSV {path}: {e}")
        return {}

def write_csv_row(path: Path, row: dict):
    headers = list(row.keys())
    # Ensure Calendar headers exist
    if "Calendar Start" not in headers: headers.append("Calendar Start")
    if "Calendar End" not in headers: headers.append("Calendar End")
    try:
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=headers)
            writer.writeheader()
            writer.writerow(row)
    except Exception as e:
        logger.error(f"Failed to write CSV {path}: {e}")

def generate_tm_chat(prompt: str) -> str:
    """Use Ollama to generate a conversational response from the TM persona."""
    sys_prompt = "You are Cal, a highly capable, professional, and slightly witty Tour Manager bot. You assist a band with their itinerary and logistics. Keep your answers concise, helpful, and in plain text."
    payload = {
        "model": OLLAMA_MODEL,
        "prompt": f"{sys_prompt}\n\nUser: {prompt}\nCal:",
        "stream": False
    }
    try:
        r = requests.post(OLLAMA_URL, json=payload, timeout=30)
        r.raise_for_status()
        return r.json().get("response", "").strip()
    except Exception as e:
        return f"*(Ollama seems to be offline or unreachable: {e})*"

# --------------------------------------------------
# Google Calendar & Date Logic
# --------------------------------------------------

def infer_calendar_datetimes(row: dict):
    """Automatically parse natural text dates into ISO 8601 for Google Calendar."""
    try:
        from dateutil import parser
        
        # Determine Start Date
        if not row.get("Calendar Start") and row.get("Starting Date"):
            time_str = row.get("Time") or row.get("Doors") or "19:00"
            try:
                dt = parser.parse(f"{row['Starting Date']} {time_str}", fuzzy=True)
                row["Calendar Start"] = dt.isoformat()
            except Exception:
                pass
                
        # Determine End Date
        if not row.get("Calendar End"):
            end_date_str = row.get("Ending Date") or row.get("Starting Date")
            if end_date_str:
                time_str = "23:59" # Default end time if unknown
                try:
                    dt2 = parser.parse(f"{end_date_str} {time_str}", fuzzy=True)
                    row["Calendar End"] = dt2.isoformat()
                except Exception:
                    pass
    except ImportError:
        pass # python-dateutil not installed

def get_calendar_service():
    if not GOOGLE_SERVICE_ACCOUNT_FILE:
        raise RuntimeError("GOOGLE_SERVICE_ACCOUNT_FILE is not set in config")
    creds = Credentials.from_service_account_file(GOOGLE_SERVICE_ACCOUNT_FILE, scopes=SCOPES)
    return build("calendar", "v3", credentials=creds)

def create_event_from_row(row: dict, calendar_id: str):
    service = get_calendar_service()
    
    summary = row.get("Venue") or "Upcoming Gig"
    location = row.get("Address") or row.get("Location") or ""
    
    desc_lines = [f"**{k}**: {v}" for k, v in row.items() if v and k not in ("Calendar Start", "Calendar End")]
    description = "\n".join(desc_lines)

    event = {
        "summary": summary, 
        "location": location,
        "description": description
    }

    start_iso = row.get("Calendar Start")
    end_iso = row.get("Calendar End")
    
    if start_iso:
        event["start"] = {"dateTime": start_iso}
    else:
        # Fallback to a full-day event using today if completely busted
        event["start"] = {"date": datetime.today().strftime('%Y-%m-%d')}
        
    if end_iso:
        event["end"] = {"dateTime": end_iso}
    else:
        event["end"] = {"date": datetime.today().strftime('%Y-%m-%d')}

    return service.events().insert(calendarId=calendar_id, body=event).execute()

def process_calendar_event(filename: str):
    """Blocking function to handle the Google Calendar API requests."""
    path = OUTPUTS_DIR / filename
    row = read_csv_row(path)
    
    responses = []
    if BAND_CALENDAR_ID:
        try:
            ev = create_event_from_row(row, BAND_CALENDAR_ID)
            responses.append(f"✅ Band calendar event created: [Link]({ev.get('htmlLink')})")
        except Exception as e:
            responses.append(f"❌ Failed to create Band Event: {e}")
            
    if PUBLIC_CALENDAR_ID:
        try:
            ev = create_event_from_row(row, PUBLIC_CALENDAR_ID)
            responses.append(f"✅ Public calendar event created: [Link]({ev.get('htmlLink')})")
        except Exception as e:
            responses.append(f"❌ Failed to create Public Event: {e}")
            
    return responses

# --------------------------------------------------
# Discord UI Components
# --------------------------------------------------

class CalendarButton(discord.ui.Button):
    def __init__(self, filename: str):
        super().__init__(style=discord.ButtonStyle.green, label="📅 Add to Calendar", custom_id="add_calendar")
        self.filename = filename

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_message("Creating calendar events... please wait.", ephemeral=True)
        # Run synchronous API calls in a separate thread
        responses = await asyncio.to_thread(process_calendar_event, self.filename)
        msg = "\n".join(responses) if responses else "⚠️ No Calendar IDs configured in Master Config.txt!"
        await interaction.followup.send(msg)

class FinishView(discord.ui.View):
    def __init__(self, filename: str):
        super().__init__(timeout=None)
        self.add_item(CalendarButton(filename))

class FileSelect(discord.ui.Select):
    def __init__(self, files):
        options = [
            discord.SelectOption(label=f.name, description=f"Update gig details for {f.stem}")
            for f in files[:25] # Discord limits select menus to 25 items
        ]
        super().__init__(placeholder="Select a gig to edit...", max_values=1, min_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        filename = self.values[0]
        await interaction.response.send_message(f"Starting edit for `{filename}`. Check your DMs!", ephemeral=True)
        await start_fill_process(interaction.user, filename, bot)

class FileView(discord.ui.View):
    def __init__(self, files):
        super().__init__(timeout=60)
        self.add_item(FileSelect(files))

# --------------------------------------------------
# Bot Setup & Commands
# --------------------------------------------------

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    print(f"🎸 Tour Manager Bot logged in as {bot.user} (id={bot.user.id})")
    await bot.change_presence(activity=discord.Activity(type=discord.ActivityType.watching, name="the itinerary | !status"))

@bot.command(name="ask")
async def ask(ctx, *, question: str):
    """Ask Cal, your AI Tour Manager, a general question."""
    async with ctx.typing():
        # Prevent blocking the bot's event loop
        reply = await asyncio.to_thread(generate_tm_chat, question)
        await ctx.send(reply)

@bot.command(name="status")
async def status(ctx):
    """Shows tour readiness: what shows are fully booked vs missing data."""
    files = list_csv_files()
    if not files:
        await ctx.send("No gigs found in the Outputs folder!")
        return

    embed = discord.Embed(title="📋 Tour Manager Status Report", description="Overview of upcoming gigs and missing details.", color=0x2ecc71)
    
    # Fields that are okay to be blank
    non_critical = ["DD Notes", "Hospitality", "Contact Details", "Other Details", "Accom Address", "Other Expenses", "Ending Date", "Est. Mileage"]

    for f in files:
        row = read_csv_row(f)
        blanks = [k for k, v in row.items() if not v and k not in non_critical]
        
        venue = row.get("Venue") or f.stem
        date = row.get("Starting Date") or "Unknown Date"

        if not blanks:
            embed.add_field(name=f"✅ {date} - {venue}", value="All critical details logged.", inline=False)
        else:
            embed.add_field(name=f"⚠️ {date} - {venue}", value=f"**Missing:** {', '.join(blanks)}", inline=False)

    await ctx.send(embed=embed)

@bot.command(name="setconfig")
async def setconfig(ctx, key: str, *, value: str):
    """Store a key/value pair in Master Config.txt."""
    update_master_config(key, value)
    await ctx.send(f"✅ Updated `{key}` in Master Config.txt")

@bot.command(name="list")
async def list_files(ctx):
    """List all CSV gigs and show count of missing fields."""
    files = list_csv_files()
    if not files:
        await ctx.send("No gigs found.")
        return
    lines = []
    for f in files:
        row = read_csv_row(f)
        blanks = [k for k, v in row.items() if not v]
        lines.append(f"{f.name}: {len(blanks)} blank(s)")
    await ctx.send("\n".join(lines))

@bot.command(name="combine")
async def combine_cmd(ctx):
    """Force a master CSV recombine using the pipeline's helper."""
    await ctx.send("Combining CSVs...")
    await asyncio.to_thread(_ai_csv.combine_csvs)
    await ctx.send("Done! master-output.csv updated.")

@bot.command(name="fill")
async def fill(ctx, filename: str = None):
    """Interactively fill missing data for a show."""
    files = list_csv_files()
    if not files:
        await ctx.send("No CSV files found to process.")
        return

    if filename:
        path = OUTPUTS_DIR / filename
        if not path.exists():
            await ctx.send(f"❌ File `{filename}` not found.")
            return
        await ctx.send(f"Check your DMs! I'm ready to update `{filename}`.")
        await start_fill_process(ctx.author, filename, bot)
    else:
        await ctx.send("Please select a gig to update:", view=FileView(files))

async def start_fill_process(user: discord.User, filename: str, bot_instance: commands.Bot):
    """Core interactive loop for gathering missing data in DMs."""
    path = OUTPUTS_DIR / filename
    row = read_csv_row(path)
    blanks = [k for k, v in row.items() if not v]
    
    dm = await user.create_dm()

    # Build intro embed
    title = f"Editing Gig: {row.get('Venue') or path.stem}"
    embed = discord.Embed(title=title, description="Let's get this itinerary sorted.", color=0x3498db)
    if blanks:
        embed.add_field(name="Currently Missing", value=", ".join(blanks))
    await dm.send(embed=embed)

    # Conversational Phase
    while blanks:
        await dm.send("Tell me anything you know about this gig in plain English.\n*(Or type `done` to move on, `skip` to skip freeform extraction)*")
        
        def _check(m: discord.Message):
            return m.author == user and isinstance(m.channel, discord.DMChannel)
            
        try:
            msg = await bot_instance.wait_for("message", check=_check, timeout=600)
        except asyncio.TimeoutError:
            await dm.send("⏱ Timeout reached. Moving to manual entry...")
            break

        text = msg.content.strip()
        if text.lower() in ["done", "skip"]:
            break

        await dm.send("Thinking... 🧠")
        # Run Ollama extraction in a separate thread so it doesn't freeze the bot
        extracted = await asyncio.to_thread(call_ollama_extract, text)
        ex_dict = extracted.model_dump(by_alias=True)
        
        changed = False
        for k, v in ex_dict.items():
            if v and (not row.get(k) or row.get(k) != v):
                row[k] = v
                changed = True
                
        if changed:
            summary = "\n".join(f"**{k}**: {row[k]}" for k in sorted(row) if row[k])
            await dm.send(f"Got it! Here is the updated file:\n{summary}")

        blanks = [k for k, v in row.items() if not v]
        if not blanks:
            await dm.send("Looks like we have everything now!")

    # Direct Question Phase for critical missing data
    blanks = [k for k, v in row.items() if not v]
    for field in blanks:
        await dm.send(f"What is the **{field}**? *(Reply with `skip` to leave blank)*")
        
        try:
            msg = await bot_instance.wait_for("message", check=_check, timeout=300)
            text = msg.content.strip()
            if text.lower() != "skip":
                row[field] = text
        except asyncio.TimeoutError:
            await dm.send("⏱ Timeout reached. Skipping.")

    # Smart Datetime Inference
    infer_calendar_datetimes(row)

    write_csv_row(path, row)
    
    # Send completion UI
    await dm.send(
        f"🎉 Finished updating `{filename}`! The master spreadsheet will reflect this on the next run.",
        view=FinishView(filename)
    )

if __name__ == "__main__":
    if not DISCORD_TOKEN:
        print("ERROR: DISCORD_BOT_TOKEN not set in Master Config.txt")
        exit(1)
    bot.run(DISCORD_TOKEN)
