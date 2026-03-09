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
from dotenv import load_dotenv

from constants import MASTER_CSV, ITINERARIES_DIR, ROOT_DIR, PROMPTS_DIR
import os

logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv(override=True)
load_dotenv(dotenv_path=ROOT_DIR / "Master Config.txt", override=True)

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434/api/generate")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "ministral-3:3b")
OLLAMA_NUM_CTX = int(os.getenv("OLLAMA_NUM_CTX", "16384"))

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
        
        # Load prompt from file
        prompt_path = PROMPTS_DIR / "TINNYBOT-survival_guide.txt"
        if prompt_path.exists():
            prompt = prompt_path.read_text(encoding="utf-8")
            prompt = prompt.replace("{{tour_summary}}", tour_summary)
        else:
            logger.warning(f"Prompt file not found: {prompt_path}. Using fallback.")
            prompt = f"Generate a brief 'Survival Guide & Packing List' for these tour dates: {tour_summary}"

        try:
            r = await asyncio.to_thread(
                requests.post, 
                OLLAMA_URL, 
                json={
                    "model": OLLAMA_MODEL, 
                    "prompt": prompt, 
                    "stream": False,
                    "options": {"num_ctx": OLLAMA_NUM_CTX}
                }, 
                timeout=120
            )
            r.raise_for_status()
            return r.json().get("response", "*AI Generation failed.*")
        except Exception as e:
            logger.error(f"Ollama Survival Guide failed: {e}")
            return "*Could not generate survival guide (AI offline).*_ \n\n **Standard Checklist:**\n- [ ] Instruments & Cables\n- [ ] Merch & Cash Box\n- [ ] Hotel Info"

    async def generate_full_itinerary(self, gig, interview_data):
        """Asks Ollama to generate a detailed minute-by-minute schedule (Step 3)."""
        date_str = gig.get("Starting Date")
        venue = gig.get("Venue", "Unknown Venue")
        loc = gig.get("Location", "")
        routing = gig.get("Routing", "N/A")
        
        # Gather all known time data
        known_times = {
            "Departure": gig.get("Departure Time"),
            "Load In": gig.get("Load In"),
            "Doors": gig.get("Doors"),
            "Show Time": gig.get("Time"),
            "End": gig.get("Calendar End"),
            "Soundcheck": interview_data.get("soundcheck"),
            "Dinner": interview_data.get("dinner"),
            "Other Notes": interview_data.get("other"),
            "Waypoints/Stops": gig.get("Other Details", "")
        }
        
        # Load system prompt from file
        prompt_path = PROMPTS_DIR / "TINNYBOT-full_itinerary.txt"
        if prompt_path.exists():
            system_prompt = prompt_path.read_text(encoding="utf-8")
            system_prompt = system_prompt.replace("{{date_str}}", date_str)
            system_prompt = system_prompt.replace("{{venue}}", venue)
            system_prompt = system_prompt.replace("{{loc}}", loc)
            system_prompt = system_prompt.replace("{{known_times}}", json.dumps(known_times, indent=2))
            system_prompt = system_prompt.replace("{{routing}}", routing)
        else:
            logger.warning(f"Prompt file not found: {prompt_path}. Using fallback.")
            system_prompt = f"Create a minute-by-minute schedule for {date_str} at {venue} in {loc}."

        try:
            r = await asyncio.to_thread(
                requests.post, 
                OLLAMA_URL, 
                json={
                    "model": OLLAMA_MODEL, 
                    "prompt": system_prompt, 
                    "stream": False,
                    "options": {"num_ctx": OLLAMA_NUM_CTX}
                }, 
                timeout=120
            )
            r.raise_for_status()
            return r.json().get("response", "*AI Generation failed.*")
        except Exception as e:
            logger.error(f"Ollama Itinerary failed: {e}")
            return "*Could not generate detailed itinerary (AI offline).*"

    async def generate_markdown(self, gigs, all_interview_data, survival_guide, filename):
        """Constructs the beautiful Markdown artifact (Refactored for Step 3)."""
        
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
            
            # Timeline (Step 3: AI-Driven Scheduling)
            md += "### ⏱️ The Timeline\n"
            itinerary = await self.generate_full_itinerary(gig, all_interview_data.get(date_str, {}))
            md += itinerary + "\n"
            
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
        
        filepath = await self.generate_markdown(gigs, all_interview_data, survival_guide, filename)

        # 4. Upload to Discord
        await thread.send("✅ **Tour Packet Generated!** Ready for the road.", file=discord.File(filepath))

async def setup(bot):
    await bot.add_cog(TinnyBot(bot))
