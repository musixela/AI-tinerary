#!/usr/bin/env python3
"""
AI-tinerary GUI Manager (Modern Edition)
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
        self.grid_rowconfigure(0, weight=1)

        self.tabview = customtkinter.CTkTabview(self, width=1050, height=850)
        self.tabview.grid(row=0, column=0, padx=20, pady=20, sticky="nsew")
        
        self.tabview.add("🚀 Dashboard")
        self.tabview.add("⚙️ Master Config")
        self.tabview.add("☁️ Google Scripts")
        self.tabview.add("🛠️ Environment")
        
        self.build_dashboard(self.tabview.tab("🚀 Dashboard"))
        self.build_config_tab(self.tabview.tab("⚙️ Master Config"))
        self.build_gscripts_tab(self.tabview.tab("☁️ Google Scripts"))
        self.build_env_tab(self.tabview.tab("🛠️ Environment"))

    # ==========================================
    # TAB 1: DASHBOARD
    # ==========================================
    def build_dashboard(self, tab):
        scroll_frame = customtkinter.CTkScrollableFrame(tab, fg_color="transparent")
        scroll_frame.pack(fill="both", expand=True)
        scroll_frame.grid_columnconfigure(0, weight=1)
        
        # Ollama Section
        self.lf_ollama = customtkinter.CTkFrame(scroll_frame)
        self.lf_ollama.pack(fill="x", padx=10, pady=10)
        customtkinter.CTkLabel(self.lf_ollama, text="🧠 Ollama Local AI", font=("Arial", 14, "bold")).pack(anchor="w", padx=15, pady=(10, 5))
        
        ollama_controls = customtkinter.CTkFrame(self.lf_ollama, fg_color="transparent")
        ollama_controls.pack(fill="x", padx=15, pady=(0, 10))
        
        self.lbl_ollama_status = customtkinter.CTkLabel(ollama_controls, text="Status: Checking...", font=("Arial", 12, "bold"))
        self.lbl_ollama_status.pack(side="left", padx=5)

        customtkinter.CTkLabel(ollama_controls, text="Active Model:").pack(side="left", padx=(20, 5))
        self.cbo_models = customtkinter.CTkComboBox(ollama_controls, width=200, values=["Loading..."], command=self.on_model_changed_ctk)
        self.cbo_models.set("Loading...")
        self.cbo_models.pack(side="left", padx=5)
        
        customtkinter.CTkButton(ollama_controls, text="Refresh Models", width=120, command=self.start_fetch_ollama_models).pack(side="left", padx=10)

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
            entry = customtkinter.CTkEntry(scrollable_frame, width=400)
            entry.grid(row=i, column=1, sticky="ew", padx=10, pady=10)
            self.config_vars[key] = entry

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
                        self.config_vars[k].delete(0, tk.END)
                        self.config_vars[k].insert(0, v)
            
            # Synchronize Dashboard Model Combo
            model_val = self.config_vars["OLLAMA_MODEL"].get()
            if model_val:
                self.cbo_models.set(model_val)
                
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
                for line in iter(self.calbot_process.stdout.readline, ''): self.log_terminal(line)
                self.calbot_process.stdout.close()
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
    # OLLAMA
    # ==========================================
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

    def background_polling(self):
        while True:
            if self.calbot_process and self.calbot_process.poll() is None:
                self.after(0, lambda: self.lbl_calbot_status.configure(text="Status: Running 🟢", text_color="#4dff4d"))
            else:
                self.after(0, lambda: self.lbl_calbot_status.configure(text="Status: Stopped 🔴", text_color="#ff4d4d"))
            if HAS_REQUESTS:
                url = self.config_vars.get("OLLAMA_URL").get()
                if url:
                    base_url = url.split("/api")[0]
                    try:
                        requests.get(base_url, timeout=2)
                        self.after(0, lambda: self.lbl_ollama_status.configure(text="Status: Online 🟢", text_color="#4dff4d"))
                    except:
                        self.after(0, lambda: self.lbl_ollama_status.configure(text="Status: Offline 🔴", text_color="#ff4d4d"))
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