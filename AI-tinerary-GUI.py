#!/usr/bin/env python3
"""
AI-tinerary GUI Manager
A graphical interface for managing the AI-tinerary toolsuite using customtkinter.
Enhanced with Multi-Config Profiles, Dual-Log Dashboard, and Log Exporting.
"""

import os
import sys
import json
import re
import threading
import subprocess
import time
import webbrowser
import shutil
from pathlib import Path
import datetime
import tkinter as tk
from tkinter import messagebox, filedialog
import customtkinter

# Optional: Import requests. If not available (e.g., outside venv), handle gracefully.
try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False


ROOT_DIR = Path(__file__).resolve().parent
CONFIGS_DIR = ROOT_DIR / "Configs"
MASTER_CONFIG_PATH = ROOT_DIR / "Master Config.txt"
GS_EMEX_PATH = ROOT_DIR / "google_scripts" / "AI-tinerary-EMEX.gs"
GS_SHSY_PATH = ROOT_DIR / "google_scripts" / "AI-tinerary-SHSY.gs"

# Ensure Configs directory exists
CONFIGS_DIR.mkdir(exist_ok=True)

# Keys in Master Config
CONFIG_KEYS = [
    "HOME_BASE_ADDRESS",
    "ORS_API_KEY",
    "ORS_BASE_URL",
    "OLLAMA_URL",
    "OLLAMA_MODEL",
    "OLLAMA_NUM_CTX",
    "MAX_THREADS",
    "TIMEZONE",
    "DISCORD_BOT_TOKEN",
    "DISCORD_CHANNEL_ID",
    "GOOGLE_SERVICE_ACCOUNT_FILE",
    "BAND_CALENDAR_ID",
    "PUBLIC_CALENDAR_ID"
]

# Set appearance and theme
customtkinter.set_appearance_mode("Dark")
customtkinter.set_default_color_theme("blue")

class AItineraryGUI(customtkinter.CTk):
    def __init__(self):
        super().__init__()
        self.title("🎸 AI-tinerary Manager")
        self.geometry("1100x900")
        
        # Runtime States
        self.calbot_process = None
        self.ollama_process = None
        self.ollama_status = "Unknown"
        self.ollama_models = []
        self.current_profile = tk.StringVar(value="Default")
        
        self.config_vars = {}
        self.gs_emex_vars = {}
        self.gs_shsy_vars = {}

        self.setup_ui()
        self.init_profiles()
        self.load_gs_config()
        
        # macOS Trackpad Fix
        if sys.platform == "darwin":
            self.bind_all("<MouseWheel>", self._on_mousewheel_macos)
        
        # Start background polling
        self.poll_thread = threading.Thread(target=self.background_polling, daemon=True)
        self.poll_thread.start()

    def _on_mousewheel_macos(self, event):
        delta = -1 * event.delta
        widget = self.winfo_containing(event.x_root, event.y_root)
        while widget:
            if isinstance(widget, (tk.Canvas, tk.Text, customtkinter.CTkTextbox)):
                widget.yview_scroll(delta, "units")
                return
            if hasattr(widget, "_canvas"):
                widget._canvas.yview_scroll(delta, "units")
                return
            widget = widget.master if hasattr(widget, "master") else None

    def setup_ui(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=0) # Reserved for side panel
        self.grid_rowconfigure(1, weight=1)

        # Header with Theme Toggle & Wiki
        self.header = customtkinter.CTkFrame(self, fg_color="transparent")
        self.header.grid(row=0, column=0, columnspan=2, padx=20, pady=(15, 0), sticky="ew")
        self.header.grid_columnconfigure(0, weight=1)
        
        customtkinter.CTkLabel(self.header, text="🎸 AI-tinerary Manager", font=("Arial", 22, "bold")).grid(row=0, column=0, sticky="w")
        
        header_btns = customtkinter.CTkFrame(self.header, fg_color="transparent")
        header_btns.grid(row=0, column=1, sticky="e")
        
        self.theme_btn = customtkinter.CTkButton(header_btns, text="🌙", width=40, font=("Arial", 16), command=self.toggle_theme)
        self.theme_btn.pack(side="left", padx=5)
        
        self.wiki_btn = customtkinter.CTkButton(header_btns, text="📖 Wiki", width=80, command=self.toggle_wiki_panel)
        self.wiki_btn.pack(side="left", padx=5)

        self.tabview = customtkinter.CTkTabview(self, width=1050, height=850)
        self.tabview.grid(row=1, column=0, padx=(20, 10), pady=(10, 20), sticky="nsew")
        
        # Side Wiki Panel (Hidden by default)
        self.wiki_panel = None
        self.wiki_visible = False
        
        self.tabview.add("🚀 Dashboard")
        self.tabview.add("⚙️ Master Config")
        self.tabview.add("🎭 Prompts")
        self.tabview.add("📂 Files & Links")
        self.tabview.add("☁️ Google Scripts")
        self.tabview.add("🛠️ Environment")
        
        self.build_dashboard(self.tabview.tab("🚀 Dashboard"))
        self.build_config_tab(self.tabview.tab("⚙️ Master Config"))
        self.build_prompts_tab(self.tabview.tab("🎭 Prompts"))
        self.build_files_tab(self.tabview.tab("📂 Files & Links"))
        self.build_gscripts_tab(self.tabview.tab("☁️ Google Scripts"))
        self.build_env_tab(self.tabview.tab("🛠️ Environment"))

    # ==========================================
    # TAB 1: DASHBOARD
    # ==========================================
    def build_dashboard(self, tab):
        scroll_frame = customtkinter.CTkScrollableFrame(tab, fg_color="transparent")
        scroll_frame.pack(fill="both", expand=True)
        scroll_frame.grid_columnconfigure(0, weight=1)
        
        # Quick Stats Bar
        stats_bar = customtkinter.CTkFrame(scroll_frame, fg_color="transparent")
        stats_bar.pack(fill="x", padx=10, pady=(5, 10))
        stats_bar.grid_columnconfigure((0, 1, 2), weight=1)
        
        self.lbl_stat_incoming = self.create_stat_widget(stats_bar, "📥 Pending Contracts", "0", 0)
        self.lbl_stat_bits = self.create_stat_widget(stats_bar, "⏳ Waiting Review", "0", 1)
        self.lbl_stat_processed = self.create_stat_widget(stats_bar, "✅ Processed Today", "0", 2)

        # Ollama Section
        self.lf_ollama = customtkinter.CTkFrame(scroll_frame)
        self.lf_ollama.pack(fill="x", padx=10, pady=10)
        customtkinter.CTkLabel(self.lf_ollama, text="🧠 Ollama Local AI", font=("Arial", 14, "bold")).pack(anchor="w", padx=15, pady=(10, 5))
        
        ollama_controls = customtkinter.CTkFrame(self.lf_ollama, fg_color="transparent")
        ollama_controls.pack(fill="x", padx=15, pady=(0, 10))
        
        self.lbl_ollama_status = customtkinter.CTkLabel(ollama_controls, text="Status: Checking...", font=("Arial", 12, "bold"))
        self.lbl_ollama_status.pack(side="left", padx=5)

        customtkinter.CTkButton(ollama_controls, text="▶ Start", width=70, command=self.start_ollama).pack(side="left", padx=(15, 2))
        customtkinter.CTkButton(ollama_controls, text="⏹ Stop", width=70, fg_color="#606060", hover_color="#404040", command=self.stop_ollama).pack(side="left", padx=2)
        customtkinter.CTkButton(ollama_controls, text="🔄 Restart", width=80, command=self.restart_ollama).pack(side="left", padx=2)

        customtkinter.CTkLabel(ollama_controls, text="Active Model:").pack(side="left", padx=(20, 5))
        self.cbo_models = customtkinter.CTkComboBox(ollama_controls, width=180, values=["Loading..."], command=self.on_model_changed_ctk)
        self.cbo_models.set("Loading...")
        self.cbo_models.pack(side="left", padx=5)
        
        customtkinter.CTkButton(ollama_controls, text="Refresh Models", width=120, command=self.start_fetch_ollama_models).pack(side="left", padx=10)

        # Context Token Slider Row
        ollama_ctx_row = customtkinter.CTkFrame(self.lf_ollama, fg_color="transparent")
        ollama_ctx_row.pack(fill="x", padx=15, pady=(0, 10))
        
        customtkinter.CTkLabel(ollama_ctx_row, text="Context Tokens (num_ctx):").pack(side="left", padx=5)
        self.lbl_ctx_value = customtkinter.CTkLabel(ollama_ctx_row, text="16,384", font=("Arial", 12, "bold"))
        self.lbl_ctx_value.pack(side="left", padx=5)
        
        self.slider_ctx = customtkinter.CTkSlider(ollama_ctx_row, from_=2048, to=131072, number_of_steps=126, width=400, command=self.on_ctx_slider_changed)
        self.slider_ctx.set(16384)
        self.slider_ctx.pack(side="left", padx=10)
        
        customtkinter.CTkButton(ollama_ctx_row, text="Set", width=60, command=self.save_current_profile).pack(side="left", padx=5)
        customtkinter.CTkButton(ollama_ctx_row, text="Revert to Default", width=120, fg_color="#606060", hover_color="#404040", command=self.revert_ctx_to_default).pack(side="left", padx=5)

        # CALBOT Section
        self.lf_calbot = customtkinter.CTkFrame(scroll_frame)
        self.lf_calbot.pack(fill="x", padx=10, pady=10)
        customtkinter.CTkLabel(self.lf_calbot, text="🤖 CALBOT (Discord Bot)", font=("Arial", 14, "bold")).pack(anchor="w", padx=15, pady=(10, 5))
        
        calbot_controls = customtkinter.CTkFrame(self.lf_calbot, fg_color="transparent")
        calbot_controls.pack(fill="x", padx=15, pady=(0, 10))
        
        self.lbl_calbot_status = customtkinter.CTkLabel(calbot_controls, text="Status: Stopped 🔴", font=("Arial", 12, "bold"), text_color="#ff4d4d")
        self.lbl_calbot_status.pack(side="left", padx=5)
        
        customtkinter.CTkButton(calbot_controls, text="▶ Start CALBOT", width=120, command=self.start_calbot).pack(side="left", padx=(20, 5))
        customtkinter.CTkButton(calbot_controls, text="⏹ Stop", width=80, fg_color="#606060", hover_color="#404040", command=self.stop_calbot).pack(side="left", padx=5)
        customtkinter.CTkButton(calbot_controls, text="🔄 Restart", width=100, command=self.restart_calbot).pack(side="left", padx=5)
        customtkinter.CTkButton(calbot_controls, text="📂 Reprocess Latest", width=140, fg_color="#1f538d", command=self.reprocess_latest_processed).pack(side="left", padx=20)

        # CSV Pipeline Section
        self.lf_csv = customtkinter.CTkFrame(scroll_frame)
        self.lf_csv.pack(fill="x", padx=10, pady=10)
        customtkinter.CTkLabel(self.lf_csv, text="📄 Extraction Engine", font=("Arial", 14, "bold")).pack(anchor="w", padx=15, pady=(10, 5))
        
        csv_controls = customtkinter.CTkFrame(self.lf_csv, fg_color="transparent")
        csv_controls.pack(fill="x", padx=15, pady=(0, 10))
        
        customtkinter.CTkLabel(csv_controls, text="Process pending contracts in /Incoming").pack(side="left", padx=5)
        customtkinter.CTkButton(csv_controls, text="⚡ Force-Run Extraction", width=180, command=self.run_csv_pipeline).pack(side="right", padx=10)
        
        # Dual Log View
        log_container = customtkinter.CTkFrame(scroll_frame, fg_color="transparent")
        log_container.pack(fill="both", expand=True, padx=10, pady=10)
        log_container.grid_columnconfigure(0, weight=1)
        log_container.grid_columnconfigure(1, weight=1)

        # Action Logs (Left)
        self.lf_logs_left = customtkinter.CTkFrame(log_container)
        self.lf_logs_left.grid(row=0, column=0, padx=(0, 5), sticky="nsew")
        header_left = customtkinter.CTkFrame(self.lf_logs_left, fg_color="transparent")
        header_left.pack(fill="x", padx=15, pady=(5, 0))
        customtkinter.CTkLabel(header_left, text="📝 Action Logs", font=("Arial", 12, "bold")).pack(side="left")
        customtkinter.CTkButton(header_left, text="Export Log", width=80, height=20, font=("Arial", 10), command=lambda: self.export_log(self.txt_logs, "Action")).pack(side="right")
        self.txt_logs = customtkinter.CTkTextbox(self.lf_logs_left, height=350, font=("Consolas", 11))
        self.txt_logs.pack(fill="both", expand=True, padx=10, pady=10)

        # Terminal Log (Right)
        self.lf_logs_right = customtkinter.CTkFrame(log_container)
        self.lf_logs_right.grid(row=0, column=1, padx=(5, 0), sticky="nsew")
        header_right = customtkinter.CTkFrame(self.lf_logs_right, fg_color="transparent")
        header_right.pack(fill="x", padx=15, pady=(5, 0))
        customtkinter.CTkLabel(header_right, text="💻 Terminal Log", font=("Arial", 12, "bold")).pack(side="left")
        customtkinter.CTkButton(header_right, text="Export Log", width=80, height=20, font=("Arial", 10), command=lambda: self.export_log(self.txt_terminal, "Terminal")).pack(side="right")
        self.txt_terminal = customtkinter.CTkTextbox(self.lf_logs_right, height=350, font=("Consolas", 11), fg_color="#1a1a1a", text_color="#d0d0d0")
        self.txt_terminal.pack(fill="both", expand=True, padx=10, pady=10)

        self.log_msg("GUI Initialized.")
        self.log_terminal("System Ready. Waiting for background tasks...\n")

    # ==========================================
    # TAB 2: MASTER CONFIG (With Profiles)
    # ==========================================
    def build_config_tab(self, tab):
        # Profile Selection Bar
        profile_frame = customtkinter.CTkFrame(tab)
        profile_frame.pack(fill="x", padx=10, pady=(10, 5))
        
        customtkinter.CTkLabel(profile_frame, text="Active Profile:", font=("Arial", 12, "bold")).pack(side="left", padx=15, pady=10)
        self.profile_dropdown = customtkinter.CTkComboBox(profile_frame, values=["Default"], command=self.on_profile_selected)
        self.profile_dropdown.pack(side="left", padx=5)
        
        customtkinter.CTkButton(profile_frame, text="New", width=60, command=self.create_new_profile).pack(side="left", padx=2)
        customtkinter.CTkButton(profile_frame, text="Duplicate", width=80, command=self.duplicate_profile).pack(side="left", padx=2)
        customtkinter.CTkButton(profile_frame, text="Delete", width=60, fg_color="#602020", hover_color="#401010", command=self.delete_profile).pack(side="left", padx=2)

        # Settings Container
        scrollable_frame = customtkinter.CTkScrollableFrame(tab, label_text="Profile Settings", label_font=("Arial", 14, "bold"))
        scrollable_frame.pack(fill="both", expand=True, padx=10, pady=10)
        scrollable_frame.grid_columnconfigure(1, weight=1)

        for i, key in enumerate(CONFIG_KEYS):
            customtkinter.CTkLabel(scrollable_frame, text=key + ":").grid(row=i, column=0, sticky="e", padx=10, pady=10)
            if key == "TIMEZONE":
                # US Timezones with NY at the top
                tz_options = [
                    "America/New_York", "America/Chicago", "America/Denver", 
                    "America/Los_Angeles", "America/Anchorage", "Pacific/Honolulu",
                    "UTC"
                ]
                widget = customtkinter.CTkComboBox(scrollable_frame, values=tz_options, width=400)
            else:
                widget = customtkinter.CTkEntry(scrollable_frame, width=400)
            
            widget.grid(row=i, column=1, sticky="ew", padx=10, pady=10)
            self.config_vars[key] = widget

        btn_frame = customtkinter.CTkFrame(scrollable_frame, fg_color="transparent")
        btn_frame.grid(row=len(CONFIG_KEYS), column=1, sticky="w", padx=10, pady=20)
        
        customtkinter.CTkButton(btn_frame, text="💾 Save to Profile", command=self.save_current_profile).pack(side="left", padx=5)
        customtkinter.CTkButton(btn_frame, text="🚀 Set as Master & Apply", width=200, fg_color="#1f538d", command=self.apply_profile_to_master).pack(side="left", padx=5)

    # ==========================================
    # TAB 3: GOOGLE SCRIPTS
    # ==========================================
    def build_gscripts_tab(self, tab):
        scroll_frame = customtkinter.CTkScrollableFrame(tab, fg_color="transparent")
        scroll_frame.pack(fill="both", expand=True)
        
        top_frame = customtkinter.CTkFrame(scroll_frame, fg_color="transparent")
        top_frame.pack(fill="x", padx=10, pady=10)
        customtkinter.CTkLabel(top_frame, text="Google Workspace Integrations", font=("Arial", 16, "bold")).pack(side="left")
        customtkinter.CTkButton(top_frame, text="🌐 Open Google Scripts Webpage", command=lambda: webbrowser.open("https://script.google.com/")).pack(side="right")

        # EMEX
        self.lf_emex = customtkinter.CTkFrame(scroll_frame)
        self.lf_emex.pack(fill="x", padx=10, pady=10)
        customtkinter.CTkLabel(self.lf_emex, text="AI-tinerary-EMEX.gs (Gmail to Drive)", font=("Arial", 14, "bold")).pack(anchor="w", padx=15, pady=(10, 5))
        emex_grid = customtkinter.CTkFrame(self.lf_emex, fg_color="transparent")
        emex_grid.pack(fill="x", padx=15, pady=(0, 10))
        emex_grid.grid_columnconfigure(1, weight=1)
        self.emex_keys = ["SOURCE_LABEL_NAME", "PROCESSED_LABEL_NAME", "INCOMING_DRIVE_FOLDER_ID", "COMPLETE_DRIVE_FOLDER_ID"]
        for i, key in enumerate(self.emex_keys):
            customtkinter.CTkLabel(emex_grid, text=key + ":").grid(row=i, column=0, sticky="e", padx=5, pady=3)
            entry = customtkinter.CTkEntry(emex_grid, width=400)
            entry.grid(row=i, column=1, sticky="ew", padx=5, pady=3)
            self.gs_emex_vars[key] = entry
        btn_frame_e = customtkinter.CTkFrame(self.lf_emex, fg_color="transparent")
        btn_frame_e.pack(fill="x", padx=15, pady=(0, 10))
        customtkinter.CTkButton(btn_frame_e, text="Save EMEX", width=120, command=lambda: self.save_gs_config(GS_EMEX_PATH, self.gs_emex_vars)).pack(side="left", padx=2)
        customtkinter.CTkButton(btn_frame_e, text="📋 Copy Full EMEX Code", width=200, fg_color="#606060", hover_color="#404040", command=lambda: self.copy_file_to_clipboard(GS_EMEX_PATH)).pack(side="left", padx=2)

        # SHSY
        self.lf_shsy = customtkinter.CTkFrame(scroll_frame)
        self.lf_shsy.pack(fill="x", padx=10, pady=10)
        customtkinter.CTkLabel(self.lf_shsy, text="AI-tinerary-SHSY.gs (Drive to Sheets)", font=("Arial", 14, "bold")).pack(anchor="w", padx=15, pady=(10, 5))
        shsy_grid = customtkinter.CTkFrame(self.lf_shsy, fg_color="transparent")
        shsy_grid.pack(fill="x", padx=15, pady=(0, 10))
        shsy_grid.grid_columnconfigure(1, weight=1)
        self.shsy_keys = ["SYNC_DRIVE_FOLDER_ID", "TARGET_SPREADSHEET_ID", "MASTER_CSV_NAME", "TARGET_SHEET_NAME"]
        for i, key in enumerate(self.shsy_keys):
            customtkinter.CTkLabel(shsy_grid, text=key + ":").grid(row=i, column=0, sticky="e", padx=5, pady=3)
            entry = customtkinter.CTkEntry(shsy_grid, width=400)
            entry.grid(row=i, column=1, sticky="ew", padx=5, pady=3)
            self.gs_shsy_vars[key] = entry
        btn_frame_s = customtkinter.CTkFrame(self.lf_shsy, fg_color="transparent")
        btn_frame_s.pack(fill="x", padx=15, pady=(0, 10))
        customtkinter.CTkButton(btn_frame_s, text="Save SHSY", width=120, command=lambda: self.save_gs_config(GS_SHSY_PATH, self.gs_shsy_vars)).pack(side="left", padx=2)
        customtkinter.CTkButton(btn_frame_s, text="📋 Copy Full SHSY Code", width=200, fg_color="#606060", hover_color="#404040", command=lambda: self.copy_file_to_clipboard(GS_SHSY_PATH)).pack(side="left", padx=2)

    # ==========================================
    # TAB 4: ENVIRONMENT
    # ==========================================
    def build_env_tab(self, tab):
        scroll_frame = customtkinter.CTkScrollableFrame(tab, fg_color="transparent")
        scroll_frame.pack(fill="both", expand=True)
        customtkinter.CTkLabel(scroll_frame, text="Virtual Environment & Dependencies", font=("Arial", 16, "bold")).pack(anchor="w", padx=20, pady=(20, 10))
        btn_frame = customtkinter.CTkFrame(scroll_frame, fg_color="transparent")
        btn_frame.pack(fill="x", padx=20, pady=5)
        customtkinter.CTkButton(btn_frame, text="🔍 Check Health", width=150, command=self.check_env_health).pack(side="left", padx=5)
        customtkinter.CTkButton(btn_frame, text="⚙️ Run Setup Script", width=150, fg_color="#606060", hover_color="#404040", command=self.run_setup_script).pack(side="left", padx=5)
        self.txt_env_logs = customtkinter.CTkTextbox(scroll_frame, height=450, font=("Consolas", 12), fg_color="#1a1a1a", text_color="#00ff00")
        self.txt_env_logs.pack(fill="both", expand=True, padx=20, pady=20)
        self.log_env("Environment manager ready.")

    # ==========================================
    # LOGGING
    # ==========================================
    def log_msg(self, msg):
        def _log():
            time_str = time.strftime("%H:%M:%S")
            self.txt_logs.insert("end", f"[{time_str}] {msg}\n")
            self.txt_logs.see("end")
        self.after(0, _log)

    def log_terminal(self, msg):
        def _log():
            self.txt_terminal.insert("end", msg)
            self.txt_terminal.see("end")
        self.after(0, _log)

    def log_env(self, msg):
        def _log():
            self.txt_env_logs.insert("end", f"{msg}\n")
            self.txt_env_logs.see("end")
        self.after(0, _log)

    def create_stat_widget(self, parent, title, value, col):
        frame = customtkinter.CTkFrame(parent)
        frame.grid(row=0, column=col, padx=5, sticky="nsew")
        customtkinter.CTkLabel(frame, text=title, font=("Arial", 11)).pack(pady=(5, 0))
        val_lbl = customtkinter.CTkLabel(frame, text=value, font=("Arial", 16, "bold"), text_color="#1f538d")
        val_lbl.pack(pady=(0, 5))
        return val_lbl

    # ==========================================
    # TAB: FILES & LINKS
    # ==========================================
    def build_files_tab(self, tab):
        from constants import (
            CONTRACTS_DIR, BITS_DIR, PROCESSED_DIR, ITINERARIES_DIR, LOGS_DIR
        )
        scroll_frame = customtkinter.CTkScrollableFrame(tab, fg_color="transparent")
        scroll_frame.pack(fill="both", expand=True)

        # Local Folders
        lf_folders = customtkinter.CTkFrame(scroll_frame)
        lf_folders.pack(fill="x", padx=10, pady=10)
        customtkinter.CTkLabel(lf_folders, text="📂 Local Project Directories", font=("Arial", 14, "bold")).pack(anchor="w", padx=15, pady=10)
        
        f_btns = customtkinter.CTkFrame(lf_folders, fg_color="transparent")
        f_btns.pack(fill="x", padx=15, pady=(0, 15))
        
        dirs = [
            ("📥 Incoming", CONTRACTS_DIR),
            ("⏳ Bits", BITS_DIR),
            ("✅ Processed", PROCESSED_DIR),
            ("📝 Itineraries", ITINERARIES_DIR),
            ("📊 Logs", LOGS_DIR)
        ]
        
        for i, (name, path) in enumerate(dirs):
            customtkinter.CTkButton(f_btns, text=name, width=140, command=lambda p=path: self.open_path(p)).grid(row=i//3, column=i%3, padx=5, pady=5)

        # Master Files
        lf_files = customtkinter.CTkFrame(scroll_frame)
        lf_files.pack(fill="x", padx=10, pady=10)
        customtkinter.CTkLabel(lf_files, text="📊 Master Data", font=("Arial", 14, "bold")).pack(anchor="w", padx=15, pady=10)
        
        f_btns_m = customtkinter.CTkFrame(lf_files, fg_color="transparent")
        f_btns_m.pack(fill="x", padx=15, pady=(0, 15))
        
        customtkinter.CTkButton(f_btns_m, text="📈 Open Master CSV", width=200, fg_color="#1f538d", command=self.open_master_csv).pack(side="left", padx=5)
        customtkinter.CTkButton(f_btns_m, text="📝 Open Master Config.txt", width=200, command=lambda: self.open_path(MASTER_CONFIG_PATH)).pack(side="left", padx=5)

        # External Links
        lf_links = customtkinter.CTkFrame(scroll_frame)
        lf_links.pack(fill="x", padx=10, pady=10)
        customtkinter.CTkLabel(lf_links, text="🌐 External Links", font=("Arial", 14, "bold")).pack(anchor="w", padx=15, pady=10)
        
        l_btns = customtkinter.CTkFrame(lf_links, fg_color="transparent")
        l_btns.pack(fill="x", padx=15, pady=(0, 15))
        
        links = [
            ("📅 Google Calendar", "https://calendar.google.com/"),
            ("📑 Google Sheets", "https://docs.google.com/spreadsheets/"),
            ("🗺️ OpenRouteService", "https://openrouteservice.org/"),
            ("🤖 Ollama Documentation", "https://ollama.com/library")
        ]
        
        for i, (name, url) in enumerate(links):
            customtkinter.CTkButton(l_btns, text=name, width=180, fg_color="#2c3e50", command=lambda u=url: webbrowser.open(u)).grid(row=i//2, column=i%2, padx=5, pady=5)

    def open_path(self, path):
        if not path.exists():
            messagebox.showerror("Error", f"Path does not exist: {path}")
            return
        
        if sys.platform == "win32":
            os.startfile(path)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path)])

    def open_master_csv(self):
        from constants import MASTER_CSV
        if not MASTER_CSV.exists():
            messagebox.showwarning("Not Found", "Master CSV file has not been created yet.")
            return
        self.open_path(MASTER_CSV)

    def toggle_theme(self):
        if customtkinter.get_appearance_mode() == "Dark":
            customtkinter.set_appearance_mode("Light")
            self.theme_btn.configure(text="☀️")
        else:
            customtkinter.set_appearance_mode("Dark")
            self.theme_btn.configure(text="🌙")

    def toggle_wiki_panel(self):
        """Toggles a side panel acting as a right-hand column for Wiki info."""
        if not self.wiki_visible:
            # Show Panel
            self.grid_columnconfigure(1, weight=0, minsize=350)
            self.wiki_panel = customtkinter.CTkFrame(self, width=350)
            self.wiki_panel.grid(row=1, column=1, padx=(0, 20), pady=(10, 20), sticky="nsew")
            
            # Header for Side Panel
            lbl_frame = customtkinter.CTkFrame(self.wiki_panel, fg_color="transparent")
            lbl_frame.pack(fill="x", padx=10, pady=10)
            customtkinter.CTkLabel(lbl_frame, text="📖 Project Wiki", font=("Arial", 16, "bold")).pack(side="left")
            customtkinter.CTkButton(lbl_frame, text="✖", width=30, fg_color="transparent", hover_color="#602020", command=self.toggle_wiki_panel).pack(side="right")
            
            # Content
            self.txt_wiki = customtkinter.CTkTextbox(self.wiki_panel, font=("Arial", 12), wrap="word")
            self.txt_wiki.pack(fill="both", expand=True, padx=10, pady=(0, 10))
            
            wiki_content = """# AI-tinerary Guide

Welcome to the Project Wiki.

## Core Workflows
1. Incoming: Place PDFs/EMLs in Contracts/Incoming.
2. Dashboard: Run Extraction.
3. Bits: Use CALBOT (Discord) to review.
4. Finalize: Events are pushed to GCal and Master CSV.

## Prompt Placeholders
- {{keys}}: Field list
- {{field_instr}}: Instructions
- {{tour_summary}}: TinnyBot summary

## Useful Tips
- Set num_ctx higher for complex contracts.
- Use 'Rockwood' in filename to auto-crop to 3 pages.
"""
            self.txt_wiki.insert("1.0", wiki_content)
            self.txt_wiki.configure(state="disabled")
            
            # External Link Button
            customtkinter.CTkButton(self.wiki_panel, text="🌐 Open Full Wiki Online", 
                                   command=lambda: webbrowser.open("https://github.com/musixela/AI-tinerary/wiki")).pack(fill="x", padx=10, pady=10)
            
            self.wiki_visible = True
            # Expand window width if needed
            new_width = self.winfo_width() + 350
            self.geometry(f"{new_width}x{self.winfo_height()}")
        else:
            # Hide Panel
            if self.wiki_panel:
                self.wiki_panel.destroy()
                self.wiki_panel = None
            
            self.grid_columnconfigure(1, weight=0, minsize=0)
            self.wiki_visible = False
            # Restore window width
            new_width = max(1100, self.winfo_width() - 350)
            self.geometry(f"{new_width}x{self.winfo_height()}")

    def export_log(self, textbox, log_name):
        content = textbox.get("1.0", tk.END).strip()
        if not content: return
        timestamp = time.strftime("%Y%m%d-%H%M")
        filename = f"{log_name}-Log-{timestamp}.txt"
        filepath = Path.home() / "Desktop" / filename
        try:
            with open(filepath, "w", encoding="utf-8") as f: f.write(content)
            self.log_msg(f"✅ Exported {log_name} log to Desktop.")
            messagebox.showinfo("Export Successful", f"Saved: {filename}")
        except Exception as e: self.log_msg(f"❌ Export failed: {e}")

    # ==========================================
    # PROFILE MANAGEMENT
    # ==========================================
    def init_profiles(self):
        """Ensure default profile exists and populate dropdown."""
        if not (CONFIGS_DIR / "Default.env").exists() and MASTER_CONFIG_PATH.exists():
            shutil.copy(MASTER_CONFIG_PATH, CONFIGS_DIR / "Default.env")
        elif not (CONFIGS_DIR / "Default.env").exists():
            with open(CONFIGS_DIR / "Default.env", "w") as f:
                f.write("\n".join([f'{k}=""' for k in CONFIG_KEYS]))
        
        self.refresh_profile_list()
        self.load_profile("Default")

    def refresh_profile_list(self):
        profiles = [f.stem for f in CONFIGS_DIR.glob("*.env")]
        if not profiles: profiles = ["Default"]
        self.profile_dropdown.configure(values=profiles)
        if self.current_profile.get() not in profiles:
            self.current_profile.set("Default")
        self.profile_dropdown.set(self.current_profile.get())

    def on_profile_selected(self, profile_name):
        self.load_profile(profile_name)

    def load_profile(self, profile_name):
        path = CONFIGS_DIR / f"{profile_name}.env"
        if not path.exists(): return
        
        self.current_profile.set(profile_name)
        try:
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line: continue
                    k, v = line.split("=", 1)
                    k = k.strip()
                    v = v.strip().strip('"').strip("'")
                    if k in self.config_vars:
                        widget = self.config_vars[k]
                        if isinstance(widget, customtkinter.CTkComboBox):
                            widget.set(v)
                        else:
                            widget.delete(0, tk.END)
                            widget.insert(0, v)
            
            # Synchronize Dashboard Model Combo
            model_val = self.config_vars["OLLAMA_MODEL"].get()
            if model_val:
                self.cbo_models.set(model_val)
            
            # Synchronize Context Slider
            ctx_val = self.config_vars["OLLAMA_NUM_CTX"].get()
            if ctx_val and ctx_val.isdigit():
                val = int(ctx_val)
                self.slider_ctx.set(val)
                self.lbl_ctx_value.configure(text=f"{val:,}")
            else:
                self.slider_ctx.set(16384)
                self.lbl_ctx_value.configure(text="16,384")
                
            self.log_msg(f"📂 Profile '{profile_name}' loaded.")
        except Exception as e: self.log_msg(f"❌ Error loading profile {profile_name}: {e}")

    def save_current_profile(self):
        profile_name = self.current_profile.get()
        path = CONFIGS_DIR / f"{profile_name}.env"
        try:
            with open(path, "w", encoding="utf-8") as f:
                for k, var in self.config_vars.items():
                    val = var.get()
                    f.write(f'{k}="{val}"\n')
            self.log_msg(f"✅ Profile '{profile_name}' saved.")
            messagebox.showinfo("Success", f"Profile '{profile_name}' updated.")
        except Exception as e: self.log_msg(f"❌ Error saving profile: {e}")

    def create_new_profile(self):
        name = customtkinter.CTkInputDialog(text="Enter name for new profile:", title="New Profile").get_input()
        if name:
            name = re.sub(r'[\\/*?:"<>|]', "", name).strip()
            if not name: return
            path = CONFIGS_DIR / f"{name}.env"
            if path.exists():
                messagebox.showerror("Error", "Profile already exists.")
                return
            # Create empty template
            with open(path, "w") as f:
                f.write("\n".join([f'{k}=""' for k in CONFIG_KEYS]))
            self.refresh_profile_list()
            self.load_profile(name)
            self.log_msg(f"✨ Created new profile: {name}")

    def duplicate_profile(self):
        old_name = self.current_profile.get()
        new_name = customtkinter.CTkInputDialog(text=f"Copy of '{old_name}' name:", title="Duplicate Profile").get_input()
        if new_name:
            new_name = re.sub(r'[\\/*?:"<>|]', "", new_name).strip()
            if not new_name: return
            old_path = CONFIGS_DIR / f"{old_name}.env"
            new_path = CONFIGS_DIR / f"{new_name}.env"
            if new_path.exists():
                messagebox.showerror("Error", "Profile already exists.")
                return
            shutil.copy(old_path, new_path)
            self.refresh_profile_list()
            self.load_profile(new_name)
            self.log_msg(f"👥 Duplicated '{old_name}' to '{new_name}'")

    def delete_profile(self):
        name = self.current_profile.get()
        if name == "Default":
            messagebox.showwarning("Warning", "Cannot delete the Default profile.")
            return
        if messagebox.askyesno("Delete", f"Are you sure you want to delete profile '{name}'?"):
            path = CONFIGS_DIR / f"{name}.env"
            path.unlink()
            self.log_msg(f"🗑️ Deleted profile: {name}")
            self.load_profile("Default")
            self.refresh_profile_list()

    def apply_profile_to_master(self):
        """Save current profile and copy it to Master Config.txt."""
        self.save_current_profile()
        profile_name = self.current_profile.get()
        profile_path = CONFIGS_DIR / f"{profile_name}.env"
        try:
            shutil.copy(profile_path, MASTER_CONFIG_PATH)
            self.log_msg(f"🚀 Profile '{profile_name}' applied as Master Config.")
            messagebox.showinfo("Applied", f"Profile '{profile_name}' is now active.")
        except Exception as e: self.log_msg(f"❌ Failed to apply profile: {e}")

    # ==========================================
    # GOOGLE SCRIPTS
    # ==========================================
    def load_gs_config(self):
        def parse_gs(path, vars_dict):
            if not path.exists(): return
            try:
                with open(path, "r", encoding="utf-8") as f:
                    content = f.read()
                for key in vars_dict.keys():
                    match = re.search(rf"var\s+{key}\s*=\s*['\"](.*?)['\"];", content)
                    if match:
                        vars_dict[key].delete(0, tk.END)
                        vars_dict[key].insert(0, match.group(1))
            except Exception as e: self.log_msg(f"⚠️ Error parsing {path.name}: {e}")
        parse_gs(GS_EMEX_PATH, self.gs_emex_vars)
        parse_gs(GS_SHSY_PATH, self.gs_shsy_vars)

    def save_gs_config(self, path, vars_dict):
        if not path.exists(): return
        try:
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
            for key, entry in vars_dict.items():
                new_val = entry.get().replace("'", "\\'")
                content = re.sub(rf"(var\s+{key}\s*=\s*)['\"].*?['\"]", rf"\1'{new_val}'", content)
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
            self.log_msg(f"✅ {path.name} saved.")
        except Exception as e: self.log_msg(f"❌ Error saving {path.name}: {e}")

    def copy_file_to_clipboard(self, path):
        if not path.exists(): return
        try:
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
            self.clipboard_clear()
            self.clipboard_append(content)
            self.log_msg(f"📋 Copied {path.name} to clipboard.")
        except: pass

    # ==========================================
    # RUNTIME CONTROLS
    # ==========================================
    def get_python_exe(self):
        if os.name == 'nt': exe = ROOT_DIR / ".venv" / "Scripts" / "python.exe"
        else: exe = ROOT_DIR / ".venv" / "bin" / "python"
        return str(exe) if exe.exists() else sys.executable

    def start_calbot(self):
        if self.calbot_process and self.calbot_process.poll() is None: return
        py_exe = self.get_python_exe()
        script = str(ROOT_DIR / "AI-tinerary-CALBOT.py")
        try:
            self.calbot_process = subprocess.Popen([py_exe, script], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
            self.log_msg("▶️ Started CALBOT.")
            def read_output():
                proc = self.calbot_process
                if not proc: return
                for line in iter(proc.stdout.readline, ''): self.log_terminal(line)
                proc.stdout.close()
            threading.Thread(target=read_output, daemon=True).start()
        except Exception as e: self.log_msg(f"❌ Failed to start CALBOT: {e}")

    def stop_calbot(self):
        if self.calbot_process and self.calbot_process.poll() is None:
            self.calbot_process.terminate()
            self.calbot_process = None
            self.log_msg("⏹ Stopped CALBOT.")

    def restart_calbot(self):
        self.stop_calbot()
        time.sleep(1)
        self.start_calbot()

    def reprocess_latest_processed(self):
        """Move the most recent file from Processed back to Bits for re-notification."""
        processed_dir = ROOT_DIR / "Outputs" / "Bits" / "Processed"
        bits_dir = ROOT_DIR / "Outputs" / "Bits"
        state_file = ROOT_DIR / "Outputs" / "bot_state.json"
        
        if not processed_dir.exists():
            messagebox.showinfo("Reprocess", "Processed directory does not exist yet.")
            return
            
        files = list(processed_dir.glob("*.csv"))
        if not files:
            messagebox.showinfo("Reprocess", "No processed files found to reprocess.")
            return
            
        # Sort by modification time to get the latest
        latest_file = max(files, key=os.path.getmtime)
        
        if messagebox.askyesno("Reprocess", f"Move '{latest_file.name}' back to Bits for re-processing?"):
            try:
                # Move file
                shutil.move(str(latest_file), str(bits_dir / latest_file.name))
                
                # Remove from notified_files in bot_state.json if possible
                if state_file.exists():
                    try:
                        with open(state_file, "r") as f:
                            data = json.load(f)
                        
                        notified = data.get("notified_files", [])
                        if latest_file.name in notified:
                            notified.remove(latest_file.name)
                            with open(state_file, "w") as f:
                                json.dump({"notified_files": notified}, f)
                    except: pass
                
                self.log_msg(f"🔄 Moved '{latest_file.name}' back to Bits for reprocessing.")
                messagebox.showinfo("Success", f"'{latest_file.name}' is now ready for re-review.")
            except Exception as e:
                self.log_msg(f"❌ Reprocess failed: {e}")
                messagebox.showerror("Error", f"Failed to move file: {e}")

    def run_csv_pipeline(self):
        self.log_msg("⚡ Initiating CSV Extraction...")
        def run():
            py_exe = self.get_python_exe()
            script = str(ROOT_DIR / "AI-tinerary-CSV.py")
            try:
                process = subprocess.Popen([py_exe, script], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
                for line in iter(process.stdout.readline, ''): self.log_terminal(line)
                process.stdout.close()
                rc = process.wait()
                if rc == 0: self.log_msg("✅ CSV Extraction successful.")
                else: self.log_msg(f"❌ CSV Extraction failed (Code {rc}).")
            except Exception as e: self.log_msg(f"❌ Error: {e}")
        threading.Thread(target=run, daemon=True).start()

    # ==========================================
    # TAB: PROMPTS
    # ==========================================
    def build_prompts_tab(self, tab):
        self.prompts_dir = ROOT_DIR / "Prompts"
        self.defaults_dir = self.prompts_dir / "Defaults"
        self.prompts_dir.mkdir(exist_ok=True)
        self.defaults_dir.mkdir(exist_ok=True)

        # Controls Frame
        controls = customtkinter.CTkFrame(tab)
        controls.pack(fill="x", padx=10, pady=10)

        customtkinter.CTkLabel(controls, text="Select Prompt:", font=("Arial", 12, "bold")).pack(side="left", padx=15, pady=10)
        self.prompt_dropdown = customtkinter.CTkComboBox(controls, values=self.get_prompt_list(), command=self.on_prompt_selected, width=250)
        self.prompt_dropdown.pack(side="left", padx=5)

        customtkinter.CTkButton(controls, text="Refresh", width=80, command=self.refresh_prompts).pack(side="left", padx=5)
        customtkinter.CTkButton(controls, text="💾 Save Changes", width=120, fg_color="#1f538d", command=self.save_prompt_changes).pack(side="right", padx=10)
        customtkinter.CTkButton(controls, text="🔄 Revert to Default", width=140, fg_color="#606060", hover_color="#404040", command=self.revert_prompt_to_default).pack(side="right", padx=5)

        # Editor Frame
        editor_frame = customtkinter.CTkFrame(tab)
        editor_frame.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        
        self.txt_prompt_editor = customtkinter.CTkTextbox(editor_frame, font=("Consolas", 13), undo=True)
        self.txt_prompt_editor.pack(fill="both", expand=True, padx=10, pady=10)

        # Initial Load
        self.refresh_prompts()
        self.init_prompt_defaults()

    def get_prompt_list(self):
        if not self.prompts_dir.exists(): return []
        return [f.name for f in self.prompts_dir.glob("*.txt") if f.is_file()]

    def refresh_prompts(self):
        prompts = self.get_prompt_list()
        self.prompt_dropdown.configure(values=prompts)
        if prompts:
            if not self.prompt_dropdown.get() in prompts:
                self.prompt_dropdown.set(prompts[0])
            self.on_prompt_selected(self.prompt_dropdown.get())
        else:
            self.prompt_dropdown.set("")
            self.txt_prompt_editor.delete("1.0", tk.END)

    def on_prompt_selected(self, filename):
        if not filename: return
        path = self.prompts_dir / filename
        if path.exists():
            content = path.read_text(encoding="utf-8")
            self.txt_prompt_editor.delete("1.0", tk.END)
            self.txt_prompt_editor.insert("1.0", content)
            self.log_msg(f"🎭 Loaded prompt: {filename}")

    def save_prompt_changes(self):
        filename = self.prompt_dropdown.get()
        if not filename: return
        content = self.txt_prompt_editor.get("1.0", tk.END).strip()
        path = self.prompts_dir / filename
        try:
            path.write_text(content, encoding="utf-8")
            self.log_msg(f"✅ Saved changes to {filename}")
            messagebox.showinfo("Success", f"Prompt '{filename}' updated successfully.")
        except Exception as e:
            self.log_msg(f"❌ Failed to save prompt: {e}")
            messagebox.showerror("Error", f"Failed to save: {e}")

    def init_prompt_defaults(self):
        """Seed Defaults folder with current prompt versions if they don't exist."""
        for p in self.prompts_dir.glob("*.txt"):
            d_path = self.defaults_dir / p.name
            if not d_path.exists():
                shutil.copy2(p, d_path)
                self.log_msg(f"📦 Created default backup for {p.name}")

    def revert_prompt_to_default(self):
        filename = self.prompt_dropdown.get()
        if not filename: return
        d_path = self.defaults_dir / filename
        if not d_path.exists():
            messagebox.showwarning("Warning", f"No default backup found for '{filename}'.")
            return
        
        if messagebox.askyesno("Confirm Revert", f"Are you sure you want to revert '{filename}' to its original default state? All unsaved changes will be lost."):
            try:
                content = d_path.read_text(encoding="utf-8")
                self.txt_prompt_editor.delete("1.0", tk.END)
                self.txt_prompt_editor.insert("1.0", content)
                # Automatically save the reverted content
                path = self.prompts_dir / filename
                path.write_text(content, encoding="utf-8")
                self.log_msg(f"🔄 Reverted {filename} to default.")
                messagebox.showinfo("Success", f"'{filename}' has been restored to its default state.")
            except Exception as e:
                self.log_msg(f"❌ Revert failed: {e}")
                messagebox.showerror("Error", f"Failed to revert: {e}")

    # ==========================================
    # OLLAMA
    # ==========================================
    def start_ollama(self):
        if self.ollama_status == "Online 🟢":
            self.log_msg("🧠 Ollama is already running.")
            return

        def run():
            try:
                self.log_msg("🧠 Starting Ollama server...")
                self.ollama_process = subprocess.Popen(["ollama", "serve"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                time.sleep(3) # Wait for server to boot
                self.start_fetch_ollama_models()
            except Exception as e:
                self.log_msg(f"❌ Failed to start Ollama: {e}")
        
        threading.Thread(target=run, daemon=True).start()

    def stop_ollama(self):
        self.log_msg("🧠 Stopping Ollama...")
        try:
            if self.ollama_process:
                self.ollama_process.terminate()
                self.ollama_process = None
            
            # More aggressive kill for both Mac/Linux and Windows
            if os.name == 'nt':
                subprocess.run(["taskkill", "/f", "/im", "ollama.exe"], capture_output=True)
            else:
                subprocess.run(["pkill", "ollama"], capture_output=True)
                
            self.log_msg("⏹ Ollama stopped.")
        except Exception as e:
            self.log_msg(f"❌ Error stopping Ollama: {e}")

    def restart_ollama(self):
        self.stop_ollama()
        self.after(2000, self.start_ollama)

    def start_fetch_ollama_models(self):
        threading.Thread(target=self.fetch_ollama_models, daemon=True).start()

    def fetch_ollama_models(self):
        if not HAS_REQUESTS: return
        url = self.config_vars.get("OLLAMA_URL").get()
        if not url: return
        base_url = url.split("/api")[0] 
        try:
            r = requests.get(f"{base_url}/api/tags", timeout=3)
            if r.status_code == 200:
                models = r.json().get("models", [])
                model_names = [m["name"] for m in models]
                def _update():
                    self.cbo_models.configure(values=model_names)
                    if model_names and not self.cbo_models.get(): self.cbo_models.set(model_names[0])
                    self.log_msg(f"🧠 Fetched {len(model_names)} Ollama models.")
                self.after(0, _update)
        except: pass

    def on_model_changed_ctk(self, selected):
        if selected:
            self.config_vars["OLLAMA_MODEL"].delete(0, tk.END)
            self.config_vars["OLLAMA_MODEL"].insert(0, selected)

    def on_ctx_slider_changed(self, value):
        val = int(value)
        self.lbl_ctx_value.configure(text=f"{val:,}")
        self.config_vars["OLLAMA_NUM_CTX"].delete(0, tk.END)
        self.config_vars["OLLAMA_NUM_CTX"].insert(0, str(val))

    def revert_ctx_to_default(self):
        self.slider_ctx.set(16384)
        self.on_ctx_slider_changed(16384)
        self.log_msg("🔄 Context tokens reset to default (16,384).")

    def background_polling(self):
        from constants import CONTRACTS_DIR, BITS_DIR, PROCESSED_DIR
        while True:
            # 1. Update CALBOT Status
            if self.calbot_process and self.calbot_process.poll() is None:
                self.after(0, lambda: self.lbl_calbot_status.configure(text="Status: Running 🟢", text_color="#4dff4d"))
            else:
                self.after(0, lambda: self.lbl_calbot_status.configure(text="Status: Stopped 🔴", text_color="#ff4d4d"))
            
            # 2. Update Ollama Status
            if HAS_REQUESTS:
                url = self.config_vars.get("OLLAMA_URL").get()
                if url:
                    base_url = url.split("/api")[0]
                    try:
                        requests.get(base_url, timeout=2)
                        self.ollama_status = "Online 🟢"
                        self.after(0, lambda: self.lbl_ollama_status.configure(text="Status: " + self.ollama_status, text_color="#4dff4d"))
                    except:
                        self.ollama_status = "Offline 🔴"
                        self.after(0, lambda: self.lbl_ollama_status.configure(text="Status: " + self.ollama_status, text_color="#ff4d4d"))
            
            # 3. Update Quick Stats
            try:
                incoming_count = len(list(CONTRACTS_DIR.glob("*")))
                bits_count = len(list(BITS_DIR.glob("*.csv")))
                
                # Processed today
                today = datetime.datetime.now().date()
                processed_today = 0
                for f in PROCESSED_DIR.glob("*.csv"):
                    if datetime.datetime.fromtimestamp(f.stat().st_mtime).date() == today:
                        processed_today += 1
                
                self.after(0, lambda: self.lbl_stat_incoming.configure(text=str(incoming_count)))
                self.after(0, lambda: self.lbl_stat_bits.configure(text=str(bits_count)))
                self.after(0, lambda: self.lbl_stat_processed.configure(text=str(processed_today)))
            except:
                pass

            time.sleep(5)

    def check_env_health(self):
        self.txt_env_logs.delete("1.0", tk.END)
        self.log_env("Initiating Health Check...")
        dirs = ["Contracts/Incoming", "Contracts/Complete", "Outputs/Bits", "Outputs/Processed", "Logs"]
        for d in dirs:
            if (ROOT_DIR / d).exists(): self.log_env(f"[OK] Directory: {d}")
            else: self.log_env(f"[MISSING] Directory: {d}")
        venv_path = ROOT_DIR / ".venv"
        if venv_path.exists(): self.log_env("[OK] .venv found")
        else: self.log_env("[ERROR] .venv missing")
        self.log_env("\n✅ Health Check Complete.")

    def run_setup_script(self):
        self.log_env("\n🚀 Running Setup...")
        def run():
            script = str(ROOT_DIR / ("setup.bat" if os.name == 'nt' else "setup.sh"))
            cmd = ["cmd.exe", "/c", script] if os.name == 'nt' else ["bash", script]
            try:
                process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
                for line in process.stdout: self.log_env(line.strip())
                process.wait()
            except Exception as e: self.log_env(f"❌ Error: {e}")
        threading.Thread(target=run, daemon=True).start()


if __name__ == "__main__":
    app = AItineraryGUI()
    app.after(1000, app.start_fetch_ollama_models)
    app.mainloop()