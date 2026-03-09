#!/usr/bin/env python3
"""
AI-tinerary GUI Manager
A graphical interface for managing the AI-tinerary toolsuite.
"""

import os
import sys
import json
import re
import threading
import subprocess
import time
import webbrowser
from pathlib import Path
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext

# Optional: Import requests. If not available (e.g., outside venv), handle gracefully.
try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False


ROOT_DIR = Path(__file__).resolve().parent
MASTER_CONFIG_PATH = ROOT_DIR / "Master Config.txt"
GS_EMEX_PATH = ROOT_DIR / "google_scripts" / "AI-tinerary-EMEX.gs"
GS_SHSY_PATH = ROOT_DIR / "google_scripts" / "AI-tinerary-SHSY.gs"

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

class AItineraryGUI(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("🎸 AI-tinerary Manager")
        self.geometry("800x600")
        
        # Style configuration
        self.style = ttk.Style(self)
        self.style.theme_use('clam')
        
        # Runtime States
        self.calbot_process = None
        self.ollama_status = "Unknown"
        self.ollama_models = []
        
        self.config_vars = {}
        self.gs_emex_vars = {}
        self.gs_shsy_vars = {}

        self.setup_ui()
        self.load_master_config()
        self.load_gs_config()
        
        # Start background polling
        self.poll_thread = threading.Thread(target=self.background_polling, daemon=True)
        self.poll_thread.start()

    def setup_ui(self):
        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill="both", expand=True, padx=10, pady=10)
        
        # Tabs
        self.tab_dashboard = ttk.Frame(self.notebook)
        self.tab_config = ttk.Frame(self.notebook)
        self.tab_gscripts = ttk.Frame(self.notebook)
        self.tab_env = ttk.Frame(self.notebook)
        
        self.notebook.add(self.tab_dashboard, text="🚀 Dashboard")
        self.notebook.add(self.tab_config, text="⚙️ Master Config")
        self.notebook.add(self.tab_gscripts, text="☁️ Google Scripts")
        self.notebook.add(self.tab_env, text="🛠️ Environment")
        
        self.build_dashboard()
        self.build_config_tab()
        self.build_gscripts_tab()
        self.build_env_tab()

    # ==========================================
    # TAB 1: DASHBOARD
    # ==========================================
    def build_dashboard(self):
        frame = ttk.Frame(self.tab_dashboard, padding=20)
        frame.pack(fill="both", expand=True)

        # Ollama Section
        lf_ollama = ttk.LabelFrame(frame, text=" 🧠 Ollama Local AI ", padding=15)
        lf_ollama.pack(fill="x", pady=10)
        
        self.lbl_ollama_status = ttk.Label(lf_ollama, text="Status: Checking...", font=("Arial", 10, "bold"))
        self.lbl_ollama_status.grid(row=0, column=0, sticky="w", padx=5)

        ttk.Label(lf_ollama, text="Active Model:").grid(row=0, column=1, padx=(20,5))
        self.cbo_models = ttk.Combobox(lf_ollama, state="readonly", width=25)
        self.cbo_models.grid(row=0, column=2, padx=5)
        self.cbo_models.bind("<<ComboboxSelected>>", self.on_model_changed)
        
        ttk.Button(lf_ollama, text="Refresh Models", command=self.start_fetch_ollama_models).grid(row=0, column=3, padx=10)

        # CALBOT Section
        lf_calbot = ttk.LabelFrame(frame, text=" 🤖 CALBOT (Discord Bot) ", padding=15)
        lf_calbot.pack(fill="x", pady=10)
        
        self.lbl_calbot_status = ttk.Label(lf_calbot, text="Status: Stopped 🔴", font=("Arial", 10, "bold"), foreground="red")
        self.lbl_calbot_status.grid(row=0, column=0, sticky="w", padx=5)
        
        ttk.Button(lf_calbot, text="▶ Start CALBOT", command=self.start_calbot).grid(row=0, column=1, padx=(20, 5))
        ttk.Button(lf_calbot, text="⏹ Stop", command=self.stop_calbot).grid(row=0, column=2, padx=5)
        ttk.Button(lf_calbot, text="🔄 Restart", command=self.restart_calbot).grid(row=0, column=3, padx=5)

        # CSV Pipeline Section
        lf_csv = ttk.LabelFrame(frame, text=" 📄 Extraction Engine ", padding=15)
        lf_csv.pack(fill="x", pady=10)
        
        ttk.Label(lf_csv, text="Process pending contracts in /Incoming").grid(row=0, column=0, sticky="w", padx=5)
        ttk.Button(lf_csv, text="⚡ Force-Run CSV Extraction", command=self.run_csv_pipeline).grid(row=0, column=1, padx=(20, 5))
        
        # Log Output (Dashboard)
        lf_logs = ttk.LabelFrame(frame, text=" Action Logs ", padding=5)
        lf_logs.pack(fill="both", expand=True, pady=10)
        
        self.txt_logs = scrolledtext.ScrolledText(lf_logs, height=8, state="disabled", font=("Consolas", 9))
        self.txt_logs.pack(fill="both", expand=True)
        self.log_msg("GUI Initialized.")

    # ==========================================
    # TAB 2: MASTER CONFIG
    # ==========================================
    def build_config_tab(self):
        canvas = tk.Canvas(self.tab_config)
        scrollbar = ttk.Scrollbar(self.tab_config, orient="vertical", command=canvas.yview)
        scrollable_frame = ttk.Frame(canvas)

        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )

        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side="left", fill="both", expand=True, padx=10, pady=10)
        scrollbar.pack(side="right", fill="y")

        ttk.Label(scrollable_frame, text="Master Configuration Variables", font=("Arial", 12, "bold")).grid(row=0, column=0, columnspan=2, pady=10, sticky="w")

        for i, key in enumerate(CONFIG_KEYS):
            ttk.Label(scrollable_frame, text=key + ":").grid(row=i+1, column=0, sticky="e", padx=5, pady=5)
            var = tk.StringVar()
            entry = ttk.Entry(scrollable_frame, textvariable=var, width=60)
            entry.grid(row=i+1, column=1, sticky="w", padx=5, pady=5)
            self.config_vars[key] = var

        ttk.Button(scrollable_frame, text="💾 Save Configuration", command=self.save_master_config).grid(row=len(CONFIG_KEYS)+1, column=1, sticky="w", pady=20)

    # ==========================================
    # TAB 3: GOOGLE SCRIPTS
    # ==========================================
    def build_gscripts_tab(self):
        frame = ttk.Frame(self.tab_gscripts, padding=10)
        frame.pack(fill="both", expand=True)
        
        # Top bar
        top_frame = ttk.Frame(frame)
        top_frame.pack(fill="x", pady=(0, 10))
        ttk.Label(top_frame, text="Google Workspace Integrations", font=("Arial", 12, "bold")).pack(side="left")
        ttk.Button(top_frame, text="🌐 Open Google Scripts Webpage", command=lambda: webbrowser.open("https://script.google.com/")).pack(side="right")

        # EMEX
        lf_emex = ttk.LabelFrame(frame, text=" AI-tinerary-EMEX.gs (Gmail to Drive) ", padding=10)
        lf_emex.pack(fill="x", pady=5)
        
        self.emex_keys = ["SOURCE_LABEL_NAME", "PROCESSED_LABEL_NAME", "INCOMING_DRIVE_FOLDER_ID", "COMPLETE_DRIVE_FOLDER_ID"]
        for i, key in enumerate(self.emex_keys):
            ttk.Label(lf_emex, text=key + ":").grid(row=i, column=0, sticky="e", padx=5, pady=3)
            var = tk.StringVar()
            ttk.Entry(lf_emex, textvariable=var, width=50).grid(row=i, column=1, sticky="w", padx=5, pady=3)
            self.gs_emex_vars[key] = var
            
        btn_frame_e = ttk.Frame(lf_emex)
        btn_frame_e.grid(row=len(self.emex_keys), column=1, sticky="w", pady=5)
        ttk.Button(btn_frame_e, text="Save EMEX", command=lambda: self.save_gs_config(GS_EMEX_PATH, self.gs_emex_vars)).pack(side="left", padx=2)
        ttk.Button(btn_frame_e, text="📋 Copy Full EMEX Code", command=lambda: self.copy_file_to_clipboard(GS_EMEX_PATH)).pack(side="left", padx=2)

        # SHSY
        lf_shsy = ttk.LabelFrame(frame, text=" AI-tinerary-SHSY.gs (Drive to Sheets) ", padding=10)
        lf_shsy.pack(fill="x", pady=10)
        
        self.shsy_keys = ["SYNC_DRIVE_FOLDER_ID", "TARGET_SPREADSHEET_ID", "MASTER_CSV_NAME", "TARGET_SHEET_NAME"]
        for i, key in enumerate(self.shsy_keys):
            ttk.Label(lf_shsy, text=key + ":").grid(row=i, column=0, sticky="e", padx=5, pady=3)
            var = tk.StringVar()
            ttk.Entry(lf_shsy, textvariable=var, width=50).grid(row=i, column=1, sticky="w", padx=5, pady=3)
            self.gs_shsy_vars[key] = var
            
        btn_frame_s = ttk.Frame(lf_shsy)
        btn_frame_s.grid(row=len(self.shsy_keys), column=1, sticky="w", pady=5)
        ttk.Button(btn_frame_s, text="Save SHSY", command=lambda: self.save_gs_config(GS_SHSY_PATH, self.gs_shsy_vars)).pack(side="left", padx=2)
        ttk.Button(btn_frame_s, text="📋 Copy Full SHSY Code", command=lambda: self.copy_file_to_clipboard(GS_SHSY_PATH)).pack(side="left", padx=2)

    # ==========================================
    # TAB 4: ENVIRONMENT
    # ==========================================
    def build_env_tab(self):
        frame = ttk.Frame(self.tab_env, padding=20)
        frame.pack(fill="both", expand=True)

        ttk.Label(frame, text="Virtual Environment & Dependencies", font=("Arial", 12, "bold")).pack(anchor="w", pady=(0, 10))

        btn_frame = ttk.Frame(frame)
        btn_frame.pack(fill="x", pady=5)

        ttk.Button(btn_frame, text="🔍 Check Health", command=self.check_env_health).pack(side="left", padx=5)
        ttk.Button(btn_frame, text="⚙️ Run Setup Script", command=self.run_setup_script).pack(side="left", padx=5)

        self.txt_env_logs = scrolledtext.ScrolledText(frame, height=15, state="disabled", font=("Consolas", 10), bg="#1e1e1e", fg="#00ff00")
        self.txt_env_logs.pack(fill="both", expand=True, pady=15)
        self.log_env("Environment manager ready. Click 'Check Health' to inspect directories and venv.")

    # ==========================================
    # CORE LOGIC: LOGGING (Thread-safe)
    # ==========================================
    def log_msg(self, msg):
        def _log():
            self.txt_logs.config(state="normal")
            time_str = time.strftime("%H:%M:%S")
            self.txt_logs.insert("end", f"[{time_str}] {msg}\n")
            self.txt_logs.see("end")
            self.txt_logs.config(state="disabled")
        self.after(0, _log)

    def log_env(self, msg):
        def _log():
            self.txt_env_logs.config(state="normal")
            self.txt_env_logs.insert("end", f"{msg}\n")
            self.txt_env_logs.see("end")
            self.txt_env_logs.config(state="disabled")
        self.after(0, _log)

    # ==========================================
    # CORE LOGIC: CONFIG MANAGEMENT
    # ==========================================
    def load_master_config(self):
        if not MASTER_CONFIG_PATH.exists():
            self.log_msg("⚠️ Master Config.txt not found. Defaults will be blank.")
            return

        try:
            with open(MASTER_CONFIG_PATH, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    if "=" in line:
                        k, v = line.split("=", 1)
                        k = k.strip()
                        v = v.strip().strip('"').strip("'")
                        if k in self.config_vars:
                            self.config_vars[k].set(v)

            # Set dropdown to loaded model
            model = self.config_vars.get("OLLAMA_MODEL").get()
            if model:
                self.cbo_models.set(model)
        except Exception as e:
            self.log_msg(f"❌ Error loading Master Config: {e}")

    def save_master_config(self):
        if not MASTER_CONFIG_PATH.exists():
            messagebox.showerror("Error", "Master Config.txt does not exist. Run Setup first.")
            return

        try:
            with open(MASTER_CONFIG_PATH, "r", encoding="utf-8") as f:
                lines = f.readlines()

            # Update lines preserving comments
            for i, line in enumerate(lines):
                stripped = line.strip()
                if stripped and not stripped.startswith("#") and "=" in stripped:
                    k = stripped.split("=")[0].strip()
                    if k in self.config_vars:
                        val = self.config_vars[k].get()
                        lines[i] = f'{k}="{val}"\n'
            
            # Append keys that might be missing
            existing_keys = [line.split("=")[0].strip() for line in lines if "=" in line and not line.strip().startswith("#")]
            for k in CONFIG_KEYS:
                if k not in existing_keys:
                    val = self.config_vars[k].get()
                    lines.append(f'{k}="{val}"\n')

            with open(MASTER_CONFIG_PATH, "w", encoding="utf-8") as f:
                f.writelines(lines)
            
            self.log_msg("✅ Master Config saved successfully.")
            messagebox.showinfo("Success", "Master Config.txt updated successfully.")
        except Exception as e:
            self.log_msg(f"❌ Error saving Master Config: {e}")
            messagebox.showerror("Error", f"Failed to save Master Config: {e}")

    def load_gs_config(self):
        # Helper to regex extract JS vars: var VAR_NAME = 'VALUE';
        def parse_gs(path, vars_dict):
            if not path.exists(): return
            try:
                with open(path, "r", encoding="utf-8") as f:
                    content = f.read()
                for key in vars_dict.keys():
                    match = re.search(rf"var\s+{key}\s*=\s*['\"](.*?)['\"];", content)
                    if match:
                        vars_dict[key].set(match.group(1))
            except Exception as e:
                self.log_msg(f"⚠️ Error parsing {path.name}: {e}")

        parse_gs(GS_EMEX_PATH, self.gs_emex_vars)
        parse_gs(GS_SHSY_PATH, self.gs_shsy_vars)

    def save_gs_config(self, path, vars_dict):
        if not path.exists():
            messagebox.showerror("Error", f"File not found: {path.name}")
            return
            
        try:
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
                
            for key, var in vars_dict.items():
                new_val = var.get().replace("'", "\\'") # escape single quotes
                content = re.sub(rf"(var\s+{key}\s*=\s*)['\"].*?['\"]", rf"\1'{new_val}'", content)
                
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
                
            self.log_msg(f"✅ Google Script {path.name} saved.")
            messagebox.showinfo("Success", f"{path.name} updated successfully.")
        except Exception as e:
            self.log_msg(f"❌ Error saving {path.name}: {e}")
            messagebox.showerror("Error", f"Failed to save {path.name}: {e}")

    def copy_file_to_clipboard(self, path):
        if not path.exists():
            messagebox.showerror("Error", f"File not found: {path.name}")
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
            self.clipboard_clear()
            self.clipboard_append(content)
            self.log_msg(f"📋 Copied {path.name} to clipboard.")
            messagebox.showinfo("Copied", f"Full code of {path.name} copied to clipboard!")
        except Exception as e:
            self.log_msg(f"❌ Error copying {path.name}: {e}")

    # ==========================================
    # RUNTIME CONTROLS
    # ==========================================
    def get_python_exe(self):
        """Find the virtual environment Python executable."""
        if os.name == 'nt':
            exe = ROOT_DIR / ".venv" / "Scripts" / "python.exe"
        else:
            exe = ROOT_DIR / ".venv" / "bin" / "python"
        
        return str(exe) if exe.exists() else sys.executable

    def start_calbot(self):
        if self.calbot_process and self.calbot_process.poll() is None:
            self.log_msg("⚠️ CALBOT is already running.")
            return

        py_exe = self.get_python_exe()
        script = str(ROOT_DIR / "AI-tinerary-CALBOT.py")
        
        try:
            # Run detached so GUI doesn't hang
            if os.name == 'nt':
                # CREATE_NEW_CONSOLE helps see logs separately on Windows
                self.calbot_process = subprocess.Popen([py_exe, script], creationflags=subprocess.CREATE_NEW_CONSOLE)
            else:
                self.calbot_process = subprocess.Popen([py_exe, script])
            self.log_msg("▶️ Started CALBOT.")
        except Exception as e:
            self.log_msg(f"❌ Failed to start CALBOT: {e}")

    def stop_calbot(self):
        if self.calbot_process and self.calbot_process.poll() is None:
            self.calbot_process.terminate()
            self.calbot_process = None
            self.log_msg("⏹ Stopped CALBOT.")
        else:
            self.log_msg("ℹ️ CALBOT is not running.")

    def restart_calbot(self):
        self.stop_calbot()
        time.sleep(1) # Wait for process to release file locks
        self.start_calbot()

    def run_csv_pipeline(self):
        self.log_msg("⚡ Initiating CSV Extraction (Background)...")
        def run():
            py_exe = self.get_python_exe()
            script = str(ROOT_DIR / "AI-tinerary-CSV.py")
            try:
                result = subprocess.run([py_exe, script], capture_output=True, text=True)
                if result.returncode == 0:
                    self.log_msg("✅ CSV Extraction completed successfully.")
                else:
                    self.log_msg(f"❌ CSV Extraction failed:\n{result.stderr}")
            except Exception as e:
                self.log_msg(f"❌ Error running CSV script: {e}")
        
        threading.Thread(target=run, daemon=True).start()

    # ==========================================
    # OLLAMA INTEGRATION (Thread-safe)
    # ==========================================
    def start_fetch_ollama_models(self):
        threading.Thread(target=self.fetch_ollama_models, daemon=True).start()

    def fetch_ollama_models(self):
        if not HAS_REQUESTS:
            self.log_msg("⚠️ Request library missing. Run Setup.")
            return

        url = self.config_vars.get("OLLAMA_URL").get()
        if not url: return
        
        # Base url without /api/generate
        base_url = url.split("/api")[0] 
        try:
            r = requests.get(f"{base_url}/api/tags", timeout=3)
            if r.status_code == 200:
                models = r.json().get("models", [])
                model_names = [m["name"] for m in models]
                
                def _update():
                    self.cbo_models['values'] = model_names
                    if model_names and not self.cbo_models.get():
                        self.cbo_models.set(model_names[0])
                    self.log_msg(f"🧠 Fetched {len(model_names)} Ollama models.")
                
                self.after(0, _update)
        except Exception as e:
            self.log_msg(f"⚠️ Could not fetch Ollama models: {e}")

    def on_model_changed(self, event):
        selected = self.cbo_models.get()
        if selected:
            self.config_vars["OLLAMA_MODEL"].set(selected)
            self.save_master_config()
            self.log_msg(f"🧠 Model switched to {selected} and config saved.")

    def background_polling(self):
        while True:
            # 1. Check CALBOT Status
            if self.calbot_process and self.calbot_process.poll() is None:
                self.after(0, lambda: self.lbl_calbot_status.config(text="Status: Running 🟢", foreground="green"))
            else:
                self.after(0, lambda: self.lbl_calbot_status.config(text="Status: Stopped 🔴", foreground="red"))

            # 2. Check Ollama Status
            if HAS_REQUESTS:
                url = self.config_vars.get("OLLAMA_URL").get()
                if url:
                    base_url = url.split("/api")[0]
                    try:
                        requests.get(base_url, timeout=2)
                        self.after(0, lambda: self.lbl_ollama_status.config(text="Status: Online 🟢", foreground="green"))
                    except:
                        self.after(0, lambda: self.lbl_ollama_status.config(text="Status: Offline 🔴", foreground="red"))
            
            time.sleep(5) # Poll every 5 seconds

    # ==========================================
    # ENVIRONMENT & HEALTH
    # ==========================================
    def check_env_health(self):
        self.txt_env_logs.config(state="normal")
        self.txt_env_logs.delete("1.0", tk.END)
        self.log_env("Initiating Health Check...")
        
        # 1. Directories
        dirs = [
            "Contracts/Incoming", "Contracts/Complete",
            "Outputs/Bits", "Outputs/Processed", "Outputs/Backups", "Outputs/Itineraries",
            "Logs"
        ]
        all_dirs_ok = True
        for d in dirs:
            if (ROOT_DIR / d).exists():
                self.log_env(f"[OK] Directory exists: {d}")
            else:
                self.log_env(f"[MISSING] Directory: {d}")
                all_dirs_ok = False

        # 2. Virtual Env
        venv_path = ROOT_DIR / ".venv"
        if venv_path.exists():
            self.log_env("[OK] Virtual environment folder exists (.venv)")
            py_exe = self.get_python_exe()
            if os.path.exists(py_exe):
                self.log_env(f"[OK] Python executable found: {py_exe}")
            else:
                self.log_env("[ERROR] Python executable NOT found in .venv")
        else:
            self.log_env("[ERROR] .venv folder is missing. Please run Setup.")
            
        # 3. Required Files
        req_files = ["AI-tinerary-CALBOT.py", "AI-tinerary-CSV.py", "Dependencies.txt", "Master Config.txt"]
        for f in req_files:
            if (ROOT_DIR / f).exists():
                self.log_env(f"[OK] File found: {f}")
            else:
                self.log_env(f"[ERROR] Missing required file: {f}")

        if all_dirs_ok:
            self.log_env("\n✅ Health Check Complete. Environment looks healthy.")
        else:
            self.log_env("\n⚠️ Health Check Complete. Some issues found. Consider running Setup.")

    def run_setup_script(self):
        self.log_env("\n🚀 Running Setup Script...")
        def run():
            if os.name == 'nt':
                script = str(ROOT_DIR / "setup.bat")
                cmd = ["cmd.exe", "/c", script]
            else:
                script = str(ROOT_DIR / "setup.sh")
                cmd = ["bash", script]

            if not os.path.exists(script):
                self.log_env(f"[ERROR] Setup script not found at: {script}")
                return

            try:
                # Pipe output to capture logs
                process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
                if process.stdout:
                    for line in process.stdout:
                        self.log_env(line.strip())
                process.wait()
                if process.returncode == 0:
                    self.log_env("✅ Setup script completed successfully.")
                else:
                    self.log_env(f"❌ Setup script failed with code {process.returncode}.")
            except Exception as e:
                self.log_env(f"❌ Error launching setup script: {e}")
                
        threading.Thread(target=run, daemon=True).start()


if __name__ == "__main__":
    app = AItineraryGUI()
    # Fetch models once GUI starts (in background)
    app.after(1000, app.start_fetch_ollama_models)
    app.mainloop()