import base64
import csv
import ctypes
import json
import math
import os
import random
import re
import subprocess
import sys
import threading
import time
import tkinter as tk
import webbrowser
import zipfile
from ctypes import wintypes
from datetime import datetime
from pathlib import Path
from tkinter import colorchooser, filedialog, messagebox, ttk
from typing import Any, Callable, cast
from urllib import error as urlerror
from urllib import parse as urlparse
from urllib import request as urlrequest

vg: Any | None = None
vg_import_error: Exception | None = None
vg_import_attempted = False


def _import_vgamepad_safely() -> tuple[Any | None, Exception | None]:
    """Import vgamepad without blocking GUI startup on problematic WMI probes."""
    try:
        if os.name == "nt":
            import platform

            # Python 3.14 on some Windows installs can stall in platform.system()
            # due to WMI probing; vgamepad calls platform.system() during import.
            try:
                if getattr(platform, "_wmi", None) is not None:
                    setattr(platform, "_wmi", None)
            except Exception:
                pass

        import vgamepad as vg_module

        return vg_module, None
    except Exception as exc:
        return None, exc

try:
    import pystray
    from PIL import Image, ImageDraw

    tray_import_error: Exception | None = None
except Exception as exc:
    pystray = None
    Image = None
    ImageDraw = None
    tray_import_error = exc


BIOME_COLOR_MAP: dict[str, str] = {
    "NORMAL": "#D8DEE9",
    "WINDY": "#66D9D0",
    "SNOWY": "#C9E9FF",
    "RAINY": "#4B7BFF",
    "SAND STORM": "#CFA267",
    "HELL": "#E04F3F",
    "STARFALL": "#4D86FF",
    "HEAVEN": "#F3D67B",
    "CORRUPTION": "#8C60FF",
    "NULL": "#9CA3AF",
    "GLITCHED": "#42FF73",
    "DREAMSPACE": "#F4A5E2",
    "CYBERSPACE": "#4EA1FF",
    "PUMPKIN MOON": "#FF6F00",
    "GRAVEYARD": "#37474F",
    "BLOOD RAIN": "#B71C1C",
    "AURORA": "#26C6DA",
}

BIOME_ALIAS_MAP: dict[str, str] = {
    "normal": "NORMAL",
    "windy": "WINDY",
    "snowy": "SNOWY",
    "rainy": "RAINY",
    "sandstorm": "SAND STORM",
    "sandstorms": "SAND STORM",
    "hell": "HELL",
    "starfall": "STARFALL",
    "heaven": "HEAVEN",
    "corruption": "CORRUPTION",
    "null": "NULL",
    "glitched": "GLITCHED",
    "dreamspace": "DREAMSPACE",
    "cyberspace": "CYBERSPACE",
    "pumpkinmoon": "PUMPKIN MOON",
    "graveyard": "GRAVEYARD",
    "bloodrain": "BLOOD RAIN",
    "aurora": "AURORA",
}

APP_VERSION = "0.2.8"
APP_USER_AGENT = f"AFKScope/{APP_VERSION}"
THEME_COLOR_KEYS = ("bg", "panel", "field", "text", "muted", "accent", "tree_sel", "tree_selfg")
WM_HOTKEY = 0x0312
PM_REMOVE = 0x0001
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002


class AntiAfkApp:
    @staticmethod
    def _resource_path(relative_name: str) -> str:
        if hasattr(sys, "_MEIPASS"):
            base_path = getattr(sys, "_MEIPASS")
        else:
            base_path = os.path.dirname(os.path.abspath(__file__))
        return os.path.join(base_path, relative_name)

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("AFKScope - Sol's RNG Anti AFK")
        self.root.geometry("1220x940")
        self.root.minsize(1100, 820)
        self.root.resizable(True, True)
        try:
            self.root.iconbitmap(self._resource_path("AFKSCOPE ICON.ico"))
        except Exception:
            pass

        self.user32 = ctypes.windll.user32
        self.kernel32 = ctypes.windll.kernel32

        self.worker_thread: threading.Thread | None = None
        self.stop_event = threading.Event()
        self.metrics_lock = threading.Lock()
        self.header_logo_photo: tk.PhotoImage | None = None
        self.header_logo_label: tk.Label | None = None
        self.header_icon_photo: Any | None = None
        self.header_icon_badge: tk.Label | None = None
        self.header_title_label: tk.Label | None = None
        self.header_subtitle_label: tk.Label | None = None

        self.is_running = False
        self.gamepad: Any | None = None
        self.config_path = os.path.join(os.getcwd(), "afkscope_config.json")
        self.theme_config_path = os.path.join(os.getcwd(), "afkscope_themes.json")
        self.recovery_state_path = os.path.join(os.getcwd(), "afkscope_recovery_state.json")
        self.recovery_snapshot_path = os.path.join(os.getcwd(), "afkscope_recovery_snapshot.json")
        self.presets_dir = os.path.join(os.getcwd(), "presets")
        self.should_offer_setup_wizard = not os.path.exists(self.config_path)

        self.interval_var = tk.StringVar(value="5")
        self.status_var = tk.StringVar(value="Idle")
        self.stats_var = tk.StringVar(value="Runtime 00:00:00 | Cycles 0 | Jumps 0 | Errors 0")
        self.auto_realign_var = tk.BooleanVar(value=False)
        self.jump_mode_var = tk.StringVar(value="all")
        self.theme_name_var = tk.StringVar(value="Midnight")
        self.anti_idle_pattern_var = tk.StringVar(value="balanced")
        self.hotkeys_enabled_var = tk.BooleanVar(value=True)
        self.health_alert_enabled_var = tk.BooleanVar(value=True)
        self.health_alert_minutes_var = tk.StringVar(value="3")
        self.autosave_enabled_var = tk.BooleanVar(value=True)
        self.autosave_minutes_var = tk.StringVar(value="2")

        self.pause_enabled_var = tk.BooleanVar(value=False)
        self.pause_start_var = tk.StringVar(value="02:00")
        self.pause_end_var = tk.StringVar(value="06:00")

        self.webhook_enabled_var = tk.BooleanVar(value=False)
        self.webhook_url_var = tk.StringVar(value="")

        self.watchdog_enabled_var = tk.BooleanVar(value=True)
        self.watchdog_threshold_var = tk.StringVar(value="12")
        self.preset_name_var = tk.StringVar(value="default")
        self.biome_alerts_enabled_var = tk.BooleanVar(value=False)
        self.rare_biome_var = tk.StringVar(value="GLITCHED")
        self.biome_action_var = tk.StringVar(value="webhook")
        self.biome_action_preset_var = tk.StringVar(value="default")
        self.recovery_enabled_var = tk.BooleanVar(value=True)
        self.latest_release_url = "https://github.com/0bl1terate3/AFKScope/releases/latest"

        self.window_map: list[tuple[int, str, int, str]] = []
        self._process_name_cache: dict[int, str] = {}
        self.instance_enabled_by_hwnd: dict[int, bool] = {}
        self.loaded_enabled_by_pid: dict[int, bool] = {}
        self.instance_last_jump: dict[int, float] = {}
        self.enabled_by_username: dict[str, bool] = {}

        self.pid_username: dict[int, str] = {}
        self.pid_user_id: dict[int, int] = {}
        self.pid_avatar_photo: dict[int, tk.PhotoImage] = {}
        self.pid_identity_confidence: dict[int, str] = {}
        self.identity_lookup_inflight: set[int] = set()
        self.identity_last_attempt: dict[int, float] = {}

        self.layout_cache: dict[int, tuple[int, int, int, int, int]] = {}
        self.last_window_count = -1

        self.session_started_at: float | None = None
        self.session_cycles = 0
        self.session_jumps = 0
        self.session_errors = 0

        self.failed_cycles = 0
        self.round_robin_index = 0
        self.last_instance_health_alert: dict[int, float] = {}
        self.last_autosave_at = 0.0
        self.recovery_prompt_needed = self._detect_unclean_shutdown()
        self.quick_setup_window: tk.Toplevel | None = None

        self.tray_icon = None
        self.tray_enabled = False
        self.hotkey_actions: dict[int, tuple[str, Callable[[], None]]] = {}
        self.global_hotkeys_registered = False

        self.current_theme_name = "Midnight"
        self.theme_palettes: dict[str, dict[str, str]] = {
            "Midnight": {"bg": "#171a1f", "panel": "#1f2430", "field": "#232a36", "text": "#e7ecf3", "muted": "#aeb8c8", "accent": "#7cb0ff", "tree_sel": "#355a93", "tree_selfg": "#ffffff"},
            "Solarized Light": {"bg": "#fdf6e3", "panel": "#eee8d5", "field": "#fffdf7", "text": "#073642", "muted": "#586e75", "accent": "#268bd2", "tree_sel": "#268bd2", "tree_selfg": "#ffffff"},
            "Neon Circuit": {"bg": "#0c1117", "panel": "#121926", "field": "#151f31", "text": "#d9fff3", "muted": "#86a5a0", "accent": "#00e6b8", "tree_sel": "#008a72", "tree_selfg": "#ffffff"},
            "Rose Quartz": {"bg": "#fff0f6", "panel": "#ffe2ee", "field": "#fff8fb", "text": "#4d2a3a", "muted": "#8e6b7a", "accent": "#d9468f", "tree_sel": "#d9468f", "tree_selfg": "#ffffff"},
            "Forest Mist": {"bg": "#eef5ef", "panel": "#dfece2", "field": "#f8fcf8", "text": "#1f3a2a", "muted": "#587260", "accent": "#2f855a", "tree_sel": "#2f855a", "tree_selfg": "#ffffff"},
            "Crimson Night": {"bg": "#1a1114", "panel": "#27161c", "field": "#311c24", "text": "#ffe8ee", "muted": "#c7a9b3", "accent": "#ff4d6d", "tree_sel": "#9e2d44", "tree_selfg": "#ffffff"},
            "Ocean Deep": {"bg": "#0c1c2b", "panel": "#12283d", "field": "#16324c", "text": "#e4f3ff", "muted": "#8db0c9", "accent": "#2ea3ff", "tree_sel": "#1f6dad", "tree_selfg": "#ffffff"},
            "Amber Terminal": {"bg": "#16120a", "panel": "#241d10", "field": "#2d2414", "text": "#ffe8b8", "muted": "#b7a47d", "accent": "#ffb020", "tree_sel": "#9a6a00", "tree_selfg": "#ffffff"},
            "Lavender Haze": {"bg": "#f6f3ff", "panel": "#ece7ff", "field": "#fbfaff", "text": "#362b57", "muted": "#6e6390", "accent": "#7c5cff", "tree_sel": "#7c5cff", "tree_selfg": "#ffffff"},
            "Matrix": {"bg": "#0a100a", "panel": "#111a11", "field": "#142014", "text": "#b8ffb8", "muted": "#79a879", "accent": "#39ff14", "tree_sel": "#1f7d1f", "tree_selfg": "#ffffff"},
            "Arctic Ice": {"bg": "#edf6fb", "panel": "#deedf6", "field": "#f7fcff", "text": "#173247", "muted": "#5c7a8f", "accent": "#1999d6", "tree_sel": "#1999d6", "tree_selfg": "#ffffff"},
            "Obsidian Gold": {"bg": "#141414", "panel": "#1e1e1e", "field": "#252525", "text": "#f7f1df", "muted": "#b5aa89", "accent": "#d4a72c", "tree_sel": "#80641a", "tree_selfg": "#ffffff"},
        }
        self.default_theme_order = list(self.theme_palettes.keys())
        self.default_theme_names = set(self.default_theme_order)
        self.custom_theme_palettes: dict[str, dict[str, str]] = {}
        self.theme_maker_window: tk.Toplevel | None = None
        self.theme_maker_name_var: tk.StringVar | None = None
        self.theme_maker_color_vars: dict[str, tk.StringVar] = {}
        self.theme_maker_swatches: dict[str, tk.Label] = {}
        self.current_palette = dict(self.theme_palettes[self.current_theme_name])

        self.username_patterns = [
            re.compile(r'displayName["\s:]+([A-Za-z0-9_]{3,20})'),
            re.compile(r'"name"\s*:\s*"([A-Za-z0-9_]{3,20})"'),
            re.compile(r'Players\.([A-Za-z0-9_]{3,20})'),
            re.compile(r'user(?:name)?["\s:]+([A-Za-z0-9_]{3,20})', re.IGNORECASE),
        ]
        self.excluded_usernames = {
            "players",
            "roblox",
            "localscript",
            "workspace",
            "camera",
            "sound",
            "humanoid",
            "character",
            "startergui",
            "replicatedstorage",
        }

        self.current_biome_name = "Unknown"
        self.current_biome_source = "-"
        self.current_biome_seen_at: float | None = None
        self.biome_counts: dict[str, int] = {name: 0 for name in BIOME_COLOR_MAP}
        self.biome_display_var = tk.StringVar(value="Unknown")
        self.biome_meta_var = tk.StringVar(value="Source: -")
        self.biome_log_path: str | None = None
        self.biome_log_offset = 0
        self.biome_history: list[str] = []
        self.event_timeline: list[str] = []
        self.biome_alert_cooldown_seconds = 45
        self.last_biome_alert_at: dict[str, float] = {}

        self._bloxstrap_presence_pattern = re.compile(
            r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d+Z,.*\[FLog::Output\]\s+\[BloxstrapRPC\]\s+(?P<payload>\{.*\})$"
        )
        self._biome_line_patterns = [
            re.compile(
                r"(?:A|The)\s+([A-Za-z]+(?:\s+[A-Za-z]+)?)\s+(?:has\s+)?(?:appeared|spawned|started|begun)",
                re.IGNORECASE,
            ),
            re.compile(
                r"(?:The\s+)?([A-Za-z]+(?:\s+[A-Za-z]+)?)\s+(?:has\s+)?(?:ended|disappeared|stopped|faded)",
                re.IGNORECASE,
            ),
            re.compile(
                r"\[System\].*?(?:biome|weather)[:\s]+([A-Za-z]+(?:\s+[A-Za-z]+)?)",
                re.IGNORECASE,
            ),
            re.compile(
                r"(?:biome|weather)\s*(?:is\s+now|changed\s+to|:)\s*([A-Za-z]+(?:\s+[A-Za-z]+)?)",
                re.IGNORECASE,
            ),
            re.compile(
                r"\b(Sandstorm|Sand\s+Storm|Hell|Starfall|Heaven|Corruption|Null|Glitched|Dreamspace|Cyberspace|Windy|Snowy|Rainy|Pumpkin\s*Moon|Graveyard|Blood\s*Rain|Aurora)\b",
                re.IGNORECASE,
            ),
        ] 

        self._build_ui()
        self._load_custom_themes()
        self._apply_selected_theme()
        self._render_biome_badge()
        os.makedirs(self.presets_dir, exist_ok=True)
        self._refresh_preset_list()
        self.load_config(silent=True)
        self._write_recovery_state_marker()
        self._ensure_window_visible()
        self.root.after(50, self._finish_startup)

    def _ensure_window_visible(self) -> None:
        # Force the main window to appear in front if Windows restores it hidden/off-screen.
        try:
            self.root.update_idletasks()
            self.root.state("normal")
            self.root.deiconify()
            self.root.lift()
            self.root.attributes("-topmost", True)
            self.root.after(250, lambda: self.root.attributes("-topmost", False))
            self.root.focus_force()
        except Exception:
            pass

    def _finish_startup(self) -> None:
        # Defer startup work so the UI appears even if environment checks are slow.
        try:
            self.refresh_instance_list(manual=False)
            self.run_diagnostics_checks()
            self._set_global_hotkeys_enabled(self.hotkeys_enabled_var.get(), log_result=False)
            self._schedule_stats_update()
            self._schedule_instance_poll()
            self._schedule_recovery_autosave()
            if self.recovery_prompt_needed:
                self.log("Detected previous unclean shutdown state.")
                self.root.after(250, self._prompt_recovery_restore)
            if self.should_offer_setup_wizard:
                self.root.after(350, self.open_quick_setup_wizard)
        except Exception as exc:
            self.log(f"Startup checks failed: {exc}")

    def _build_ui(self) -> None:
        self.style = ttk.Style()
        try:
            self.style.theme_use("clam")
        except tk.TclError:
            pass
        self.style.configure(".", font=("Segoe UI", 9))
        self.style.configure("Treeview", rowheight=34)

        container = ttk.Frame(self.root, padding=10)
        container.pack(fill="both", expand=True)

        header = ttk.Frame(container)
        header.pack(fill="x", pady=(0, 8))
        header_theme = ttk.Frame(header)
        header_theme.pack(side=tk.RIGHT, anchor="ne")
        ttk.Label(header_theme, text="Theme").pack(side=tk.LEFT, padx=(0, 6))
        self.theme_combo = ttk.Combobox(
            header_theme,
            textvariable=self.theme_name_var,
            values=sorted(self.theme_palettes.keys()),
            width=18,
            state="readonly",
        )
        self.theme_combo.pack(side=tk.LEFT)
        self.theme_combo.bind("<<ComboboxSelected>>", self.on_theme_selected)
        ttk.Button(header_theme, text="Theme Maker", width=12, command=self.open_theme_maker).pack(side=tk.LEFT, padx=(6, 0))
        title_row = ttk.Frame(header)
        title_row.pack(anchor="center")
        try:
            logo_path = self._resource_path(os.path.join("assets", "afkscope-header-logo.png"))
            self.header_logo_photo = tk.PhotoImage(file=logo_path)
        except Exception:
            self.header_logo_photo = None

        if self.header_logo_photo is not None:
            self.header_logo_label = tk.Label(
                title_row,
                image=self.header_logo_photo,
                bd=0,
                highlightthickness=0,
            )
            self.header_logo_label.pack(side=tk.LEFT)
        else:
            try:
                from PIL import Image as PilImage
                from PIL import ImageTk

                icon_path = self._resource_path("AFKSCOPE ICON.ico")
                with PilImage.open(icon_path) as pil_icon:
                    pil_icon = pil_icon.convert("RGBA")
                    bbox = pil_icon.getbbox()
                    if bbox is not None:
                        pil_icon = pil_icon.crop(bbox)
                    resampling = getattr(PilImage, "Resampling", None)
                    if resampling is not None:
                        resample = cast(Any, resampling).LANCZOS
                    else:
                        resample = getattr(PilImage, "LANCZOS", 1)
                    pil_icon.thumbnail((40, 40), cast(Any, resample))
                    self.header_icon_photo = ImageTk.PhotoImage(pil_icon)
            except Exception:
                try:
                    icon = tk.PhotoImage(file=self._resource_path("AFKSCOPE ICON.png"))
                    if icon.width() > 40:
                        step = max(1, icon.width() // 40)
                        icon = cast(tk.PhotoImage, icon.subsample(step))
                    self.header_icon_photo = icon
                except Exception:
                    self.header_icon_photo = None
            if self.header_icon_photo is not None:
                self.header_icon_badge = tk.Label(
                    title_row,
                    image=self.header_icon_photo,
                    bg="#f5f8ff",
                    bd=1,
                    relief="solid",
                    padx=3,
                    pady=3,
                    highlightthickness=1,
                    highlightbackground="#7f8ea3",
                )
                self.header_icon_badge.pack(side=tk.LEFT, padx=(0, 8))
            self.header_title_label = tk.Label(
                title_row,
                text="AFKScope",
                font=("Segoe UI", 15, "bold"),
                padx=0,
                pady=0,
            )
            self.header_title_label.pack(side=tk.LEFT)
        self.header_subtitle_label = tk.Label(
            header,
            text="ViGEm focus spoofing macro with identity mapping, watchdog, and export tools",
            font=("Segoe UI", 9, "normal"),
        )
        self.header_subtitle_label.pack(anchor="center", pady=(2, 0))

        notebook = ttk.Notebook(container)
        notebook.pack(fill="both", expand=True)

        tab_control = ttk.Frame(notebook, padding=10)
        tab_instances = ttk.Frame(notebook, padding=10)
        tab_monitor = ttk.Frame(notebook, padding=10)
        tab_log = ttk.Frame(notebook, padding=10)
        notebook.add(tab_control, text="Controls")
        notebook.add(tab_instances, text="Instances")
        notebook.add(tab_monitor, text="Monitor")
        notebook.add(tab_log, text="Log")

        controls_group = ttk.LabelFrame(tab_control, text="Main Controls", padding=10)
        controls_group.pack(fill="x")

        row1 = ttk.Frame(controls_group)
        row1.pack(fill="x")
        ttk.Label(row1, text="Jump interval (seconds):").pack(side=tk.LEFT)
        ttk.Entry(row1, textvariable=self.interval_var, width=8, justify="center").pack(side=tk.LEFT, padx=(8, 14))
        ttk.Checkbutton(row1, text="Auto realign", variable=self.auto_realign_var).pack(side=tk.LEFT, padx=(0, 14))
        ttk.Label(row1, text="Jump mode:").pack(side=tk.LEFT)
        ttk.Radiobutton(row1, text="All-at-once", variable=self.jump_mode_var, value="all").pack(side=tk.LEFT, padx=(6, 4))
        ttk.Radiobutton(row1, text="Round-robin", variable=self.jump_mode_var, value="round").pack(side=tk.LEFT)

        row2 = ttk.Frame(controls_group)
        row2.pack(fill="x", pady=(8, 0))
        self.start_button = ttk.Button(row2, text="Start", width=11, command=self.start)
        self.start_button.pack(side=tk.LEFT, padx=(0, 5))
        self.stop_button = ttk.Button(row2, text="Stop", width=11, command=self.stop, state=tk.DISABLED)
        self.stop_button.pack(side=tk.LEFT, padx=(0, 5))
        self.test_button = ttk.Button(row2, text="Jump Now", width=11, command=self.test_jump)
        self.test_button.pack(side=tk.LEFT, padx=(0, 5))
        self.refresh_button = ttk.Button(row2, text="Refresh", width=11, command=lambda: self.refresh_instance_list(manual=True))
        self.refresh_button.pack(side=tk.LEFT, padx=(0, 5))
        self.align_button = ttk.Button(row2, text="Align", width=11, command=self.align_windows)
        self.align_button.pack(side=tk.LEFT, padx=(0, 5))
        self.restore_button = ttk.Button(row2, text="Restore", width=11, command=self.restore_windows)
        self.restore_button.pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(row2, text="Retry Identity", width=13, command=self.retry_selected_identity).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(row2, text="To Tray", width=11, command=self.minimize_to_tray).pack(side=tk.LEFT)

        row3 = ttk.Frame(controls_group)
        row3.pack(fill="x", pady=(8, 0))
        self.save_button = ttk.Button(row3, text="Save Config", width=12, command=self.save_config)
        self.save_button.pack(side=tk.LEFT, padx=(0, 5))
        self.load_button = ttk.Button(row3, text="Load Config", width=12, command=lambda: self.load_config(silent=False))
        self.load_button.pack(side=tk.LEFT, padx=(0, 10))
        ttk.Button(row3, text="Export JSON", width=12, command=lambda: self.export_instances("json")).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(row3, text="Export CSV", width=12, command=lambda: self.export_instances("csv")).pack(side=tk.LEFT, padx=(0, 10))
        ttk.Button(row3, text="Build EXE", width=12, command=self.build_exe).pack(side=tk.LEFT)

        preset_row = ttk.Frame(controls_group)
        preset_row.pack(fill="x", pady=(8, 0))
        ttk.Label(preset_row, text="Profile preset:").pack(side=tk.LEFT)
        self.preset_combo = ttk.Combobox(preset_row, textvariable=self.preset_name_var, width=24, state="normal")
        self.preset_combo.pack(side=tk.LEFT, padx=(8, 8))
        ttk.Button(preset_row, text="Save Preset", width=12, command=self.save_preset).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(preset_row, text="Load Preset", width=12, command=self.load_preset).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(preset_row, text="Delete Preset", width=12, command=self.delete_preset).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(preset_row, text="Refresh Presets", width=14, command=self._refresh_preset_list).pack(side=tk.LEFT)
        ttk.Button(preset_row, text="Open Presets", width=12, command=self.open_presets_folder).pack(side=tk.LEFT, padx=(5, 0))

        options_group = ttk.LabelFrame(tab_control, text="Automation Options", padding=10)
        options_group.pack(fill="x", pady=(8, 0))

        opt1 = ttk.Frame(options_group)
        opt1.pack(fill="x")
        ttk.Checkbutton(opt1, text="Safe pause schedule", variable=self.pause_enabled_var).pack(side=tk.LEFT)
        ttk.Label(opt1, text="Start HH:MM").pack(side=tk.LEFT, padx=(10, 4))
        ttk.Entry(opt1, textvariable=self.pause_start_var, width=6, justify="center").pack(side=tk.LEFT)
        ttk.Label(opt1, text="End HH:MM").pack(side=tk.LEFT, padx=(10, 4))
        ttk.Entry(opt1, textvariable=self.pause_end_var, width=6, justify="center").pack(side=tk.LEFT)

        opt2 = ttk.Frame(options_group)
        opt2.pack(fill="x", pady=(6, 0))
        ttk.Checkbutton(opt2, text="Discord webhook alerts", variable=self.webhook_enabled_var).pack(side=tk.LEFT)
        ttk.Entry(opt2, textvariable=self.webhook_url_var, width=70).pack(side=tk.LEFT, padx=(8, 0))

        opt3 = ttk.Frame(options_group)
        opt3.pack(fill="x", pady=(6, 0))
        ttk.Checkbutton(opt3, text="Watchdog reset if no successful jumps", variable=self.watchdog_enabled_var).pack(side=tk.LEFT)
        ttk.Label(opt3, text="Threshold cycles:").pack(side=tk.LEFT, padx=(10, 4))
        ttk.Entry(opt3, textvariable=self.watchdog_threshold_var, width=5, justify="center").pack(side=tk.LEFT)
        ttk.Checkbutton(opt3, text="Recovery sequence", variable=self.recovery_enabled_var).pack(side=tk.LEFT, padx=(12, 0))

        pattern_row = ttk.Frame(options_group)
        pattern_row.pack(fill="x", pady=(6, 0))
        ttk.Label(pattern_row, text="Anti-idle pattern:").pack(side=tk.LEFT)
        self.pattern_combo = ttk.Combobox(
            pattern_row,
            textvariable=self.anti_idle_pattern_var,
            values=["balanced", "subtle", "aggressive", "randomized"],
            width=12,
            state="readonly",
        )
        self.pattern_combo.pack(side=tk.LEFT, padx=(8, 0))

        hotkey_row = ttk.Frame(options_group)
        hotkey_row.pack(fill="x", pady=(6, 0))
        ttk.Checkbutton(
            hotkey_row,
            text="Global hotkeys (Ctrl+Alt+S/J/R/T)",
            variable=self.hotkeys_enabled_var,
            command=self.on_hotkeys_toggle,
        ).pack(side=tk.LEFT)

        health_row = ttk.Frame(options_group)
        health_row.pack(fill="x", pady=(6, 0))
        ttk.Checkbutton(health_row, text="Instance health alerts", variable=self.health_alert_enabled_var).pack(side=tk.LEFT)
        ttk.Label(health_row, text="No jump threshold (minutes):").pack(side=tk.LEFT, padx=(10, 4))
        ttk.Entry(health_row, textvariable=self.health_alert_minutes_var, width=5, justify="center").pack(side=tk.LEFT)
        ttk.Checkbutton(health_row, text="Auto-save recovery snapshot", variable=self.autosave_enabled_var).pack(
            side=tk.LEFT,
            padx=(12, 0),
        )
        ttk.Label(health_row, text="Every (minutes):").pack(side=tk.LEFT, padx=(8, 4))
        ttk.Entry(health_row, textvariable=self.autosave_minutes_var, width=5, justify="center").pack(side=tk.LEFT)

        biome_row = ttk.Frame(options_group)
        biome_row.pack(fill="x", pady=(8, 0))
        ttk.Label(biome_row, text="Current biome:").pack(side=tk.LEFT)
        self.biome_badge = tk.Label(
            biome_row,
            textvariable=self.biome_display_var,
            font=("Segoe UI", 9, "bold"),
            padx=8,
            pady=2,
            relief="solid",
            borderwidth=1,
        )
        self.biome_badge.pack(side=tk.LEFT, padx=(8, 8))
        ttk.Label(biome_row, textvariable=self.biome_meta_var).pack(side=tk.LEFT)

        alert_row = ttk.Frame(options_group)
        alert_row.pack(fill="x", pady=(6, 0))
        ttk.Checkbutton(alert_row, text="Rare biome webhook alerts", variable=self.biome_alerts_enabled_var).pack(side=tk.LEFT)
        ttk.Label(alert_row, text="Tracked rare biome:").pack(side=tk.LEFT, padx=(10, 4))
        self.rare_biome_combo = ttk.Combobox(
            alert_row,
            textvariable=self.rare_biome_var,
            values=["GLITCHED", "NULL", "DREAMSPACE", "CORRUPTION", "STARFALL", "HEAVEN", "AURORA", "BLOOD RAIN"],
            width=14,
            state="readonly",
        )
        self.rare_biome_combo.pack(side=tk.LEFT)

        action_row = ttk.Frame(options_group)
        action_row.pack(fill="x", pady=(6, 0))
        ttk.Label(action_row, text="Rare biome action:").pack(side=tk.LEFT)
        self.biome_action_combo = ttk.Combobox(
            action_row,
            textvariable=self.biome_action_var,
            values=["webhook", "pause_5m", "load_preset"],
            width=12,
            state="readonly",
        )
        self.biome_action_combo.pack(side=tk.LEFT, padx=(8, 8))
        ttk.Label(action_row, text="Preset").pack(side=tk.LEFT)
        ttk.Entry(action_row, textvariable=self.biome_action_preset_var, width=16).pack(side=tk.LEFT, padx=(6, 0))

        history_group = ttk.LabelFrame(tab_monitor, text="Biome Alert History", padding=8)
        history_group.pack(fill="x", pady=(8, 0))
        self.biome_history_list = tk.Listbox(history_group, height=4)
        self.biome_history_list.pack(fill="x")

        timeline_group = ttk.LabelFrame(tab_monitor, text="Event Timeline", padding=8)
        timeline_group.pack(fill="x", pady=(8, 0))
        self.event_history_list = tk.Listbox(timeline_group, height=5)
        self.event_history_list.pack(fill="x")

        target_group = ttk.LabelFrame(tab_instances, text="Per Instance Controls", padding=10)
        target_group.pack(fill="both", expand=True, pady=(8, 0))

        target_top = ttk.Frame(target_group)
        target_top.pack(fill="x")
        ttk.Label(target_top, text="Double-click Enabled column to toggle per instance.").pack(side=tk.LEFT)
        ttk.Button(target_top, text="Enable All", command=self.enable_all_instances).pack(side=tk.RIGHT, padx=(6, 0))
        ttk.Button(target_top, text="Disable All", command=self.disable_all_instances).pack(side=tk.RIGHT)

        tree_frame = ttk.Frame(target_group)
        tree_frame.pack(fill="both", expand=True, pady=(8, 0))

        columns = ("enabled", "pid", "hwnd", "process", "username", "confidence", "last_jump", "title")
        self.instance_tree = ttk.Treeview(tree_frame, columns=columns, show="tree headings", height=8)
        self.instance_tree.heading("#0", text="Avatar")
        self.instance_tree.heading("enabled", text="Enabled")
        self.instance_tree.heading("pid", text="PID")
        self.instance_tree.heading("hwnd", text="HWND")
        self.instance_tree.heading("process", text="Process")
        self.instance_tree.heading("username", text="Username")
        self.instance_tree.heading("confidence", text="Identity")
        self.instance_tree.heading("last_jump", text="Last Jump")
        self.instance_tree.heading("title", text="Window Title")
        self.instance_tree.column("#0", width=56, anchor="center", stretch=False)
        self.instance_tree.column("enabled", width=70, anchor="center")
        self.instance_tree.column("pid", width=70, anchor="center")
        self.instance_tree.column("hwnd", width=95, anchor="center")
        self.instance_tree.column("process", width=150, anchor="w")
        self.instance_tree.column("username", width=130, anchor="w")
        self.instance_tree.column("confidence", width=95, anchor="center")
        self.instance_tree.column("last_jump", width=90, anchor="center")
        self.instance_tree.column("title", width=330, anchor="w")
        self.instance_tree.pack(side=tk.LEFT, fill="both", expand=True)
        self.instance_tree.bind("<Double-1>", self.on_tree_double_click)

        tree_scroll = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=self.instance_tree.yview)
        tree_scroll.pack(side=tk.RIGHT, fill="y")
        self.instance_tree.configure(yscrollcommand=tree_scroll.set)

        status_frame = ttk.LabelFrame(tab_monitor, text="Session Stats", padding=10)
        status_frame.pack(fill="x", pady=(8, 0))
        ttk.Label(status_frame, textvariable=self.stats_var).pack(anchor="w")

        health_group = ttk.LabelFrame(tab_monitor, text="Instance Health Panel", padding=10)
        health_group.pack(fill="x", pady=(8, 0))
        self.health_text = tk.Text(health_group, height=4, font=("Consolas", 9), state=tk.DISABLED)
        self.health_text.pack(fill="x")

        diag_group = ttk.LabelFrame(tab_monitor, text="Diagnostics", padding=10)
        diag_group.pack(fill="x", pady=(8, 0))
        diag_row = ttk.Frame(diag_group)
        diag_row.pack(fill="x", pady=(0, 6))
        ttk.Button(diag_row, text="Run Checks", width=12, command=self.run_diagnostics_checks).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(diag_row, text="Export Debug Bundle", width=18, command=self.export_debug_bundle).pack(side=tk.LEFT)
        ttk.Button(diag_row, text="Check Updates", width=13, command=self.check_for_updates).pack(side=tk.LEFT, padx=(5, 5))
        ttk.Button(diag_row, text="Open Release", width=12, command=self.open_latest_release_page).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(diag_row, text="Copy Diag", width=10, command=self.copy_diagnostics_to_clipboard).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(diag_row, text="Copy Support", width=12, command=self.copy_support_bundle_to_clipboard).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(diag_row, text="Export Portable", width=14, command=self.export_portable_bundle).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(diag_row, text="Import Portable", width=14, command=self.import_portable_bundle).pack(side=tk.LEFT)
        self.diagnostics_text = tk.Text(diag_group, height=5, font=("Consolas", 9), state=tk.DISABLED)
        self.diagnostics_text.pack(fill="x")

        status_row = ttk.Frame(tab_log)
        status_row.pack(fill="x", pady=(8, 4))
        ttk.Label(status_row, text="Status:").pack(side=tk.LEFT)
        ttk.Label(status_row, textvariable=self.status_var).pack(side=tk.LEFT, padx=(6, 0))

        log_group = ttk.LabelFrame(tab_log, text="Application Log", padding=6)
        log_group.pack(fill="both", expand=True)
        self.log_box = tk.Text(log_group, height=8, font=("Consolas", 9), state=tk.DISABLED)
        self.log_box.pack(fill="both", expand=True)

        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    def _append_log_line(self, line: str) -> None:
        self.log_box.configure(state=tk.NORMAL)
        self.log_box.insert(tk.END, line)
        self.log_box.see(tk.END)
        self.log_box.configure(state=tk.DISABLED)

    def log(self, text: str) -> None:
        timestamp = time.strftime("%H:%M:%S")
        line = f"[{timestamp}] {text}\n"
        if threading.current_thread() is threading.main_thread():
            self._append_log_line(line)
        else:
            self.root.after(0, self._append_log_line, line)

    @staticmethod
    def _hex_to_rgb(value: str) -> tuple[int, int, int]:
        value = value.lstrip("#")
        return int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)

    @staticmethod
    def _rgb_to_hex(rgb: tuple[int, int, int]) -> str:
        return f"#{rgb[0]:02x}{rgb[1]:02x}{rgb[2]:02x}"

    @staticmethod
    def _is_valid_theme_color(value: str) -> bool:
        return re.fullmatch(r"#[0-9a-fA-F]{6}", value.strip()) is not None

    @staticmethod
    def _normalize_theme_name(raw_name: str) -> str:
        name = re.sub(r"\s+", " ", raw_name.strip())
        return name[:48]

    def _normalize_theme_palette(self, raw_palette: Any) -> dict[str, str] | None:
        if not isinstance(raw_palette, dict):
            return None
        normalized: dict[str, str] = {}
        for key in THEME_COLOR_KEYS:
            raw_value = raw_palette.get(key)
            if not isinstance(raw_value, str):
                return None
            value = raw_value.strip().lower()
            if not self._is_valid_theme_color(value):
                return None
            normalized[key] = value
        return normalized

    def _refresh_theme_combo_values(self) -> None:
        custom_names = sorted(self.custom_theme_palettes.keys(), key=str.lower)
        values = list(self.default_theme_order) + [name for name in custom_names if name not in self.default_theme_names]
        if hasattr(self, "theme_combo"):
            self.theme_combo.configure(values=values)

    def _save_custom_themes(self) -> None:
        if not self.custom_theme_palettes:
            if os.path.exists(self.theme_config_path):
                os.remove(self.theme_config_path)
            return
        payload = {name: self.custom_theme_palettes[name] for name in sorted(self.custom_theme_palettes, key=str.lower)}
        with open(self.theme_config_path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)

    def _load_custom_themes(self) -> None:
        for theme_name in list(self.custom_theme_palettes.keys()):
            self.theme_palettes.pop(theme_name, None)
        self.custom_theme_palettes.clear()

        if not os.path.exists(self.theme_config_path):
            self._refresh_theme_combo_values()
            return
        try:
            with open(self.theme_config_path, "r", encoding="utf-8") as handle:
                raw_data = json.load(handle)
        except Exception as exc:
            self.log(f"Custom theme load skipped: {exc}")
            self._refresh_theme_combo_values()
            return

        loaded = 0
        skipped = 0
        if isinstance(raw_data, dict):
            for raw_name, raw_palette in raw_data.items():
                if not isinstance(raw_name, str):
                    skipped += 1
                    continue
                name = self._normalize_theme_name(raw_name)
                if not name or name in self.default_theme_names:
                    skipped += 1
                    continue
                palette = self._normalize_theme_palette(raw_palette)
                if palette is None:
                    skipped += 1
                    continue
                self.custom_theme_palettes[name] = palette
                self.theme_palettes[name] = dict(palette)
                loaded += 1
        else:
            skipped += 1

        self._refresh_theme_combo_values()
        if loaded > 0:
            self.log(f"Loaded {loaded} custom theme(s).")
        if skipped > 0:
            noun = "entry" if skipped == 1 else "entries"
            self.log(f"Skipped {skipped} invalid custom theme {noun}.")

    def open_theme_maker(self) -> None:
        if self.theme_maker_window is not None and self.theme_maker_window.winfo_exists():
            self.theme_maker_window.lift()
            self.theme_maker_window.focus_force()
            return

        window = tk.Toplevel(self.root)
        self.theme_maker_window = window
        window.title("Theme Maker")
        window.geometry("650x360")
        window.minsize(650, 360)
        window.resizable(False, False)
        window.transient(self.root)
        window.protocol("WM_DELETE_WINDOW", self._theme_maker_on_close)

        container = ttk.Frame(window, padding=10)
        container.pack(fill="both", expand=True)

        name_row = ttk.Frame(container)
        name_row.pack(fill="x")
        self.theme_maker_name_var = tk.StringVar(value=self.theme_name_var.get().strip() or "Custom Theme")
        ttk.Label(name_row, text="Theme name:").pack(side=tk.LEFT)
        ttk.Entry(name_row, textvariable=self.theme_maker_name_var, width=26).pack(side=tk.LEFT, padx=(8, 8))
        ttk.Button(name_row, text="Load Current", width=12, command=self._theme_maker_load_current).pack(side=tk.LEFT, padx=(0, 4))
        ttk.Button(name_row, text="Load Selected", width=12, command=self._theme_maker_load_selected).pack(side=tk.LEFT)

        colors_group = ttk.LabelFrame(container, text="Palette Colors (#RRGGBB)", padding=8)
        colors_group.pack(fill="x", pady=(10, 8))

        self.theme_maker_color_vars = {}
        self.theme_maker_swatches = {}
        for idx, key in enumerate(THEME_COLOR_KEYS):
            row = idx // 2
            col = (idx % 2) * 4
            ttk.Label(colors_group, text=f"{key}:").grid(row=row, column=col, sticky="w", padx=(0, 4), pady=4)
            var = tk.StringVar(value=self.current_palette.get(key, "#000000"))
            self.theme_maker_color_vars[key] = var
            ttk.Entry(colors_group, textvariable=var, width=10, justify="center").grid(row=row, column=col + 1, sticky="w", padx=(0, 4))
            ttk.Button(colors_group, text="Pick", width=6, command=lambda k=key: self._theme_maker_pick_color(k)).grid(
                row=row,
                column=col + 2,
                sticky="w",
                padx=(0, 4),
            )
            swatch = tk.Label(colors_group, text="    ", relief="solid", borderwidth=1)
            swatch.grid(row=row, column=col + 3, sticky="w")
            self.theme_maker_swatches[key] = swatch
            var.trace_add("write", lambda *_args, k=key: self._theme_maker_update_swatch(k))

        button_row = ttk.Frame(container)
        button_row.pack(fill="x", pady=(2, 0))
        ttk.Button(button_row, text="Preview", width=12, command=self._theme_maker_preview).pack(side=tk.LEFT)
        ttk.Button(button_row, text="Save Theme", width=12, command=self._theme_maker_save).pack(side=tk.LEFT, padx=(6, 0))
        ttk.Button(button_row, text="Delete Theme", width=12, command=self._theme_maker_delete).pack(side=tk.LEFT, padx=(6, 0))
        ttk.Button(button_row, text="Import Theme", width=12, command=self._theme_maker_import).pack(side=tk.LEFT, padx=(6, 0))
        ttk.Button(button_row, text="Export Theme", width=12, command=self._theme_maker_export).pack(side=tk.LEFT, padx=(6, 0))
        ttk.Button(button_row, text="Close", width=10, command=self._theme_maker_on_close).pack(side=tk.RIGHT)

        ttk.Label(
            container,
            text="Built-in themes are read-only. Save a custom theme to add it to the dropdown.",
        ).pack(anchor="w", pady=(8, 0))

        self._theme_maker_update_all_swatches()
        self._apply_theme(self.current_palette)

    def _theme_maker_on_close(self) -> None:
        if self.theme_maker_window is not None and self.theme_maker_window.winfo_exists():
            self.theme_maker_window.destroy()
        self.theme_maker_window = None
        self.theme_maker_name_var = None
        self.theme_maker_color_vars = {}
        self.theme_maker_swatches = {}

    def _theme_maker_load_current(self) -> None:
        if self.theme_maker_name_var is not None:
            self.theme_maker_name_var.set(self.theme_name_var.get().strip() or "Custom Theme")
        for key in THEME_COLOR_KEYS:
            var = self.theme_maker_color_vars.get(key)
            if var is not None:
                var.set(self.current_palette.get(key, "#000000"))
        self._theme_maker_update_all_swatches()

    def _theme_maker_load_selected(self) -> None:
        selected = self.theme_name_var.get().strip()
        palette = self.theme_palettes.get(selected)
        if palette is None:
            self._theme_maker_load_current()
            return
        if self.theme_maker_name_var is not None:
            self.theme_maker_name_var.set(selected)
        for key in THEME_COLOR_KEYS:
            var = self.theme_maker_color_vars.get(key)
            if var is not None:
                var.set(palette.get(key, "#000000"))
        self._theme_maker_update_all_swatches()

    def _theme_maker_pick_color(self, key: str) -> None:
        var = self.theme_maker_color_vars.get(key)
        if var is None:
            return
        initial = var.get().strip() if self._is_valid_theme_color(var.get()) else self.current_palette.get(key, "#000000")
        _rgb, picked = colorchooser.askcolor(color=initial, parent=self.theme_maker_window)
        if picked:
            var.set(picked.lower())
            self._theme_maker_update_swatch(key)

    def _theme_maker_update_swatch(self, key: str) -> None:
        swatch = self.theme_maker_swatches.get(key)
        var = self.theme_maker_color_vars.get(key)
        if swatch is None or var is None:
            return
        value = var.get().strip()
        if self._is_valid_theme_color(value):
            swatch.configure(bg=value, fg=value, text="    ")
        else:
            swatch.configure(bg="#ff9b9b", fg="#ff9b9b", text=" !! ")

    def _theme_maker_update_all_swatches(self) -> None:
        for key in THEME_COLOR_KEYS:
            self._theme_maker_update_swatch(key)

    def _theme_maker_collect_palette(self) -> dict[str, str]:
        palette: dict[str, str] = {}
        invalid: list[str] = []
        for key in THEME_COLOR_KEYS:
            var = self.theme_maker_color_vars.get(key)
            value = var.get().strip() if var is not None else ""
            if not self._is_valid_theme_color(value):
                invalid.append(key)
                continue
            palette[key] = value.lower()
        if invalid:
            raise ValueError(f"Invalid #RRGGBB value for: {', '.join(invalid)}")
        return palette

    def _theme_maker_preview(self) -> None:
        try:
            palette = self._theme_maker_collect_palette()
        except ValueError as exc:
            messagebox.showerror("Theme Maker", str(exc))
            return
        self.current_palette = dict(palette)
        self._apply_theme(self.current_palette)
        self.log("Theme maker preview applied.")

    def _theme_maker_save(self) -> None:
        raw_name = self.theme_maker_name_var.get() if self.theme_maker_name_var is not None else ""
        name = self._normalize_theme_name(raw_name)
        if not name:
            messagebox.showerror("Theme Maker", "Theme name cannot be empty.")
            return
        existing_name = next((candidate for candidate in self.theme_palettes if candidate.lower() == name.lower()), None)
        if existing_name in self.default_theme_names:
            messagebox.showerror("Theme Maker", "Built-in themes are read-only. Choose a different name.")
            return
        if existing_name is not None:
            name = existing_name

        try:
            palette = self._theme_maker_collect_palette()
            self.custom_theme_palettes[name] = dict(palette)
            self.theme_palettes[name] = dict(palette)
            self._save_custom_themes()
        except Exception as exc:
            messagebox.showerror("Theme Maker", f"Could not save theme: {exc}")
            return

        self._refresh_theme_combo_values()
        self.theme_name_var.set(name)
        if self.theme_maker_name_var is not None:
            self.theme_maker_name_var.set(name)
        self._apply_selected_theme()
        self.log(f"Theme saved: {name}")

    def _theme_maker_delete(self) -> None:
        raw_name = self.theme_maker_name_var.get() if self.theme_maker_name_var is not None else ""
        name = self._normalize_theme_name(raw_name)
        existing_name = next((candidate for candidate in self.custom_theme_palettes if candidate.lower() == name.lower()), None)
        if existing_name is None:
            messagebox.showinfo("Theme Maker", "Select a saved custom theme to delete.")
            return
        if not messagebox.askyesno("Theme Maker", f"Delete custom theme '{existing_name}'?"):
            return

        self.custom_theme_palettes.pop(existing_name, None)
        self.theme_palettes.pop(existing_name, None)
        try:
            self._save_custom_themes()
        except Exception as exc:
            messagebox.showerror("Theme Maker", f"Could not update theme file: {exc}")
            return

        self._refresh_theme_combo_values()
        fallback = "Midnight"
        if self.theme_name_var.get().strip() == existing_name:
            self.theme_name_var.set(fallback)
            self._apply_selected_theme()
        if self.theme_maker_name_var is not None:
            self.theme_maker_name_var.set(self.theme_name_var.get().strip())
        self._theme_maker_load_selected()
        self.log(f"Theme deleted: {existing_name}")

    def _make_unique_custom_theme_name(self, base_name: str) -> str:
        name = self._normalize_theme_name(base_name) or "Custom Theme"
        if name in self.default_theme_names:
            name = f"{name} Custom"
        if name not in self.theme_palettes:
            return name
        for i in range(2, 200):
            candidate = f"{name} {i}"
            if candidate not in self.theme_palettes:
                return candidate
        return f"{name} {int(time.time())}"

    def _theme_maker_export(self) -> None:
        raw_name = self.theme_maker_name_var.get() if self.theme_maker_name_var is not None else self.theme_name_var.get()
        name = self._normalize_theme_name(raw_name) or "Custom Theme"
        try:
            palette = self._theme_maker_collect_palette()
        except Exception:
            palette = dict(self.current_palette)

        default_name = f"{self._sanitize_preset_name(name).lower()}-theme.json"
        path = filedialog.asksaveasfilename(
            defaultextension=".json",
            initialfile=default_name,
            filetypes=[("JSON", "*.json")],
        )
        if not path:
            return
        payload = {
            "name": name,
            "palette": palette,
            "exported_at": datetime.now().isoformat(timespec="seconds"),
            "version": APP_VERSION,
        }
        try:
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, indent=2)
            self.log(f"Theme exported: {path}")
        except Exception as exc:
            messagebox.showerror("Theme Maker", f"Could not export theme: {exc}")

    def _theme_maker_import(self) -> None:
        path = filedialog.askopenfilename(filetypes=[("JSON", "*.json")])
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
        except Exception as exc:
            messagebox.showerror("Theme Maker", f"Could not read file: {exc}")
            return

        raw_name = os.path.splitext(os.path.basename(path))[0]
        raw_palette: Any = None
        if isinstance(data, dict):
            if "palette" in data:
                raw_palette = data.get("palette")
                name_value = data.get("name")
                if isinstance(name_value, str) and name_value.strip():
                    raw_name = name_value
            elif all(key in data for key in THEME_COLOR_KEYS):
                raw_palette = data
            else:
                # Also allow {"Theme A": {...palette...}} shape by taking first valid entry.
                for key, value in data.items():
                    candidate = self._normalize_theme_palette(value)
                    if candidate is not None:
                        raw_palette = candidate
                        if isinstance(key, str) and key.strip():
                            raw_name = key
                        break

        palette = self._normalize_theme_palette(raw_palette)
        if palette is None:
            messagebox.showerror("Theme Maker", "Imported file does not contain a valid AFKScope theme palette.")
            return

        name = self._make_unique_custom_theme_name(raw_name)
        if self.theme_maker_name_var is not None:
            self.theme_maker_name_var.set(name)
        for key in THEME_COLOR_KEYS:
            var = self.theme_maker_color_vars.get(key)
            if var is not None:
                var.set(palette[key])
        self._theme_maker_update_all_swatches()
        self._theme_maker_save()
        self.log(f"Theme imported: {name}")

    def _apply_selected_theme(self) -> None:
        name = self.theme_name_var.get().strip()
        palette = self.theme_palettes.get(name)
        if palette is None:
            name = "Midnight"
            self.theme_name_var.set(name)
            palette = self.theme_palettes[name]
        self.current_theme_name = name
        self.current_palette = dict(palette)
        self._apply_theme(self.current_palette)
        self.log(f"Theme applied: {name}")
        self._record_event(f"Theme: {name}")

    def _apply_theme(self, palette: dict[str, str]) -> None:
        try:
            self.root.configure(bg=palette["bg"])
        except tk.TclError:
            pass

        self.style.configure(".", background=palette["bg"], foreground=palette["text"])
        self.style.configure("TFrame", background=palette["bg"])
        self.style.configure("TLabelframe", background=palette["bg"], foreground=palette["text"])
        self.style.configure("TLabelframe.Label", background=palette["bg"], foreground=palette["text"])
        self.style.configure("TLabel", background=palette["bg"], foreground=palette["text"])
        self.style.configure("TButton", background=palette["panel"], foreground=palette["text"], borderwidth=1)
        self.style.map(
            "TButton",
            background=[("active", palette["field"]), ("pressed", palette["field"])],
            foreground=[("disabled", palette["muted"])],
        )
        self.style.configure("TCheckbutton", background=palette["bg"], foreground=palette["text"])
        self.style.configure("TRadiobutton", background=palette["bg"], foreground=palette["text"])
        self.style.configure("TEntry", fieldbackground=palette["field"], foreground=palette["text"])

        self.style.configure(
            "Treeview",
            background=palette["field"],
            foreground=palette["text"],
            fieldbackground=palette["field"],
        )
        self.style.configure("Treeview.Heading", background=palette["panel"], foreground=palette["text"])
        self.style.map("Treeview", background=[("selected", palette["tree_sel"])], foreground=[("selected", palette["tree_selfg"])])

        for widget in (self.log_box, self.health_text, self.diagnostics_text):
            widget.configure(
                bg=palette["field"],
                fg=palette["text"],
                insertbackground=palette["text"],
                highlightbackground=palette["panel"],
                highlightcolor=palette["accent"],
            )
        self.biome_history_list.configure(
            bg=palette["field"],
            fg=palette["text"],
            highlightbackground=palette["panel"],
            highlightcolor=palette["accent"],
            selectbackground=palette["tree_sel"],
            selectforeground=palette["tree_selfg"],
        )
        if self.header_logo_label is not None:
            self.header_logo_label.configure(bg=palette["bg"])
        if self.header_title_label is not None:
            self.header_title_label.configure(bg=palette["bg"], fg=palette["accent"])
        if self.header_subtitle_label is not None:
            self.header_subtitle_label.configure(bg=palette["bg"], fg=palette["muted"])
        if self.header_icon_badge is not None:
            self.header_icon_badge.configure(
                bg=palette["field"],
                highlightbackground=palette["accent"],
            )
        if hasattr(self, "biome_badge"):
            self.biome_badge.configure(
                highlightbackground=palette["panel"],
                highlightcolor=palette["accent"],
            )
            self._render_biome_badge()

    def on_theme_selected(self, _event: tk.Event | None = None) -> None:
        self._apply_selected_theme()

    @staticmethod
    def _pick_text_color(bg_hex: str) -> str:
        r, g, b = AntiAfkApp._hex_to_rgb(bg_hex)
        luminance = (0.299 * r) + (0.587 * g) + (0.114 * b)
        return "#000000" if luminance >= 170 else "#ffffff"

    @staticmethod
    def _normalize_biome(raw: str) -> str | None:
        compact = re.sub(r"[^a-z]", "", raw.lower())
        return BIOME_ALIAS_MAP.get(compact)

    def _extract_biome_from_line(self, line: str) -> tuple[str | None, str]:
        line = line.strip()
        if not line:
            return None, "none"

        rpc_match = self._bloxstrap_presence_pattern.search(line)
        if rpc_match:
            try:
                payload = json.loads(rpc_match.group("payload"))
                if isinstance(payload, dict) and payload.get("command") == "SetRichPresence":
                    data = payload.get("data")
                    if isinstance(data, dict):
                        large_image = data.get("largeImage")
                        if isinstance(large_image, dict):
                            hover_text = large_image.get("hoverText")
                            if isinstance(hover_text, str) and hover_text.strip():
                                biome = self._normalize_biome(hover_text)
                                if biome:
                                    return biome, "bloxstrap"
            except json.JSONDecodeError:
                pass

        for pattern in self._biome_line_patterns:
            match = pattern.search(line)
            if not match:
                continue
            candidate = match.group(1)
            biome = self._normalize_biome(candidate)
            if biome:
                return biome, "roblox-log"
        return None, "none"

    def _get_biome_log_dirs(self) -> list[str]:
        local_app_data = os.getenv("LOCALAPPDATA", "")
        return [
            os.path.join(local_app_data, "Roblox", "logs"),
            os.path.join(local_app_data, "Bloxstrap", "Logs"),
            os.path.join(local_app_data, "Voidstrap", "Logs"),
        ]

    def _find_latest_biome_log(self) -> str | None:
        candidates: list[tuple[float, str]] = []
        for log_dir in self._get_biome_log_dirs():
            if not os.path.isdir(log_dir):
                continue
            path = Path(log_dir)
            for pattern in ("*_Player_*.log", "*.log"):
                for entry in path.glob(pattern):
                    try:
                        mtime = entry.stat().st_mtime
                    except OSError:
                        continue
                    candidates.append((mtime, str(entry)))
        if not candidates:
            return None
        candidates.sort(key=lambda item: item[0], reverse=True)
        return candidates[0][1]

    def _render_biome_badge(self) -> None:
        biome = self.current_biome_name
        if biome in BIOME_COLOR_MAP:
            color = BIOME_COLOR_MAP[biome]
            text = biome
        else:
            color = self.current_palette["field"]
            text = "Unknown"
        if biome == "GLITCHED":
            text = "GL1TCHED" if int(time.time() * 2) % 2 else "GLITCHED"
        fg = self._pick_text_color(color)
        self.biome_display_var.set(text)
        self.biome_meta_var.set(f"Source: {self.current_biome_source}")
        if hasattr(self, "biome_badge"):
            self.biome_badge.configure(bg=color, fg=fg)

    def _append_biome_history(self, biome: str, source: str) -> None:
        stamp = time.strftime("%H:%M:%S")
        line = f"{stamp} | {biome} | {source}"
        self.biome_history.append(line)
        self.biome_history = self.biome_history[-120:]
        if hasattr(self, "biome_history_list"):
            self.biome_history_list.delete(0, tk.END)
            for item in self.biome_history[-40:]:
                self.biome_history_list.insert(tk.END, item)

    def _record_event(self, text: str) -> None:
        stamp = time.strftime("%H:%M:%S")
        line = f"{stamp} | {text}"
        self.event_timeline.append(line)
        self.event_timeline = self.event_timeline[-160:]
        if hasattr(self, "event_history_list"):
            self.event_history_list.delete(0, tk.END)
            for item in self.event_timeline[-60:]:
                self.event_history_list.insert(tk.END, item)

    def _maybe_send_biome_alert(self, biome: str) -> None:
        if not self.biome_alerts_enabled_var.get():
            return
        tracked = self.rare_biome_var.get().strip().upper()
        if not tracked or biome != tracked:
            return
        now = time.time()
        last = self.last_biome_alert_at.get(biome, 0.0)
        if now - last < self.biome_alert_cooldown_seconds:
            return
        self.last_biome_alert_at[biome] = now
        self._send_webhook("AFKScope Rare Biome", f"Detected tracked rare biome: {biome}")
        action = self.biome_action_var.get().strip().lower()
        if action == "pause_5m":
            until = time.localtime(now + 300)
            self.pause_enabled_var.set(True)
            self.pause_start_var.set(time.strftime("%H:%M", time.localtime(now)))
            self.pause_end_var.set(time.strftime("%H:%M", until))
            self.log("Rare biome action: pause schedule set for 5 minutes.")
            self._record_event("Rare biome action: pause_5m")
        elif action == "load_preset":
            self.preset_name_var.set(self.biome_action_preset_var.get().strip() or "default")
            self.load_preset()
            self._record_event("Rare biome action: load_preset")

    def _set_current_biome(self, biome: str, source: str) -> None:
        if biome not in BIOME_COLOR_MAP:
            return
        changed = biome != self.current_biome_name
        self.current_biome_name = biome
        self.current_biome_source = source
        self.current_biome_seen_at = time.time()
        if changed:
            self.biome_counts[biome] = self.biome_counts.get(biome, 0) + 1
            self.log(f"Biome detected: {biome} ({source}).")
            self._append_biome_history(biome, source)
            self._maybe_send_biome_alert(biome)
        self._render_biome_badge()

    def _poll_biome_tracker(self) -> None:
        log_path = self._find_latest_biome_log()
        if not log_path:
            self.current_biome_source = "-"
            self._render_biome_badge()
            return

        try:
            log_size = os.path.getsize(log_path)
        except OSError:
            return

        if self.biome_log_path != log_path:
            self.biome_log_path = log_path
            self.biome_log_offset = max(0, log_size - 250_000)
        elif log_size < self.biome_log_offset:
            self.biome_log_offset = 0

        try:
            with open(log_path, "r", encoding="utf-8", errors="ignore") as handle:
                handle.seek(self.biome_log_offset)
                chunk = handle.read(250_000)
                self.biome_log_offset = handle.tell()
        except OSError:
            return

        detected_biome: str | None = None
        detected_source = "roblox-log"
        for line in chunk.splitlines():
            biome, source = self._extract_biome_from_line(line)
            if biome is not None:
                detected_biome = biome
                detected_source = source

        if detected_biome:
            self._set_current_biome(detected_biome, detected_source)
        elif self.current_biome_name == "GLITCHED":
            self._render_biome_badge()

    def _send_webhook(self, title: str, description: str) -> None:
        if not self.webhook_enabled_var.get():
            return
        url = self.webhook_url_var.get().strip()
        if not url:
            return

        def _worker() -> None:
            payload = {
                "embeds": [
                    {
                        "title": title,
                        "description": description,
                        "color": 0x4FC3F7,
                        "timestamp": datetime.utcnow().isoformat() + "Z",
                    }
                ]
            }
            data = json.dumps(payload).encode("utf-8")
            req = urlrequest.Request(
                url,
                data=data,
                headers={"Content-Type": "application/json", "User-Agent": APP_USER_AGENT},
                method="POST",
            )
            try:
                with urlrequest.urlopen(req, timeout=10):
                    pass
            except Exception:
                pass

        threading.Thread(target=_worker, daemon=True).start()

    def set_running_ui(self, running: bool) -> None:
        self.is_running = running
        self.start_button.configure(state=tk.DISABLED if running else tk.NORMAL)
        self.stop_button.configure(state=tk.NORMAL if running else tk.DISABLED)
        self.test_button.configure(state=tk.DISABLED if running else tk.NORMAL)
        self.refresh_button.configure(state=tk.DISABLED if running else tk.NORMAL)
        self.align_button.configure(state=tk.DISABLED if running else tk.NORMAL)
        self.restore_button.configure(state=tk.DISABLED if running else tk.NORMAL)
        self.save_button.configure(state=tk.DISABLED if running else tk.NORMAL)
        self.load_button.configure(state=tk.DISABLED if running else tk.NORMAL)
        self.status_var.set("Running" if running else "Idle")

    def parse_interval(self) -> float:
        raw = self.interval_var.get().strip()
        try:
            interval = float(raw)
        except ValueError as exc:
            raise ValueError("Interval must be a number.") from exc
        if interval <= 0:
            raise ValueError("Interval must be greater than 0.")
        return interval

    def parse_watchdog_threshold(self) -> int:
        raw = self.watchdog_threshold_var.get().strip()
        try:
            value = int(raw)
        except ValueError as exc:
            raise ValueError("Watchdog threshold must be an integer.") from exc
        if value < 1:
            raise ValueError("Watchdog threshold must be >= 1.")
        return value

    def parse_health_alert_minutes(self) -> int:
        raw = self.health_alert_minutes_var.get().strip()
        try:
            value = int(raw)
        except ValueError as exc:
            raise ValueError("Health alert minutes must be an integer.") from exc
        if value < 1:
            raise ValueError("Health alert minutes must be >= 1.")
        return value

    def parse_autosave_minutes(self) -> int:
        raw = self.autosave_minutes_var.get().strip()
        try:
            value = int(raw)
        except ValueError as exc:
            raise ValueError("Auto-save minutes must be an integer.") from exc
        if value < 1:
            raise ValueError("Auto-save minutes must be >= 1.")
        return value

    @staticmethod
    def _parse_hhmm(raw: str, label: str) -> tuple[int, int]:
        text = raw.strip()
        parts = text.split(":")
        if len(parts) != 2:
            raise ValueError(f"{label} must be HH:MM (24-hour).")
        try:
            hour = int(parts[0])
            minute = int(parts[1])
        except ValueError as exc:
            raise ValueError(f"{label} must be HH:MM (24-hour).") from exc
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            raise ValueError(f"{label} must be a valid 24-hour time.")
        return hour, minute

    def _validate_pause_schedule(self) -> None:
        if not self.pause_enabled_var.get():
            return
        start_hour, start_min = self._parse_hhmm(self.pause_start_var.get(), "Pause start")
        end_hour, end_min = self._parse_hhmm(self.pause_end_var.get(), "Pause end")
        if start_hour == end_hour and start_min == end_min:
            raise ValueError("Pause start and end cannot be identical.")

    @staticmethod
    def _is_valid_webhook_url(url: str) -> bool:
        parsed = urlparse.urlparse(url.strip())
        if parsed.scheme.lower() != "https":
            return False
        return bool(parsed.netloc and parsed.path)

    def validate_runtime_settings(self) -> None:
        self.parse_interval()
        self.parse_watchdog_threshold()
        if self.health_alert_enabled_var.get():
            self.parse_health_alert_minutes()
        if self.autosave_enabled_var.get():
            self.parse_autosave_minutes()
        self._validate_pause_schedule()
        if self.webhook_enabled_var.get():
            url = self.webhook_url_var.get().strip()
            if not url:
                raise ValueError("Webhook is enabled but URL is empty.")
            if not self._is_valid_webhook_url(url):
                raise ValueError("Webhook URL must be a valid HTTPS URL.")

    def _detect_unclean_shutdown(self) -> bool:
        if not os.path.exists(self.recovery_state_path):
            return False
        return True

    def _write_recovery_state_marker(self) -> None:
        payload = {
            "pid": os.getpid(),
            "started_at": datetime.now().isoformat(timespec="seconds"),
            "version": APP_VERSION,
        }
        try:
            with open(self.recovery_state_path, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, indent=2)
        except Exception:
            pass

    def _clear_recovery_state_marker(self) -> None:
        try:
            if os.path.exists(self.recovery_state_path):
                os.remove(self.recovery_state_path)
        except Exception:
            pass

    def _write_recovery_snapshot(self, force: bool = False) -> None:
        if not self.autosave_enabled_var.get() and not force:
            return
        try:
            every_minutes = self.parse_autosave_minutes()
        except ValueError:
            every_minutes = 2
        now = time.time()
        if not force and (now - self.last_autosave_at) < (every_minutes * 60):
            return
        payload = {
            "saved_at": datetime.now().isoformat(timespec="seconds"),
            "version": APP_VERSION,
            "config": self._collect_config_data(),
            "runtime": {
                "is_running": self.is_running,
                "session_started_at": self.session_started_at,
                "session_cycles": self.session_cycles,
                "session_jumps": self.session_jumps,
                "session_errors": self.session_errors,
            },
        }
        try:
            with open(self.recovery_snapshot_path, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, indent=2)
            self.last_autosave_at = now
        except Exception:
            pass

    def _schedule_recovery_autosave(self) -> None:
        self._write_recovery_snapshot(force=False)
        self.root.after(30_000, self._schedule_recovery_autosave)

    def _prompt_recovery_restore(self) -> None:
        if not self.recovery_prompt_needed:
            return
        self.recovery_prompt_needed = False
        if not os.path.exists(self.recovery_snapshot_path):
            return
        try:
            with open(self.recovery_snapshot_path, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
            if not isinstance(payload, dict):
                return
            raw_config = payload.get("config")
            if not isinstance(raw_config, dict):
                return
        except Exception:
            return

        restore = messagebox.askyesno(
            "Recovery Snapshot Found",
            "AFKScope detected a previous unclean shutdown.\n\nRestore settings from the latest auto-save snapshot?",
        )
        if not restore:
            self.log("Recovery snapshot skipped by user.")
            return
        try:
            self._apply_config_data(raw_config)
            self.log("Recovered settings from auto-save snapshot.")
            self._record_event("Recovery snapshot restored")
        except Exception as exc:
            self.log(f"Recovery restore failed: {exc}")

    def open_quick_setup_wizard(self) -> None:
        if self.quick_setup_window is not None and self.quick_setup_window.winfo_exists():
            self.quick_setup_window.lift()
            self.quick_setup_window.focus_force()
            return
        self.should_offer_setup_wizard = False

        window = tk.Toplevel(self.root)
        self.quick_setup_window = window
        window.title("Quick Setup Wizard")
        window.geometry("540x320")
        window.minsize(540, 320)
        window.resizable(False, False)
        window.transient(self.root)
        window.protocol("WM_DELETE_WINDOW", self._close_quick_setup_wizard)

        container = ttk.Frame(window, padding=12)
        container.pack(fill="both", expand=True)

        ttk.Label(
            container,
            text="Welcome to AFKScope. Configure a safe baseline and save it in one step.",
            font=("Segoe UI", 10, "bold"),
        ).pack(anchor="w")
        ttk.Label(
            container,
            text="You can change all settings later in the Controls tab.",
        ).pack(anchor="w", pady=(4, 10))

        interval_var = tk.StringVar(value=self.interval_var.get())
        jump_mode_var = tk.StringVar(value=self.jump_mode_var.get())
        auto_realign_var = tk.BooleanVar(value=self.auto_realign_var.get())
        hotkeys_var = tk.BooleanVar(value=self.hotkeys_enabled_var.get())

        grid = ttk.Frame(container)
        grid.pack(fill="x")
        ttk.Label(grid, text="Jump interval (seconds):").grid(row=0, column=0, sticky="w")
        ttk.Entry(grid, textvariable=interval_var, width=8, justify="center").grid(row=0, column=1, sticky="w", padx=(6, 0))
        ttk.Label(grid, text="Jump mode:").grid(row=1, column=0, sticky="w", pady=(8, 0))
        ttk.Combobox(grid, textvariable=jump_mode_var, values=["all", "round"], state="readonly", width=10).grid(
            row=1,
            column=1,
            sticky="w",
            padx=(6, 0),
            pady=(8, 0),
        )
        ttk.Checkbutton(grid, text="Auto realign windows", variable=auto_realign_var).grid(row=2, column=0, columnspan=2, sticky="w", pady=(10, 0))
        ttk.Checkbutton(grid, text="Enable global hotkeys", variable=hotkeys_var).grid(row=3, column=0, columnspan=2, sticky="w", pady=(6, 0))

        actions = ttk.Frame(container)
        actions.pack(fill="x", pady=(14, 0))
        ttk.Button(actions, text="Detect Roblox Windows", width=22, command=lambda: self.refresh_instance_list(manual=True)).pack(
            side=tk.LEFT
        )

        def _apply_and_save() -> None:
            self.interval_var.set(interval_var.get().strip())
            self.jump_mode_var.set(jump_mode_var.get().strip() or "all")
            self.auto_realign_var.set(bool(auto_realign_var.get()))
            self.hotkeys_enabled_var.set(bool(hotkeys_var.get()))
            try:
                self.validate_runtime_settings()
                self.save_config()
                self.on_hotkeys_toggle()
                self.log("Quick setup wizard applied.")
                self._record_event("Quick setup completed")
            except Exception as exc:
                messagebox.showerror("Quick Setup", str(exc))
                return
            self._close_quick_setup_wizard()

        ttk.Button(actions, text="Apply & Save", width=14, command=_apply_and_save).pack(side=tk.RIGHT)
        ttk.Button(actions, text="Skip", width=10, command=self._close_quick_setup_wizard).pack(side=tk.RIGHT, padx=(0, 6))

    def _close_quick_setup_wizard(self) -> None:
        if self.quick_setup_window is not None and self.quick_setup_window.winfo_exists():
            self.quick_setup_window.destroy()
        self.quick_setup_window = None

    def on_hotkeys_toggle(self) -> None:
        self._set_global_hotkeys_enabled(self.hotkeys_enabled_var.get(), log_result=True)

    def _set_global_hotkeys_enabled(self, enabled: bool, log_result: bool) -> None:
        if enabled:
            ok = self._register_global_hotkeys()
            if ok and log_result:
                self.log("Global hotkeys enabled (Ctrl+Alt+S/J/R/T).")
            elif not ok and log_result:
                self.log("Global hotkeys unavailable (some combinations may already be in use).")
            self.hotkeys_enabled_var.set(ok)
        else:
            self._unregister_global_hotkeys()
            if log_result:
                self.log("Global hotkeys disabled.")

    def _register_global_hotkeys(self) -> bool:
        if self.global_hotkeys_registered:
            return True
        self.hotkey_actions.clear()
        combos: list[tuple[int, str, int, Callable[[], None]]] = [
            (1, "Start/Stop", ord("S"), lambda: self.stop() if self.is_running else self.start()),
            (2, "Jump Now", ord("J"), self.test_jump),
            (3, "Refresh", ord("R"), lambda: self.refresh_instance_list(manual=True)),
            (4, "To Tray", ord("T"), self.minimize_to_tray),
        ]
        registered_count = 0
        for hotkey_id, label, vk, action in combos:
            ok = self.user32.RegisterHotKey(None, hotkey_id, MOD_CONTROL | MOD_ALT, vk)
            if ok:
                self.hotkey_actions[hotkey_id] = (label, action)
                registered_count += 1
        if registered_count != len(combos):
            self._unregister_global_hotkeys()
            return False
        self.global_hotkeys_registered = registered_count > 0
        if self.global_hotkeys_registered:
            self.root.after(150, self._poll_global_hotkeys)
        return self.global_hotkeys_registered

    def _unregister_global_hotkeys(self) -> None:
        for hotkey_id in list(self.hotkey_actions.keys()):
            try:
                self.user32.UnregisterHotKey(None, hotkey_id)
            except Exception:
                pass
        self.hotkey_actions.clear()
        self.global_hotkeys_registered = False

    def _poll_global_hotkeys(self) -> None:
        if not self.global_hotkeys_registered:
            return
        msg = wintypes.MSG()
        try:
            while self.user32.PeekMessageW(ctypes.byref(msg), None, WM_HOTKEY, WM_HOTKEY, PM_REMOVE):
                if int(msg.message) != WM_HOTKEY:
                    continue
                hotkey_id = int(msg.wParam)
                entry = self.hotkey_actions.get(hotkey_id)
                if not entry:
                    continue
                label, action = entry
                self._record_event(f"Hotkey: {label}")
                self.root.after(0, action)
        except Exception:
            pass
        self.root.after(120, self._poll_global_hotkeys)

    def _ensure_vgamepad_module(self) -> Any:
        global vg, vg_import_error, vg_import_attempted

        if vg is None and not vg_import_attempted:
            vg_import_attempted = True
            vg, vg_import_error = _import_vgamepad_safely()

        if vg is None:
            extra = f" ({vg_import_error})" if vg_import_error else ""
            raise RuntimeError(
                "vgamepad/ViGEmClient failed to load. Reinstall ViGEmBus and rebuild with collected binaries"
                + extra
            )
        return vg

    def _vgamepad_status(self) -> str:
        if vg is not None:
            return "OK"
        if not vg_import_attempted:
            return "NOT LOADED (lazy)"
        if vg_import_error:
            return f"FAIL ({vg_import_error})"
        return "FAIL"

    def ensure_gamepad(self) -> None:
        vg_module = cast(Any, self._ensure_vgamepad_module())
        if self.gamepad is None:
            self.gamepad = vg_module.VX360Gamepad()

    @staticmethod
    def _window_title(hwnd: int) -> str:
        length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return ""
        buff = ctypes.create_unicode_buffer(length + 1)
        ctypes.windll.user32.GetWindowTextW(hwnd, buff, length + 1)
        return buff.value

    def _get_process_name(self, pid: int) -> str:
        cached = self._process_name_cache.get(pid)
        if cached is not None:
            return cached

        process_query_limited_information = 0x1000
        handle = self.kernel32.OpenProcess(process_query_limited_information, False, pid)
        if not handle:
            self._process_name_cache[pid] = ""
            return ""

        try:
            size = wintypes.DWORD(260)
            buffer = ctypes.create_unicode_buffer(size.value)
            ok = self.kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size))
            if not ok:
                self._process_name_cache[pid] = ""
                return ""
            name = os.path.basename(buffer.value)
            self._process_name_cache[pid] = name
            return name
        finally:
            self.kernel32.CloseHandle(handle)

    def find_roblox_windows(self) -> list[tuple[int, str, int, str]]:
        windows: list[tuple[int, str, int, str]] = []
        enum_proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

        def _enum_cb(hwnd: int, _lparam: int) -> bool:
            if not self.user32.IsWindowVisible(hwnd):
                return True
            title = self._window_title(hwnd)
            if not title:
                return True

            pid_ref = wintypes.DWORD(0)
            self.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid_ref))
            pid = int(pid_ref.value)
            process_name = self._get_process_name(pid)
            proc_lower = process_name.lower()
            if proc_lower in {"robloxplayerbeta.exe", "windows10universal.exe"}:
                windows.append((int(hwnd), title, pid, process_name))
            return True

        callback = enum_proc(_enum_cb)
        self.user32.EnumWindows(callback, 0)
        return windows

    def _extract_username_from_text(self, text: str) -> str | None:
        for pattern in self.username_patterns:
            match = pattern.search(text)
            if not match:
                continue
            username = match.group(1).strip()
            if username and username.lower() not in self.excluded_usernames:
                return username
        return None

    def _find_candidate_logs_for_pid(self, pid: int) -> list[str]:
        local_app_data = os.getenv("LOCALAPPDATA", "")
        candidates: list[tuple[float, str]] = []
        log_dirs = [
            os.path.join(local_app_data, "Roblox", "logs"),
            os.path.join(local_app_data, "Bloxstrap", "Logs"),
            os.path.join(local_app_data, "Voidstrap", "Logs"),
        ]
        for log_dir in log_dirs:
            if not os.path.isdir(log_dir):
                continue
            try:
                for name in os.listdir(log_dir):
                    if not name.lower().endswith(".log"):
                        continue
                    full = os.path.join(log_dir, name)
                    try:
                        mtime = os.path.getmtime(full)
                    except OSError:
                        continue
                    candidates.append((mtime, full))
            except OSError:
                continue

        pid_hex_upper = format(pid, "X")
        pid_hex_lower = pid_hex_upper.lower()
        candidates.sort(key=lambda item: item[0], reverse=True)

        ranked: list[str] = []
        for _mtime, full in candidates[:150]:
            filename = os.path.basename(full)
            if (
                f"_{pid_hex_upper}_" in filename
                or f"_{pid_hex_lower}_" in filename.lower()
                or f"_{pid_hex_upper}." in filename
                or f"_{pid_hex_lower}." in filename.lower()
            ):
                ranked.append(full)

        for _mtime, full in candidates[:60]:
            if full in ranked:
                continue
            try:
                with open(full, "r", encoding="utf-8", errors="ignore") as f:
                    header = f.read(65536)
            except OSError:
                continue
            if f"pid:{pid}" in header or f"PID: {pid}" in header:
                ranked.append(full)

        for _mtime, full in candidates[:25]:
            if full not in ranked:
                ranked.append(full)

        return ranked

    def _detect_username_for_pid(self, pid: int) -> tuple[str | None, str]:
        for log_path in self._find_candidate_logs_for_pid(pid):
            try:
                with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
                    text = f.read(2_000_000)
            except OSError:
                continue
            username = self._extract_username_from_text(text)
            if username:
                return username, "log"
        return None, "unknown"

    @staticmethod
    def _fetch_json(url: str, method: str = "GET", body: bytes | None = None) -> dict[str, Any] | None:
        headers = {"User-Agent": APP_USER_AGENT}
        if method == "POST":
            headers["Content-Type"] = "application/json"
        req = urlrequest.Request(url, data=body, headers=headers, method=method)
        try:
            with urlrequest.urlopen(req, timeout=10) as resp:
                payload = resp.read().decode("utf-8", errors="ignore")
            data = json.loads(payload)
            if isinstance(data, dict):
                return data
            return None
        except (urlerror.URLError, TimeoutError, json.JSONDecodeError):
            return None

    def _resolve_user_id(self, username: str) -> int | None:
        body = json.dumps({"usernames": [username], "excludeBannedUsers": False}).encode("utf-8")
        data = self._fetch_json("https://users.roblox.com/v1/usernames/users", method="POST", body=body)
        if not data:
            return None
        entries = data.get("data", [])
        if not isinstance(entries, list) or not entries:
            return None
        first = entries[0]
        if not isinstance(first, dict):
            return None
        user_id = first.get("id")
        return int(user_id) if isinstance(user_id, int) else None

    def _resolve_avatar_bytes(self, user_id: int) -> bytes | None:
        url = (
            "https://thumbnails.roblox.com/v1/users/avatar-headshot"
            f"?userIds={user_id}&size=48x48&format=Png&isCircular=false"
        )
        data = self._fetch_json(url)
        if not data:
            return None
        entries = data.get("data", [])
        if not isinstance(entries, list) or not entries:
            return None
        first = entries[0]
        if not isinstance(first, dict):
            return None
        image_url = first.get("imageUrl")
        if not isinstance(image_url, str) or not image_url:
            return None
        req = urlrequest.Request(image_url, headers={"User-Agent": APP_USER_AGENT})
        try:
            with urlrequest.urlopen(req, timeout=10) as resp:
                return resp.read()
        except (urlerror.URLError, TimeoutError):
            return None

    def _start_identity_lookup(self, pid: int) -> None:
        if pid in self.identity_lookup_inflight:
            return
        self.identity_lookup_inflight.add(pid)
        self.identity_last_attempt[pid] = time.time()
        threading.Thread(target=self._identity_lookup_worker, args=(pid,), daemon=True).start()

    def _identity_lookup_worker(self, pid: int) -> None:
        username, confidence = self._detect_username_for_pid(pid)
        user_id: int | None = None
        avatar_bytes: bytes | None = None
        if username:
            user_id = self._resolve_user_id(username)
            if user_id is not None:
                confidence = "api"
                avatar_bytes = self._resolve_avatar_bytes(user_id)
        self.root.after(0, lambda: self._apply_identity_result(pid, username, user_id, confidence, avatar_bytes))

    def _apply_identity_result(
        self,
        pid: int,
        username: str | None,
        user_id: int | None,
        confidence: str,
        avatar_bytes: bytes | None,
    ) -> None:
        self.identity_lookup_inflight.discard(pid)
        if username:
            self.pid_username[pid] = username
            self.enabled_by_username.setdefault(username.lower(), True)
        self.pid_identity_confidence[pid] = confidence
        if user_id is not None:
            self.pid_user_id[pid] = user_id
        if avatar_bytes:
            try:
                encoded = base64.b64encode(avatar_bytes).decode("ascii")
                image = tk.PhotoImage(data=encoded, format="png")
                if image.width() > 32:
                    step = max(1, (image.width() + 31) // 32)
                    image = cast(tk.PhotoImage, image.subsample(step))
                self.pid_avatar_photo[pid] = image
            except tk.TclError:
                pass
        self.refresh_instance_list(manual=False)

    def refresh_instance_list(self, manual: bool) -> None:
        previous_count = len(self.window_map)
        old_map = {hwnd: (title, pid, pname) for hwnd, title, pid, pname in self.window_map}
        self.window_map = self.find_roblox_windows()

        for old_hwnd, (_title, old_pid, _pname) in old_map.items():
            username = self.pid_username.get(old_pid)
            if username:
                self.enabled_by_username[username.lower()] = self.instance_enabled_by_hwnd.get(old_hwnd, True)

        active_hwnds = {hwnd for hwnd, _, _, _ in self.window_map}
        self.instance_enabled_by_hwnd = {hwnd: enabled for hwnd, enabled in self.instance_enabled_by_hwnd.items() if hwnd in active_hwnds}
        self.instance_last_jump = {hwnd: ts for hwnd, ts in self.instance_last_jump.items() if hwnd in active_hwnds}

        for hwnd, _title, pid, _pname in self.window_map:
            if hwnd not in self.instance_enabled_by_hwnd:
                username = self.pid_username.get(pid, "").lower()
                if username and username in self.enabled_by_username:
                    self.instance_enabled_by_hwnd[hwnd] = self.enabled_by_username[username]
                else:
                    self.instance_enabled_by_hwnd[hwnd] = self.loaded_enabled_by_pid.get(pid, True)

        for item in self.instance_tree.get_children():
            self.instance_tree.delete(item)

        for hwnd, title, pid, pname in sorted(self.window_map, key=lambda x: x[2]):
            enabled = self.instance_enabled_by_hwnd.get(hwnd, True)
            username = self.pid_username.get(pid)
            if not username:
                username = "Detecting..." if pid in self.identity_lookup_inflight else "Unknown"
            confidence = self.pid_identity_confidence.get(pid, "unknown")
            last_jump = self.instance_last_jump.get(hwnd)
            last_jump_str = time.strftime("%H:%M:%S", time.localtime(last_jump)) if last_jump else "-"
            avatar = self.pid_avatar_photo.get(pid)
            values = (
                "Yes" if enabled else "No",
                str(pid),
                str(hwnd),
                pname or "unknown.exe",
                username,
                confidence,
                last_jump_str,
                title[:100],
            )
            item_id = self.instance_tree.insert("", tk.END, iid=str(hwnd), text="", image=avatar if avatar else "")
            self.instance_tree.item(item_id, values=list(values))

        now = time.time()
        pids = {pid for _hwnd, _title, pid, _pname in self.window_map}
        for pid in pids:
            if pid in self.pid_username:
                continue
            if pid in self.identity_lookup_inflight:
                continue
            if now - self.identity_last_attempt.get(pid, 0) >= 20:
                self._start_identity_lookup(pid)

        if len(self.window_map) != self.last_window_count:
            self.last_window_count = len(self.window_map)
            self.log(f"Detected Roblox windows: {len(self.window_map)}")

        if self.auto_realign_var.get() and len(self.window_map) > 0 and len(self.window_map) != previous_count:
            self.align_windows(log_result=False)
            self.log("Auto-realigned windows after instance count change.")

        self.update_health_panel()
        if manual:
            self.log("Instance list refreshed.")

    def update_health_panel(self) -> None:
        lines: list[str] = []
        biome_seen = "-"
        if self.current_biome_seen_at is not None:
            biome_seen = time.strftime("%H:%M:%S", time.localtime(self.current_biome_seen_at))
        lines.append(f"Biome {self.current_biome_name} | source {self.current_biome_source} | seen {biome_seen}")
        if not self.window_map:
            lines.append("No Roblox instances detected.")
        else:
            enabled_count = 0
            for hwnd, title, pid, _pname in self.window_map:
                enabled = self.instance_enabled_by_hwnd.get(hwnd, True)
                if enabled:
                    enabled_count += 1
                username = self.pid_username.get(pid, "unknown")
                confidence = self.pid_identity_confidence.get(pid, "unknown")
                last_jump = self.instance_last_jump.get(hwnd)
                last_jump_str = time.strftime("%H:%M:%S", time.localtime(last_jump)) if last_jump else "never"
                status = "ENABLED" if enabled else "DISABLED"
                lines.append(
                    f"PID {pid} | {username} ({confidence}) | HWND {hwnd} | {status} | last jump {last_jump_str} | {title[:26]}"
                )
            lines.insert(1, f"Enabled {enabled_count}/{len(self.window_map)} instances")

        self.health_text.configure(state=tk.NORMAL)
        self.health_text.delete("1.0", tk.END)
        self.health_text.insert(tk.END, "\n".join(lines))
        self.health_text.configure(state=tk.DISABLED)

    def _toggle_hwnd_enabled(self, hwnd: int) -> None:
        if hwnd not in self.instance_enabled_by_hwnd:
            return
        self.instance_enabled_by_hwnd[hwnd] = not self.instance_enabled_by_hwnd[hwnd]
        pid = next((pid for h, _t, pid, _p in self.window_map if h == hwnd), None)
        if pid is not None:
            username = self.pid_username.get(pid)
            if username:
                self.enabled_by_username[username.lower()] = self.instance_enabled_by_hwnd[hwnd]
        self.refresh_instance_list(manual=False)

    def on_tree_double_click(self, event: tk.Event) -> None:
        item_id = self.instance_tree.identify_row(event.y)
        column_id = self.instance_tree.identify_column(event.x)
        if not item_id or column_id != "#1":
            return
        try:
            hwnd = int(item_id)
        except ValueError:
            return
        self._toggle_hwnd_enabled(hwnd)

    def retry_selected_identity(self) -> None:
        selected = self.instance_tree.selection()
        if not selected:
            self.log("Retry identity skipped: no row selected.")
            return
        for item in selected:
            try:
                hwnd = int(item)
            except ValueError:
                continue
            pid = next((pid for h, _t, pid, _p in self.window_map if h == hwnd), None)
            if pid is None:
                continue
            self.pid_username.pop(pid, None)
            self.pid_user_id.pop(pid, None)
            self.pid_avatar_photo.pop(pid, None)
            self.pid_identity_confidence.pop(pid, None)
            self.identity_last_attempt[pid] = 0
            self._start_identity_lookup(pid)
        self.log("Requested identity retry for selected instances.")

    def enable_all_instances(self) -> None:
        for hwnd, _title, pid, _pname in self.window_map:
            self.instance_enabled_by_hwnd[hwnd] = True
            username = self.pid_username.get(pid)
            if username:
                self.enabled_by_username[username.lower()] = True
        self.refresh_instance_list(manual=False)
        self.log("Enabled all detected instances.")

    def disable_all_instances(self) -> None:
        for hwnd, _title, pid, _pname in self.window_map:
            self.instance_enabled_by_hwnd[hwnd] = False
            username = self.pid_username.get(pid)
            if username:
                self.enabled_by_username[username.lower()] = False
        self.refresh_instance_list(manual=False)
        self.log("Disabled all detected instances.")

    def spoof_focus(self, hwnd: int, active: bool) -> None:
        wm_activate = 0x0006
        wm_setfocus = 0x0007
        wm_ncactivate = 0x0086
        wa_active = 1
        wa_inactive = 0

        if active:
            self.user32.PostMessageW(hwnd, wm_ncactivate, 1, 0)
            self.user32.PostMessageW(hwnd, wm_activate, wa_active, 0)
            self.user32.PostMessageW(hwnd, wm_setfocus, 0, 0)
        else:
            self.user32.PostMessageW(hwnd, wm_activate, wa_inactive, 0)
            self.user32.PostMessageW(hwnd, wm_ncactivate, 0, 0)

    def _capture_layout(self, hwnd: int) -> None:
        if hwnd in self.layout_cache:
            return
        gwl_style = -16
        rect = wintypes.RECT()
        if not self.user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            return
        style = int(self.user32.GetWindowLongW(hwnd, gwl_style))
        self.layout_cache[hwnd] = (style, rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top)

    def align_windows(self, log_result: bool = True) -> None:
        roblox_windows = self.find_roblox_windows()
        if not roblox_windows:
            if log_result:
                self.log("Align skipped: no Roblox windows found.")
            return

        windows = sorted(roblox_windows, key=lambda item: item[2])
        count = len(windows)

        spi_getworkarea = 0x0030
        sw_restore = 9
        sw_show = 5
        gwl_style = -16
        ws_caption = 0x00C00000
        ws_thickframe = 0x00040000
        ws_border = 0x00800000
        ws_popup = 0x80000000
        swp_noactivate = 0x0010
        swp_framechanged = 0x0020
        hwnd_bottom = 1

        rect = wintypes.RECT()
        ok = self.user32.SystemParametersInfoW(spi_getworkarea, 0, ctypes.byref(rect), 0)
        if not ok:
            if log_result:
                self.log("Align failed: could not read screen work area.")
            return

        start_x = int(rect.left)
        start_y = int(rect.top)
        screen_width = int(rect.right - rect.left)
        screen_height = int(rect.bottom - rect.top)

        cols = math.ceil(math.sqrt(count))
        rows = math.ceil(count / cols)
        min_waste = (cols * rows) - count
        for c in range(cols + 1, count + 1):
            r = math.ceil(count / c)
            if c / r > 2.5:
                break
            waste = (c * r) - count
            if waste < min_waste:
                cols = c
                rows = r
                min_waste = waste
                if waste == 0:
                    break

        windows_in_last_row = count % cols
        if windows_in_last_row == 0:
            windows_in_last_row = cols
        last_row_index = rows - 1

        for i, (hwnd, _title, _pid, _pname) in enumerate(windows):
            self._capture_layout(hwnd)
            if self.user32.IsIconic(hwnd):
                self.user32.ShowWindow(hwnd, sw_restore)
            else:
                self.user32.ShowWindow(hwnd, sw_show)

            style = int(self.user32.GetWindowLongW(hwnd, gwl_style))
            style &= ~(ws_caption | ws_thickframe | ws_border)
            style |= ws_popup
            self.user32.SetWindowLongW(hwnd, gwl_style, style)

            r = i // cols
            c = i % cols
            is_last_row = (r == last_row_index) and (windows_in_last_row < cols)

            if is_last_row:
                last_row_col = i - (last_row_index * cols)
                x = start_x + int(last_row_col * (screen_width / windows_in_last_row))
                y = start_y + int(r * (screen_height / rows))
                w = start_x + int((last_row_col + 1) * (screen_width / windows_in_last_row)) - x
                h = start_y + int((r + 1) * (screen_height / rows)) - y
            else:
                x = start_x + int(c * (screen_width / cols))
                y = start_y + int(r * (screen_height / rows))
                w = start_x + int((c + 1) * (screen_width / cols)) - x
                h = start_y + int((r + 1) * (screen_height / rows)) - y

            self.user32.SetWindowPos(hwnd, hwnd_bottom, x, y, w, h, swp_noactivate | swp_framechanged)

        if log_result:
            self.log(f"Aligned {count} Roblox windows to grid.")

    def restore_windows(self) -> None:
        if not self.layout_cache:
            self.log("Restore skipped: no cached layout found.")
            return

        gwl_style = -16
        swp_noactivate = 0x0010
        swp_framechanged = 0x0020

        restored = 0
        for hwnd, (style, x, y, w, h) in list(self.layout_cache.items()):
            if not self.user32.IsWindow(hwnd):
                continue
            self.user32.SetWindowLongW(hwnd, gwl_style, style)
            self.user32.SetWindowPos(hwnd, 0, x, y, w, h, swp_noactivate | swp_framechanged)
            restored += 1

        self.log(f"Restored {restored} Roblox windows.")

    def _is_in_pause_window(self) -> bool:
        if not self.pause_enabled_var.get():
            return False
        try:
            start_hour, start_min = self._parse_hhmm(self.pause_start_var.get(), "Pause start")
            end_hour, end_min = self._parse_hhmm(self.pause_end_var.get(), "Pause end")
        except Exception:
            return False

        now = datetime.now()
        now_mins = now.hour * 60 + now.minute
        start_mins = start_hour * 60 + start_min
        end_mins = end_hour * 60 + end_min

        if start_mins <= end_mins:
            return start_mins <= now_mins < end_mins
        return now_mins >= start_mins or now_mins < end_mins

    def _resolve_target_hwnds(self) -> list[int]:
        windows = self.find_roblox_windows()
        enabled = [hwnd for hwnd, _title, _pid, _pname in windows if self.instance_enabled_by_hwnd.get(hwnd, True)]
        if not enabled:
            return []

        if self.jump_mode_var.get() == "round":
            self.round_robin_index = self.round_robin_index % len(enabled)
            hwnd = enabled[self.round_robin_index]
            self.round_robin_index = (self.round_robin_index + 1) % len(enabled)
            return [hwnd]
        return enabled

    def _reset_gamepad_session(self) -> None:
        self.gamepad = None
        self.ensure_gamepad()
        self.log("Watchdog reset: reinitialized gamepad session.")
        self._send_webhook("AFKScope Watchdog", "Gamepad session reset after repeated failed cycles.")

    def _run_recovery_sequence(self) -> None:
        try:
            self.refresh_instance_list(manual=False)
            self.restore_windows()
            if self.auto_realign_var.get():
                self.align_windows(log_result=False)
            self._record_event("Recovery sequence executed")
        except Exception as exc:
            self.log(f"Recovery sequence failed: {exc}")
            self._record_event(f"Recovery failed: {exc}")

    def jump_once(self) -> bool:
        if self._is_in_pause_window():
            with self.metrics_lock:
                self.session_cycles += 1
            return False

        self.ensure_gamepad()
        vg_module = cast(Any, self._ensure_vgamepad_module())
        gamepad = self.gamepad
        if gamepad is None:
            raise RuntimeError("Virtual gamepad is not initialized.")

        target_hwnds = self._resolve_target_hwnds()
        if not target_hwnds:
            with self.metrics_lock:
                self.session_cycles += 1
            return False

        for hwnd in target_hwnds:
            self.spoof_focus(hwnd, True)

        pattern = self.anti_idle_pattern_var.get().strip().lower()
        stick_x = 2000
        stick_hold = 0.05
        gap = 0.03
        button_hold = 0.12
        if pattern == "subtle":
            stick_x = random.randint(900, 1600)
            stick_hold = 0.03
            button_hold = 0.1
        elif pattern == "aggressive":
            stick_x = random.randint(2600, 4200)
            stick_hold = 0.08
            button_hold = 0.14
        elif pattern == "randomized":
            stick_x = random.randint(800, 4600)
            stick_hold = random.uniform(0.02, 0.1)
            gap = random.uniform(0.01, 0.05)
            button_hold = random.uniform(0.09, 0.17)

        gamepad.left_joystick(stick_x, 0)
        gamepad.update()
        time.sleep(stick_hold)
        gamepad.left_joystick(0, 0)
        gamepad.update()
        time.sleep(gap)

        jump_button = vg_module.XUSB_BUTTON.XUSB_GAMEPAD_A
        gamepad.press_button(jump_button)
        gamepad.update()
        time.sleep(button_hold)
        gamepad.release_button(jump_button)
        gamepad.update()

        for hwnd in target_hwnds:
            self.spoof_focus(hwnd, False)
            self.instance_last_jump[hwnd] = time.time()

        with self.metrics_lock:
            self.session_cycles += 1
            self.session_jumps += len(target_hwnds)

        self.root.after(0, self.update_health_panel)
        self.root.after(0, lambda: self.refresh_instance_list(manual=False))
        return True

    def test_jump(self) -> None:
        try:
            sent = self.jump_once()
            if sent:
                self.log("Manual jump sent to enabled instances.")
            else:
                self.log("No enabled Roblox windows found for jump test.")
        except Exception as exc:
            with self.metrics_lock:
                self.session_errors += 1
            messagebox.showerror("Jump test failed", str(exc))

    def worker(self, interval: float) -> None:
        self.log(f"Anti-AFK loop started (interval={interval:.2f}s).")
        self._record_event("Loop started")
        self._send_webhook("AFKScope", "Anti-AFK loop started.")
        threshold = self.parse_watchdog_threshold() if self.watchdog_enabled_var.get() else 999999

        while not self.stop_event.is_set():
            try:
                sent = self.jump_once()
                if sent:
                    self.failed_cycles = 0
                    self.log("Sent virtual jump (A) to enabled spoofed instances.")
                    self._record_event("Jump cycle success")
                else:
                    self.failed_cycles += 1
                    self.log("No enabled Roblox windows found or cycle paused.")

                if self.watchdog_enabled_var.get() and self.failed_cycles >= threshold:
                    if self.recovery_enabled_var.get():
                        self._run_recovery_sequence()
                    self._reset_gamepad_session()
                    self.failed_cycles = 0
            except Exception as exc:  # pragma: no cover
                self.failed_cycles += 1
                with self.metrics_lock:
                    self.session_errors += 1
                self.log(f"Error while sending jump: {exc}")
                self._record_event(f"Loop error: {exc}")
                self._send_webhook("AFKScope Error", f"Jump loop error: {exc}")
                self.root.after(0, self.stop)
                return

            if self.stop_event.wait(interval):
                break

        self.log("Anti-AFK loop stopped.")
        self._record_event("Loop stopped")
        self._send_webhook("AFKScope", "Anti-AFK loop stopped.")

    def start(self) -> None:
        if self.is_running:
            return

        try:
            self.validate_runtime_settings()
            interval = self.parse_interval()
            self.refresh_instance_list(manual=False)
            self.ensure_gamepad()
        except Exception as exc:
            with self.metrics_lock:
                self.session_errors += 1
            messagebox.showerror("Cannot start", str(exc))
            return

        with self.metrics_lock:
            if self.session_started_at is None:
                self.session_started_at = time.time()

        self.stop_event.clear()
        self.worker_thread = threading.Thread(target=self.worker, args=(interval,), daemon=True)
        self.worker_thread.start()
        self.set_running_ui(True)
        self._write_recovery_snapshot(force=True)

    def stop(self) -> None:
        self.stop_event.set()
        if self.worker_thread and self.worker_thread.is_alive():
            self.worker_thread.join(timeout=0.5)
        self.set_running_ui(False)
        self._write_recovery_snapshot(force=True)

    def _schedule_stats_update(self) -> None:
        with self.metrics_lock:
            started = self.session_started_at
            cycles = self.session_cycles
            jumps = self.session_jumps
            errors = self.session_errors

        runtime = 0
        if started is not None:
            runtime = int(time.time() - started)
        hh = runtime // 3600
        mm = (runtime % 3600) // 60
        ss = runtime % 60
        self.stats_var.set(f"Runtime {hh:02d}:{mm:02d}:{ss:02d} | Cycles {cycles} | Jumps {jumps} | Errors {errors}")
        self.root.after(1000, self._schedule_stats_update)

    def _schedule_instance_poll(self) -> None:
        self.refresh_instance_list(manual=False)
        self._poll_biome_tracker()
        self._check_instance_health_alerts()
        self.root.after(2500, self._schedule_instance_poll)

    def _check_instance_health_alerts(self) -> None:
        active_hwnds = {hwnd for hwnd, _title, _pid, _pname in self.window_map}
        self.last_instance_health_alert = {
            hwnd: ts for hwnd, ts in self.last_instance_health_alert.items() if hwnd in active_hwnds
        }
        if not self.is_running or not self.health_alert_enabled_var.get():
            return
        try:
            threshold_seconds = self.parse_health_alert_minutes() * 60
        except ValueError:
            threshold_seconds = 180
        now = time.time()
        for hwnd, _title, pid, _pname in self.window_map:
            if not self.instance_enabled_by_hwnd.get(hwnd, True):
                continue
            baseline = self.instance_last_jump.get(hwnd)
            if baseline is None:
                baseline = self.session_started_at if self.session_started_at is not None else now
            gap = now - baseline
            if gap < threshold_seconds:
                continue
            last_alert = self.last_instance_health_alert.get(hwnd, 0.0)
            if now - last_alert < threshold_seconds:
                continue
            self.last_instance_health_alert[hwnd] = now
            username = self.pid_username.get(pid, "unknown")
            msg = (
                f"No successful jump for PID {pid} ({username}) "
                f"for {int(gap // 60)}m {int(gap % 60)}s."
            )
            self.log(f"Instance health alert: {msg}")
            self._record_event(f"Health alert: PID {pid}")
            self._send_webhook("AFKScope Instance Health Alert", msg)

    def _enabled_by_pid_snapshot(self) -> dict[int, bool]:
        mapping: dict[int, bool] = {}
        for hwnd, _title, pid, _pname in self.window_map:
            mapping[pid] = self.instance_enabled_by_hwnd.get(hwnd, True)
        return mapping

    def _collect_config_data(self) -> dict[str, Any]:
        return {
            "interval_seconds": self.interval_var.get().strip(),
            "auto_realign": bool(self.auto_realign_var.get()),
            "enabled_by_pid": {str(pid): enabled for pid, enabled in self._enabled_by_pid_snapshot().items()},
            "jump_mode": self.jump_mode_var.get(),
            "pause_enabled": bool(self.pause_enabled_var.get()),
            "pause_start": self.pause_start_var.get().strip(),
            "pause_end": self.pause_end_var.get().strip(),
            "webhook_enabled": bool(self.webhook_enabled_var.get()),
            "webhook_url": self.webhook_url_var.get().strip(),
            "watchdog_enabled": bool(self.watchdog_enabled_var.get()),
            "watchdog_threshold": self.watchdog_threshold_var.get().strip(),
            "theme_name": self.theme_name_var.get().strip(),
            "anti_idle_pattern": self.anti_idle_pattern_var.get().strip(),
            "hotkeys_enabled": bool(self.hotkeys_enabled_var.get()),
            "health_alert_enabled": bool(self.health_alert_enabled_var.get()),
            "health_alert_minutes": self.health_alert_minutes_var.get().strip(),
            "autosave_enabled": bool(self.autosave_enabled_var.get()),
            "autosave_minutes": self.autosave_minutes_var.get().strip(),
            "biome_alerts_enabled": bool(self.biome_alerts_enabled_var.get()),
            "rare_biome": self.rare_biome_var.get().strip().upper(),
            "biome_action": self.biome_action_var.get().strip(),
            "biome_action_preset": self.biome_action_preset_var.get().strip(),
            "recovery_enabled": bool(self.recovery_enabled_var.get()),
        }

    def _apply_config_data(self, data: dict[str, Any]) -> None:
        interval = str(data.get("interval_seconds", "5"))
        auto_realign = bool(data.get("auto_realign", False))
        raw_enabled = data.get("enabled_by_pid", {})
        enabled_by_pid: dict[int, bool] = {}
        if isinstance(raw_enabled, dict):
            for k, v in raw_enabled.items():
                try:
                    enabled_by_pid[int(k)] = bool(v)
                except (TypeError, ValueError):
                    continue

        self.interval_var.set(interval)
        self.auto_realign_var.set(auto_realign)
        self.loaded_enabled_by_pid = enabled_by_pid
        self.jump_mode_var.set(str(data.get("jump_mode", "all")))
        self.pause_enabled_var.set(bool(data.get("pause_enabled", False)))
        self.pause_start_var.set(str(data.get("pause_start", "02:00")))
        self.pause_end_var.set(str(data.get("pause_end", "06:00")))
        self.webhook_enabled_var.set(bool(data.get("webhook_enabled", False)))
        self.webhook_url_var.set(str(data.get("webhook_url", "")))
        self.watchdog_enabled_var.set(bool(data.get("watchdog_enabled", True)))
        self.watchdog_threshold_var.set(str(data.get("watchdog_threshold", "12")))
        theme_name = str(data.get("theme_name", "")).strip()
        if theme_name not in self.theme_palettes:
            legacy_dark = bool(data.get("dark_mode", False))
            theme_name = "Midnight" if legacy_dark else "Solarized Light"
        self.theme_name_var.set(theme_name)
        anti_pattern = str(data.get("anti_idle_pattern", "balanced")).strip().lower()
        if anti_pattern not in {"balanced", "subtle", "aggressive", "randomized"}:
            anti_pattern = "balanced"
        self.anti_idle_pattern_var.set(anti_pattern)
        self.hotkeys_enabled_var.set(bool(data.get("hotkeys_enabled", True)))
        self.health_alert_enabled_var.set(bool(data.get("health_alert_enabled", True)))
        self.health_alert_minutes_var.set(str(data.get("health_alert_minutes", "3")))
        self.autosave_enabled_var.set(bool(data.get("autosave_enabled", True)))
        self.autosave_minutes_var.set(str(data.get("autosave_minutes", "2")))
        self.biome_alerts_enabled_var.set(bool(data.get("biome_alerts_enabled", False)))
        self.rare_biome_var.set(str(data.get("rare_biome", "GLITCHED")).strip().upper() or "GLITCHED")
        biome_action = str(data.get("biome_action", "webhook")).strip().lower()
        if biome_action not in {"webhook", "pause_5m", "load_preset"}:
            biome_action = "webhook"
        self.biome_action_var.set(biome_action)
        self.biome_action_preset_var.set(str(data.get("biome_action_preset", "default")).strip())
        self.recovery_enabled_var.set(bool(data.get("recovery_enabled", True)))
        self._apply_selected_theme()
        self._set_global_hotkeys_enabled(self.hotkeys_enabled_var.get(), log_result=False)
        self.refresh_instance_list(manual=False)

    @staticmethod
    def _sanitize_preset_name(name: str) -> str:
        cleaned = re.sub(r"[^A-Za-z0-9_-]+", "_", name.strip())
        return cleaned[:48].strip("_") or "default"

    def _preset_path(self, preset_name: str) -> str:
        return os.path.join(self.presets_dir, f"{self._sanitize_preset_name(preset_name)}.json")

    def _refresh_preset_list(self) -> None:
        os.makedirs(self.presets_dir, exist_ok=True)
        names: list[str] = []
        try:
            for entry in os.listdir(self.presets_dir):
                if entry.lower().endswith(".json"):
                    names.append(os.path.splitext(entry)[0])
        except OSError:
            names = []
        names = sorted(set(names))
        if not names:
            names = ["default"]
        self.preset_combo.configure(values=names)
        if self.preset_name_var.get().strip() not in names:
            self.preset_name_var.set(names[0])

    def save_preset(self) -> None:
        name = self._sanitize_preset_name(self.preset_name_var.get())
        path = self._preset_path(name)
        data = self._collect_config_data()
        try:
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(data, handle, indent=2)
            self.preset_name_var.set(name)
            self._refresh_preset_list()
            self.log(f"Preset saved: {name}")
        except Exception as exc:
            messagebox.showerror("Save preset failed", str(exc))

    def load_preset(self) -> None:
        name = self._sanitize_preset_name(self.preset_name_var.get())
        path = self._preset_path(name)
        if not os.path.exists(path):
            messagebox.showinfo("Preset", f"Preset not found: {name}")
            return
        try:
            with open(path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
            if not isinstance(data, dict):
                raise ValueError("Preset file is invalid.")
            self._apply_config_data(data)
            self.log(f"Preset loaded: {name}")
        except Exception as exc:
            messagebox.showerror("Load preset failed", str(exc))

    def delete_preset(self) -> None:
        name = self._sanitize_preset_name(self.preset_name_var.get())
        if name == "default":
            messagebox.showinfo("Preset", "Default preset cannot be deleted.")
            return
        path = self._preset_path(name)
        if not os.path.exists(path):
            messagebox.showinfo("Preset", f"Preset not found: {name}")
            return
        try:
            os.remove(path)
            self.log(f"Preset deleted: {name}")
            self._refresh_preset_list()
        except Exception as exc:
            messagebox.showerror("Delete preset failed", str(exc))

    def run_diagnostics_checks(self) -> None:
        windows = self.find_roblox_windows()
        latest_log = self._find_latest_biome_log() or "none"
        webhook_on = self.webhook_enabled_var.get() and bool(self.webhook_url_var.get().strip())
        try:
            self._validate_pause_schedule()
            pause_validation = "OK"
        except Exception as exc:
            pause_validation = f"INVALID ({exc})"
        webhook_validation = "OK"
        webhook_url = self.webhook_url_var.get().strip()
        if self.webhook_enabled_var.get():
            webhook_validation = "OK" if self._is_valid_webhook_url(webhook_url) else "INVALID (must be HTTPS URL)"
        checks = [
            f"AFKScope version: {APP_VERSION}",
            f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"vgamepad import: {self._vgamepad_status()}",
            f"Gamepad session: {'READY' if self.gamepad is not None else 'NOT INITIALIZED'}",
            f"Roblox windows detected: {len(windows)}",
            f"Biome log source: {latest_log}",
            f"Current biome: {self.current_biome_name} ({self.current_biome_source})",
            f"Theme: {self.current_theme_name}",
            f"Anti-idle pattern: {self.anti_idle_pattern_var.get()}",
            f"Global hotkeys: {'ON' if self.hotkeys_enabled_var.get() else 'OFF'} (Ctrl+Alt+S/J/R/T)",
            f"Instance health alerts: {'ON' if self.health_alert_enabled_var.get() else 'OFF'} ({self.health_alert_minutes_var.get().strip() or '3'} min)",
            f"Recovery auto-save: {'ON' if self.autosave_enabled_var.get() else 'OFF'} ({self.autosave_minutes_var.get().strip() or '2'} min)",
            f"Recovery sequence: {'ON' if self.recovery_enabled_var.get() else 'OFF'}",
            f"Webhook configured: {'YES' if webhook_on else 'NO'}",
            f"Webhook URL validation: {webhook_validation}",
            f"Pause schedule validation: {pause_validation}",
            f"Rare biome alerts: {'ON' if self.biome_alerts_enabled_var.get() else 'OFF'} ({self.rare_biome_var.get().strip().upper() or 'GLITCHED'})",
            f"Rare biome action: {self.biome_action_var.get()} ({self.biome_action_preset_var.get().strip() or 'default'})",
            f"Latest release URL: {self.latest_release_url}",
            f"Session errors: {self.session_errors}",
        ]
        body = "\n".join(checks)
        self.diagnostics_text.configure(state=tk.NORMAL)
        self.diagnostics_text.delete("1.0", tk.END)
        self.diagnostics_text.insert(tk.END, body)
        self.diagnostics_text.configure(state=tk.DISABLED)
        self.log("Diagnostics checks completed.")

    def export_debug_bundle(self) -> None:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        default_name = f"afkscope-debug-{stamp}.zip"
        path = filedialog.asksaveasfilename(
            defaultextension=".zip",
            initialfile=default_name,
            filetypes=[("Zip archive", "*.zip")],
        )
        if not path:
            return

        self.run_diagnostics_checks()
        diagnostics_body = self.diagnostics_text.get("1.0", tk.END).strip()
        app_log_tail = self.log_box.get("1.0", tk.END).splitlines()[-250:]
        biome_history = self.biome_history[-120:]

        try:
            with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                zf.writestr("diagnostics.txt", diagnostics_body + "\n")
                zf.writestr("afkscope-log-tail.txt", "\n".join(app_log_tail) + "\n")
                zf.writestr("biome-history.txt", "\n".join(biome_history) + "\n")
                if os.path.exists(self.config_path):
                    zf.write(self.config_path, arcname="afkscope_config.json")
                if os.path.exists(self.theme_config_path):
                    zf.write(self.theme_config_path, arcname="afkscope_themes.json")
                latest_log = self._find_latest_biome_log()
                if latest_log and os.path.exists(latest_log):
                    try:
                        with open(latest_log, "r", encoding="utf-8", errors="ignore") as handle:
                            lines = handle.readlines()[-600:]
                        zf.writestr("latest-roblox-log-tail.txt", "".join(lines))
                    except OSError:
                        pass
            self.log(f"Debug bundle exported: {path}")
        except Exception as exc:
            messagebox.showerror("Export debug bundle failed", str(exc))

    def save_config(self) -> None:
        data = self._collect_config_data()
        try:
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            self.log(f"Config saved: {self.config_path}")
        except Exception as exc:
            messagebox.showerror("Save config failed", str(exc))

    def load_config(self, silent: bool) -> None:
        if not os.path.exists(self.config_path):
            if not silent:
                messagebox.showinfo("Config", "No saved config found yet.")
            return

        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                raise ValueError("Config file is invalid.")
            self._apply_config_data(data)
            self.log(f"Config loaded: {self.config_path}")
        except Exception as exc:
            if not silent:
                messagebox.showerror("Load config failed", str(exc))

    def export_instances(self, mode: str) -> None:
        rows: list[dict[str, Any]] = []
        for hwnd, title, pid, pname in self.window_map:
            rows.append(
                {
                    "enabled": self.instance_enabled_by_hwnd.get(hwnd, True),
                    "pid": pid,
                    "hwnd": hwnd,
                    "process": pname,
                    "username": self.pid_username.get(pid, ""),
                    "identity": self.pid_identity_confidence.get(pid, "unknown"),
                    "last_jump": self.instance_last_jump.get(hwnd),
                    "title": title,
                }
            )

        if mode == "json":
            path = filedialog.asksaveasfilename(defaultextension=".json", filetypes=[("JSON", "*.json")])
            if not path:
                return
            with open(path, "w", encoding="utf-8") as f:
                json.dump(rows, f, indent=2)
            self.log(f"Exported JSON: {path}")
            return

        path = filedialog.asksaveasfilename(defaultextension=".csv", filetypes=[("CSV", "*.csv")])
        if not path:
            return
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=["enabled", "pid", "hwnd", "process", "username", "identity", "last_jump", "title"])
            writer.writeheader()
            writer.writerows(rows)
        self.log(f"Exported CSV: {path}")

    @staticmethod
    def _parse_version_parts(tag: str) -> tuple[int, int, int]:
        numbers = re.findall(r"\d+", tag)
        if not numbers:
            return (0, 0, 0)
        parts = [int(n) for n in numbers[:3]]
        while len(parts) < 3:
            parts.append(0)
        return parts[0], parts[1], parts[2]

    def open_presets_folder(self) -> None:
        os.makedirs(self.presets_dir, exist_ok=True)
        try:
            if os.name == "nt":
                os.startfile(self.presets_dir)  # type: ignore[attr-defined]
            else:
                webbrowser.open(f"file://{self.presets_dir}")
            self._record_event("Opened presets folder")
        except Exception as exc:
            messagebox.showerror("Open presets folder failed", str(exc))

    def copy_diagnostics_to_clipboard(self) -> None:
        text = self.diagnostics_text.get("1.0", tk.END).strip()
        if not text:
            self.run_diagnostics_checks()
            text = self.diagnostics_text.get("1.0", tk.END).strip()
        if not text:
            messagebox.showinfo("Diagnostics", "No diagnostics text available.")
            return
        try:
            self.root.clipboard_clear()
            self.root.clipboard_append(text)
            self.root.update()
            self.log("Diagnostics copied to clipboard.")
            self._record_event("Diagnostics copied")
        except Exception as exc:
            messagebox.showerror("Copy diagnostics failed", str(exc))

    def copy_support_bundle_to_clipboard(self) -> None:
        try:
            self.run_diagnostics_checks()
            diagnostics_lines = self.diagnostics_text.get("1.0", tk.END).strip().splitlines()
            log_tail = self.log_box.get("1.0", tk.END).splitlines()[-140:]
            payload = {
                "version": APP_VERSION,
                "generated_at": datetime.now().isoformat(timespec="seconds"),
                "diagnostics": diagnostics_lines,
                "settings": self._collect_config_data(),
                "recent_events": self.event_timeline[-60:],
                "recent_log_tail": log_tail,
            }
            text = json.dumps(payload, indent=2)
            self.root.clipboard_clear()
            self.root.clipboard_append(text)
            self.root.update()
            self.log("Support bundle copied to clipboard.")
            self._record_event("Support bundle copied")
        except Exception as exc:
            messagebox.showerror("Copy support bundle failed", str(exc))

    def open_latest_release_page(self) -> None:
        target = self.latest_release_url or "https://github.com/0bl1terate3/AFKScope/releases/latest"
        opened = webbrowser.open(target)
        if opened:
            self._record_event("Opened release page")
        else:
            messagebox.showinfo("Release page", target)

    def check_for_updates(self) -> None:
        release = self._fetch_json("https://api.github.com/repos/0bl1terate3/AFKScope/releases/latest")
        if not release:
            messagebox.showinfo("Updates", "Could not check for updates right now.")
            return
        tag = str(release.get("tag_name", "")).strip()
        url = str(release.get("html_url", "")).strip()
        body = str(release.get("body", "") or "").strip()
        if url:
            self.latest_release_url = url
        if not tag:
            messagebox.showinfo("Updates", "Latest release tag was not found.")
            return

        latest = self._parse_version_parts(tag)
        current = self._parse_version_parts(APP_VERSION)
        snippet = ""
        if body:
            for line in body.splitlines():
                s = line.strip()
                if s:
                    snippet = s
                    break
        if snippet:
            snippet = f"\n\nNotes: {snippet[:180]}"

        if latest == current:
            messagebox.showinfo("Updates", f"You're up to date ({APP_VERSION}).{snippet}")
            self._record_event("Update check: up to date")
            return
        if latest < current:
            messagebox.showinfo(
                "Updates",
                f"You're on a newer local build (v{APP_VERSION}) than latest release ({tag}).\n\n{url}",
            )
            self._record_event(f"Update check: local ahead of {tag}")
            return

        self._record_event(f"Update available: {tag}")
        messagebox.showinfo("Update Available", f"Latest: {tag}\nCurrent: v{APP_VERSION}\n\n{url}{snippet}")

    def export_portable_bundle(self) -> None:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        default_name = f"afkscope-portable-{stamp}.zip"
        path = filedialog.asksaveasfilename(
            defaultextension=".zip",
            initialfile=default_name,
            filetypes=[("Zip archive", "*.zip")],
        )
        if not path:
            return
        self.save_config()
        try:
            with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                if os.path.exists(self.config_path):
                    zf.write(self.config_path, arcname="afkscope_config.json")
                if os.path.exists(self.theme_config_path):
                    zf.write(self.theme_config_path, arcname="afkscope_themes.json")
                if os.path.isdir(self.presets_dir):
                    for name in os.listdir(self.presets_dir):
                        full = os.path.join(self.presets_dir, name)
                        if os.path.isfile(full) and name.lower().endswith(".json"):
                            zf.write(full, arcname=os.path.join("presets", name))
            self.log(f"Portable bundle exported: {path}")
            self._record_event("Portable export completed")
        except Exception as exc:
            messagebox.showerror("Export portable bundle failed", str(exc))

    def import_portable_bundle(self) -> None:
        path = filedialog.askopenfilename(filetypes=[("Zip archive", "*.zip")])
        if not path:
            return
        try:
            with zipfile.ZipFile(path, "r") as zf:
                members = zf.namelist()
                if "afkscope_config.json" in members:
                    with zf.open("afkscope_config.json") as src, open(self.config_path, "wb") as dst:
                        dst.write(src.read())
                if "afkscope_themes.json" in members:
                    with zf.open("afkscope_themes.json") as src, open(self.theme_config_path, "wb") as dst:
                        dst.write(src.read())
                os.makedirs(self.presets_dir, exist_ok=True)
                for name in members:
                    normalized = name.replace("\\", "/")
                    if normalized.startswith("presets/") and normalized.lower().endswith(".json"):
                        target = os.path.join(self.presets_dir, os.path.basename(normalized))
                        with zf.open(name) as src, open(target, "wb") as dst:
                            dst.write(src.read())
            self._refresh_preset_list()
            self._load_custom_themes()
            self.load_config(silent=True)
            self.log(f"Portable bundle imported: {path}")
            self._record_event("Portable import completed")
        except Exception as exc:
            messagebox.showerror("Import portable bundle failed", str(exc))

    def build_exe(self) -> None:
        cmd = [
            sys.executable,
            "-m",
            "PyInstaller",
            "--noconfirm",
            "--clean",
            "--onefile",
            "--windowed",
            "--name",
            "AFKScope",
            "--icon",
            "AFKSCOPE ICON.ico",
            "--add-data",
            "AFKSCOPE ICON.ico;.",
            "--add-data",
            "assets/afkscope-header-logo.png;assets",
            "--collect-binaries",
            "vgamepad",
            "--collect-data",
            "vgamepad",
            "--collect-submodules",
            "vgamepad",
            "main.py",
        ]

        def _worker() -> None:
            self.log("Build EXE started...")
            try:
                result = subprocess.run(cmd, cwd=os.getcwd(), capture_output=True, text=True, timeout=600)
                if result.returncode == 0:
                    self.log("Build EXE complete: dist/AFKScope.exe")
                else:
                    self.log("Build EXE failed. Run in terminal to inspect output.")
            except Exception as exc:
                self.log(f"Build EXE failed: {exc}")

        threading.Thread(target=_worker, daemon=True).start()

    def _make_tray_image(self):
        if Image is None or ImageDraw is None:
            return None
        image = Image.new("RGB", (64, 64), (32, 46, 64))
        draw = ImageDraw.Draw(image)
        draw.rectangle((10, 10, 54, 54), fill=(79, 195, 247))
        draw.rectangle((18, 18, 46, 46), fill=(255, 255, 255))
        return image

    def minimize_to_tray(self) -> None:
        if pystray is None:
            self.log(f"Tray mode unavailable ({tray_import_error}). Install pystray + pillow.")
            return
        if self.tray_icon is not None:
            return

        self.tray_enabled = True
        self.root.withdraw()

        def _show() -> None:
            self.root.after(0, self.restore_from_tray)

        def _quit() -> None:
            self.root.after(0, self.on_close)

        menu = pystray.Menu(
            pystray.MenuItem("Show", lambda _icon, _item: _show()),
            pystray.MenuItem("Start", lambda _icon, _item: self.root.after(0, self.start)),
            pystray.MenuItem("Stop", lambda _icon, _item: self.root.after(0, self.stop)),
            pystray.MenuItem("Quit", lambda _icon, _item: _quit()),
        )
        self.tray_icon = pystray.Icon("AFKScope", self._make_tray_image(), "AFKScope", menu)
        threading.Thread(target=self.tray_icon.run, daemon=True).start()
        self.log("Minimized to tray.")

    def restore_from_tray(self) -> None:
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()
        if self.tray_icon is not None:
            self.tray_icon.stop()
            self.tray_icon = None
        self.tray_enabled = False
        self.log("Restored from tray.")

    def on_close(self) -> None:
        self.stop()
        self._write_recovery_snapshot(force=True)
        self.save_config()
        self._unregister_global_hotkeys()
        self._clear_recovery_state_marker()
        if self.tray_icon is not None:
            self.tray_icon.stop()
            self.tray_icon = None
        self.root.destroy()


def main() -> None:
    root = tk.Tk()
    app = AntiAfkApp(root)
    app.log("Ready. Configure instances and press Start.")
    root.mainloop()


if __name__ == "__main__":
    main()


