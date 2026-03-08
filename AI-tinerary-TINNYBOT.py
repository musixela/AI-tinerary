#!/usr/bin/env python3
"""
AI-tinerary TINNYBOT: The Markdown Tour Packet Generator
Operates as a Discord Cog loaded into CALBOT.
"""

import csv
import json
import logging
import asyncio
from pathlib import Path
from datetime import datetime, timedelta
from dateutil import parser
import requests

import discord
from discord.ext import commands

from constants import MASTER_CSV, ITINERARIES_DIR
import os

logger = logging.getLogger(__name__)

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434/api/generate")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "ministral-3:3b")

class TinnyBot(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    def get_gigs_in_range(self, start_date_str, end_date_str=None):
        if not MASTER_CSV.exists():
            return []
            
        gigs = []
        try:
            start_dt = parser.parse(start_date_str).date()
            end_dt = parser.parse(end_date_str).date() if end_date_str else start_dt

            with open(MASTER_CSV, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    gig_date_str = row.get("Starting Date")
                    if not gig_date_str: continue
                    try:
                        gig_dt = parser.parse(gig_date_str).date()
                        if start_dt <= gig_dt <= end_dt:
                            gigs.append(row)
                    except:
                        pass
        except Exception as e:
            logger.error(f"Date parsing error: {e}")
            
        # Sort chronologically
        gigs.sort(key=lambda x: x.get("Starting Date", ""))
        return gigs

    async def generate_survival_guide(self, gigs):
        """Asks Ollama for a customized packing list and survival guide based on the tour data."""
        if not gigs: return "*No gig data provided.*"
        
        tour_summary = "\n".join([f"- {g['Starting Date']}: {g['Venue']} in {g['Location']} (Routing: {g.get('Routing', 'N/A')})" for g in gigs])
        
        prompt = f"""
You are an expert Tour Manager. The band is embarking on the following tour dates:
{tour_summary}

Based on these locations and the driving routing, generate a brief 'Survival Guide & Packing List' for the band. 
Consider weather, drive times, and standard gig necessities. 
Format as a clean Markdown bulleted list. Keep it fun but highly practical. Do not use pleasantries.
"""
        try:
            r = await asyncio.to_thread(
                requests.post, 
                OLLAMA_URL, 
                json={"model": OLLAMA_MODEL, "prompt": prompt, "stream": False}, 
                timeout=120
            )
            r.raise_for_status()
            return r.json().get("response", "*AI Generation failed.*")
        except Exception as e:
            logger.error(f"Ollama Survival Guide failed: {e}")
            return "*Could not generate survival guide (AI offline).*_ \n\n **Standard Checklist:**\n- [ ] Instruments & Cables\n- [ ] Merch & Cash Box\n- [ ] Hotel Info"

    def calculate_timeline(self, gig, interview_data):
        """Merges fixed CSV times with Interview times and calculates Free Time."""
        events = []
        date_str = gig.get("Starting Date")
        
        # Helper to parse times safely
        def add_event(time_str, label, desc):
            if not time_str: return
            try:
                # Handle ISO formats or loose times
                if "T" in time_str: 
                    dt = parser.parse(time_str)
                else:
                    dt = parser.parse(f"{date_str} {time_str}")
                events.append({"time": dt, "label": label, "desc": desc})
            except Exception as e:
                logger.warning(f"Could not parse time '{time_str}' for {label}: {e}")

        # 1. Standard CSV Events
        add_event(gig.get("Departure Time"), "🚐 Departure", f"Leave {gig.get('Routing', '').split('->')[0].strip() or 'Home'}")
        add_event(gig.get("Load In"), "📦 Load In", "Arrive at venue, load gear.")
        add_event(gig.get("Doors"), "🚪 Doors", "Venue opens to public.")
        add_event(gig.get("Time"), "🤘 Show Time", "Set begins.")
        add_event(gig.get("Calendar End"), "🍻 End", "Approximate end/load out.")

        # 2. Interview Events
        if interview_data.get("soundcheck"):
            add_event(interview_data["soundcheck"], "🎤 Soundcheck", "Line check and levels.")
        if interview_data.get("dinner"):
            add_event(interview_data["dinner"], "🍔 Dinner", "Band meal.")
        if interview_data.get("other"):
            add_event(interview_data["other"], "📌 Note", "Custom event.")

        # 3. Sort chronologically
        events.sort(key=lambda x: x["time"])

        # 4. Inject "Free Time" Buffers
        timeline = []
        for i in range(len(events)):
            timeline.append(events[i])
            if i < len(events) - 1:
                gap_minutes = (events[i+1]["time"] - events[i]["time"]).total_seconds() / 60
                # If there's an unexplained gap of > 75 minutes, inject a free time block
                if gap_minutes > 75:
                    free_start = events[i]["time"] + timedelta(minutes=15) # Assuming event takes 15m to wrap
                    timeline.append({
                        "time": free_start,
                        "label": "🛋️ Free Time",
                        "desc": f"~{int(gap_minutes - 15)} mins of buffer time."
                    })

        return timeline

    def generate_markdown(self, gigs, all_interview_data, survival_guide, filename):
        """Constructs the beautiful Markdown artifact."""
        
        md = f"# 🎸 Tour Packet: {gigs[0]['Starting Date']}"
        if len(gigs) > 1:
             md += f" to {gigs[-1]['Starting Date']}"
        md += "\n\n---\n\n"

        # Gig Days
        for gig in gigs:
            date_str = gig.get("Starting Date")
            venue = gig.get("Venue", "Unknown Venue")
            loc = gig.get("Location", "")
            
            md += f"## 📅 {date_str} - {venue} ({loc})\n"
            
            # Timeline
            md += "### ⏱️ The Timeline\n"
            timeline = self.calculate_timeline(gig, all_interview_data.get(date_str, {}))
            if not timeline:
                md += "*No time data available.*\n"
            else:
                for event in timeline:
                    time_fmt = event["time"].strftime("%I:%M %p")
                    # Italicize Free Time
                    if "Free Time" in event["label"]:
                        md += f"* **{time_fmt}** - *{event['label']} ({event['desc']})*\n"
                    else:
                        md += f"* **{time_fmt}** - **{event['label']}** ({event['desc']})\n"
            
            # Details
            md += "\n### 📋 Gig Details\n"
            md += f"- **Address:** {gig.get('Address', 'N/A')}\n"
            md += f"- **Contact:** {gig.get('Contact Name', 'N/A')} ({gig.get('Contact Details', 'N/A')})\n"
            md += f"- **Pay/Deal:** {gig.get('Pay', 'N/A')} | Door Deal: {gig.get('Door Deal', 'N/A')}\n"
            md += f"- **Hospitality:** {gig.get('Hospitality', 'N/A')}\n"
            md += f"- **Sound:** System: {gig.get('Sound - System', 'N/A')} | Engineer: {gig.get('Sound - Person', 'N/A')}\n"
            
            if gig.get("Accom Address"):
                md += f"- **Accommodations:** {gig.get('Accom Address')}\n"
                
            if gig.get("Other Details"):
                 md += f"- **Notes:** {gig.get('Other Details')}\n"
                 
            md += "\n---\n\n"

        # Survival Guide
        md += "## 🤖 TINNYBOT's Survival Guide\n"
        md += survival_guide + "\n"

        # Save to disk
        filepath = ITINERARIES_DIR / filename
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(md)
            
        return filepath

    @commands.group(name="tinny", aliases=["tinnybot"], invoke_without_command=True)
    async def tinny_base(self, ctx):
        await ctx.send("🤖 **TINNYBOT**\nUsage: `!tinny generate YYYY-MM-DD` or `!tinny generate YYYY-MM-DD YYYY-MM-DD`")

    @tinny_base.command(name="generate")
    async def tinny_generate(self, ctx, start_date: str, end_date: str = None):
        """Starts the interactive itinerary generation process."""
        gigs = self.get_gigs_in_range(start_date, end_date)
        
        if not gigs:
            await ctx.send(f"❌ Could not find any gigs between {start_date} and {end_date or start_date} in the master CSV.")
            return

        thread_name = f"🗓️ Itinerary Prep: {start_date}"
        if end_date: thread_name += f" to {end_date}"
        
        thread = await ctx.message.create_thread(name=thread_name)
        await ctx.send(f"Started Tour Packet interview in {thread.mention}")

        all_interview_data = {}

        # 1. Interview Loop
        def check(m): return m.channel.id == thread.id and m.author == ctx.author

        for gig in gigs:
            date_str = gig["Starting Date"]
            venue = gig.get("Venue")
            all_interview_data[date_str] = {}
            
            await thread.send(f"**🎸 Regarding the show at {venue} on {date_str}:**\nWhat time is **Soundcheck**? (Reply with time, e.g., '4:00 PM', or 'skip')")
            try:
                msg = await self.bot.wait_for('message', check=check, timeout=120)
                if msg.content.lower() != 'skip':
                    all_interview_data[date_str]["soundcheck"] = msg.content.strip()
            except asyncio.TimeoutError:
                await thread.send("⏱ Timeout. Skipping soundcheck.")

            await thread.send(f"What time/where is **Dinner**? (e.g., '5:30 PM at Venue', or 'skip')")
            try:
                msg = await self.bot.wait_for('message', check=check, timeout=120)
                if msg.content.lower() != 'skip':
                    # Best effort to extract time vs notes. If they write "5:30 PM at Venue", dateutil handles it decently, 
                    # but we will just pass the whole string to dateutil later and hope for the best, 
                    # or they can just provide time. Let's ask for strict time.
                    all_interview_data[date_str]["dinner"] = msg.content.strip()
            except asyncio.TimeoutError:
                 await thread.send("⏱ Timeout. Skipping dinner.")
                 
            await thread.send(f"Any other special events or VIPs for {venue}? (Provide Time + Note, e.g., '6:30 PM Meet and Greet', or 'skip')")
            try:
                msg = await self.bot.wait_for('message', check=check, timeout=120)
                if msg.content.lower() != 'skip':
                    all_interview_data[date_str]["other"] = msg.content.strip()
            except asyncio.TimeoutError:
                 pass

        # 2. Generate Ollama Survival Guide
        await thread.send("🧠 *Interview complete! Asking AI for survival and packing recommendations...*")
        survival_guide = await self.generate_survival_guide(gigs)

        # 3. Generate Markdown
        await thread.send("📄 *Assembling Tour Packet...*")
        filename = f"Tour_Packet_{start_date}.md"
        if end_date: filename = f"Tour_Packet_{start_date}_to_{end_date}.md"
        
        filepath = self.generate_markdown(gigs, all_interview_data, survival_guide, filename)

        # 4. Upload to Discord
        await thread.send("✅ **Tour Packet Generated!** Ready for the road.", file=discord.File(filepath))

async def setup(bot):
    await bot.add_cog(TinnyBot(bot))