#!/usr/bin/env python3
"""
Discord + Google Calendar helper for AI-tinerary

This module launches a simple Discord bot that knows how to:

* Scan the `Outputs/` directory for `.csv` files produced by the
  AI-tinerary pipeline.
* Walk you through any missing fields by asking a series of questions in
  Discord (either in a server channel or via DM).
* Persist updates back to the CSV so the master spreadsheet stays
  complete.
* Create Google Calendar events in two calendars (band & public) using
  a service account.
* Update the `Master Config.txt` file with new environment values.

The bot is intentionally minimal; questions are driven by a small script
(`QUESTION_SCRIPT`) that can be extended at any time.  To skip a question
simply reply with `skip` (case‑insensitive) and the field will remain blank.

Environment configuration is pulled from the same `Master Config.txt` file
used by the rest of the project via `python-dotenv`.

Run:

    python AI-tinerary-CALBOT.py

...after you've added the Discord token and Google calendar settings to
`Master Config.txt`.
"""

import os
import csv
import asyncio
from pathlib import Path
from datetime import datetime

import discord
from discord.ext import commands
from dotenv import load_dotenv

# Google calendar imports
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

# --------------------------------------------------
# configuration
# --------------------------------------------------

ROOT_DIR = Path(__file__).resolve().parent
load_dotenv(dotenv_path=ROOT_DIR / "Master Config.txt")

# Discord
DISCORD_TOKEN = os.getenv("DISCORD_BOT_TOKEN")

# Google calendar
GOOGLE_SERVICE_ACCOUNT_FILE = os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE")
BAND_CALENDAR_ID = os.getenv("BAND_CALENDAR_ID")
PUBLIC_CALENDAR_ID = os.getenv("PUBLIC_CALENDAR_ID")
SCOPES = ["https://www.googleapis.com/auth/calendar"]

# outputs path used by the original pipeline
OUTPUTS_DIR = ROOT_DIR / "Outputs"

# ------------------------------------------------------------------
# helper: reuse the contract-extraction AI logic from the CSV script.
# This allows us to hand freeform text to the same prompt that already
# knows how to populate the spreadsheet schema.
import importlib.util, sys

_csv_spec = importlib.util.spec_from_file_location("aitin_csv", ROOT_DIR / "AI-tinerary-CSV.py")
_ai_csv = importlib.util.module_from_spec(_csv_spec)
_csv_spec.loader.exec_module(_ai_csv)

# expose a convenient wrapper here
call_ollama_extract = _ai_csv.call_ollama_extract
CSV_HEADERS = _ai_csv.CSV_HEADERS

# ------------------------------------------------------------------

# --------------------------------------------------
# helper utilities
# --------------------------------------------------

def update_master_config(key: str, value: str):
    """Write or update a dotenv-style key/value in the master config file."""
    config_path = ROOT_DIR / "Master Config.txt"
    lines = []
    found = False

    # read existing lines and replace the key if present
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


async def ask_for_value(user: discord.User, prompt: str, timeout: int = 300):
    """Send a DM to the user asking for input and wait for a response."""
    try:
        dm = await user.create_dm()
        await dm.send(prompt + " (reply with `skip` to leave blank)")

        def check(m: discord.Message):
            return m.author == user and isinstance(m.channel, discord.DMChannel)

        msg = await bot.wait_for("message", check=check, timeout=timeout)
        text = msg.content.strip()
        if text.lower() == "skip":
            return None
        return text
    except asyncio.TimeoutError:
        await dm.send("⏱ Timeout reached – moving on.")
        return None


def list_csv_files():
    return sorted(p for p in OUTPUTS_DIR.glob("*.csv") if not p.name.lower().startswith("master"))


def read_csv_row(path: Path):
    # assumes single-row CSV with header
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return next(reader)


def write_csv_row(path: Path, row: dict):
    headers = list(row.keys())
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        writer.writeheader()
        writer.writerow(row)


### question script -- modify/append as needed
QUESTION_SCRIPT = [
    ("Starting Date", "Starting date (M/D or M/D/YYYY)") ,
    ("Ending Date", "Ending date (blank if single-day)") ,
    ("Venue", "Venue name") ,
    ("Location", "City, State") ,
    ("Address", "Full street address") ,
    ("Time", "Show start time") ,
    ("Doors", "Door time") ,
    ("Load In", "Load-in time") ,
    ("Pay", "Guaranteed pay") ,
    # calendar-related questions can be added later, e.g.:
    # ("Calendar Start", "Event start datetime (ISO)"),
    # ("Calendar End", "Event end datetime (ISO)"),
]

# --------------------------------------------------
# Google calendar helpers
# --------------------------------------------------

def get_calendar_service():
    if not GOOGLE_SERVICE_ACCOUNT_FILE:
        raise RuntimeError("GOOGLE_SERVICE_ACCOUNT_FILE is not set in config")
    creds = Credentials.from_service_account_file(GOOGLE_SERVICE_ACCOUNT_FILE, scopes=SCOPES)
    return build("calendar", "v3", credentials=creds)


def create_event_from_row(row: dict, calendar_id: str):
    """Build and insert a calendar event based on a CSV row."""
    service = get_calendar_service()

    # basic summary and description
    summary = row.get("Venue") or "Show"
    description = "\n".join(f"{k}: {v}" for k, v in row.items() if v)

    event = {"summary": summary, "description": description}

    # attempt to use calendar-specific fields if they exist
    start_iso = row.get("Calendar Start")
    end_iso = row.get("Calendar End")
    if start_iso:
        event["start"] = {"dateTime": start_iso}
    if end_iso:
        event["end"] = {"dateTime": end_iso}

    return service.events().insert(calendarId=calendar_id, body=event).execute()


# --------------------------------------------------
# Bot setup
# --------------------------------------------------

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)


@bot.event
async def on_ready():
    print(f"Bot logged in as {bot.user} (id={bot.user.id})")


@bot.command(name="setconfig")
async def setconfig(ctx, key: str, *, value: str):
    """Store a key/value pair in Master Config.txt."""
    update_master_config(key, value)
    await ctx.send(f"Updated `{key}` in Master Config.txt")


@bot.command(name="fill")
async def fill(ctx, filename: str = None):
    """Use AI to find blanks in one or all CSVs, ask for any missing data,
    and update the files.  The interaction is conversational so you can
    answer in plain English; the bot will summarise and follow up until
    the sheet is complete or you signal you're done.
    """
    user = ctx.author
    targets = []
    if filename:
        path = OUTPUTS_DIR / filename
        if not path.exists():
            await ctx.send(f"File {filename} not found")
            return
        targets = [path]
    else:
        targets = list_csv_files()

    if not targets:
        await ctx.send("No CSV files found to process.")
        return

    await ctx.send(f"Alright, I'll DM you to work through {len(targets)} file(s).")

    for path in targets:
        row = read_csv_row(path)
        blanks = [k for k, v in row.items() if not v]
        dm = await user.create_dm()
        await dm.send(f"\n=== Editing {path.name} ===")

        # conversational loop: collect user descriptions until blanks filled or user quits
        while blanks:
            await dm.send(
                "Tell me anything you know about this show or contract. "
                "I’ll try to fill in missing fields for you."
            )
            def _check(m: discord.Message):
                return m.author == user and isinstance(m.channel, discord.DMChannel)
            try:
                msg = await bot.wait_for("message", check=_check, timeout=600)
            except asyncio.TimeoutError:
                await dm.send("⏱ Timeout reached. If you're still there, send me more info or type `done`.")
                break

            text = msg.content.strip()
            if text.lower() == "done":
                break

            # use AI to interpret whatever the user said
            extracted = call_ollama_extract(text)
            ex_dict = extracted.model_dump(by_alias=True)
            changed = False
            for k, v in ex_dict.items():
                if v and (not row.get(k) or row.get(k) != v):
                    row[k] = v
                    changed = True
            if changed:
                await dm.send("Here's what I've filled so far:")
                summary = "\n".join(f"{k}: {row[k]}" for k in sorted(row) if row[k])
                await dm.send(summary)

            blanks = [k for k, v in row.items() if not v]
            if blanks:
                await dm.send("I'm still missing: " + ", ".join(blanks))
            else:
                await dm.send("All fields look complete now. Type `done` if you're happy.")

        # final explicit questions for any remaining blanks
        for field in blanks:
            answer = await ask_for_value(user, f"Could you tell me the {field.lower()}?")
            if answer is not None:
                row[field] = answer

                # attempt to auto‑fill calendar datetimes if we have simple date/time info
        try:
            from dateutil import parser

            if not row.get("Calendar Start"):
                if row.get("Starting Date") and row.get("Time"):
                    try:
                        dt = parser.parse(f"{row['Starting Date']} {row['Time']}", fuzzy=True)
                        row["Calendar Start"] = dt.isoformat()
                    except Exception:
                        pass
            if not row.get("Calendar End"):
                # use Ending Date if provided, otherwise reuse start
                if row.get("Ending Date"):
                    try:
                        dt2 = parser.parse(f"{row['Ending Date']} {row.get('Time','')}", fuzzy=True)
                        row["Calendar End"] = dt2.isoformat()
                    except Exception:
                        pass
        except ImportError:
            # dateutil not installed; skip inference
            pass

        write_csv_row(path, row)
        await dm.send(f"Finished updating {path.name} 🎉")
    await ctx.send("Done processing all files. Check your DMs for notes.")


@bot.command(name="event")
async def event(ctx, filename: str):
    """Create calendar event(s) for a specific CSV file."""
    path = OUTPUTS_DIR / filename
    if not path.exists():
        await ctx.send(f"File {filename} not found")
        return
    row = read_csv_row(path)

    # ask for start/end if not present
    if not row.get("Calendar Start"):
        ans = await ask_for_value(ctx.author, "Event start datetime (ISO 8601)")
        if ans:
            row["Calendar Start"] = ans
    if not row.get("Calendar End"):
        ans = await ask_for_value(ctx.author, "Event end datetime (ISO 8601)")
        if ans:
            row["Calendar End"] = ans

    # persist any new values
    write_csv_row(path, row)

    responses = []
    if BAND_CALENDAR_ID:
        ev = create_event_from_row(row, BAND_CALENDAR_ID)
        responses.append(f"Band calendar event created: {ev.get('htmlLink')}")
    if PUBLIC_CALENDAR_ID:
        ev = create_event_from_row(row, PUBLIC_CALENDAR_ID)
        responses.append(f"Public calendar event created: {ev.get('htmlLink')}")

    if responses:
        await ctx.send("\n".join(responses))
    else:
        await ctx.send("No calendar IDs configured; add BAND_CALENDAR_ID and/or PUBLIC_CALENDAR_ID in Master Config.txt")


if __name__ == "__main__":
    if not DISCORD_TOKEN:
        print("ERROR: DISCORD_BOT_TOKEN not set in Master Config.txt")
        exit(1)
    bot.run(DISCORD_TOKEN)
