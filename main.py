import base64
import csv
import ctypes
import json
import math
import os
import re
import subprocess
import sys
import threading
import time
import tkinter as tk
import zipfile
from ctypes import wintypes
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Any, cast
from urllib import error as urlerror
from urllib import request as urlrequest

try:
    import vgamepad as vg
    vg_import_error: Exception | None = None
except Exception as exc:
    vg = None
    vg_import_error = exc

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


class AntiAfkApp:
    @staticmethod
    def _resource_path(relative_name: str) -> str:
        base_path = getattr(sys, "_MEIPASS", os.getcwd())
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

        self.is_running = False
        self.gamepad: Any | None = None
        self.config_path = os.path.join(os.getcwd(), "afkscope_config.json")
        self.presets_dir = os.path.join(os.getcwd(), "presets")

        self.interval_var = tk.StringVar(value="5")
        self.status_var = tk.StringVar(value="Idle")
        self.stats_var = tk.StringVar(value="Runtime 00:00:00 | Cycles 0 | Jumps 0 | Errors 0")
        self.auto_realign_var = tk.BooleanVar(value=False)
        self.jump_mode_var = tk.StringVar(value="all")
        self.dark_mode_var = tk.BooleanVar(value=False)

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

        self.tray_icon = None
        self.tray_enabled = False

        self.theme_animating = False
        self.theme_animation_after_id: str | None = None
        self.current_theme_t = 0.0
        self.palette_light = {
            "bg": "#f2f2f2",
            "panel": "#f8f8f8",
            "field": "#ffffff",
            "text": "#111111",
            "muted": "#4d4d4d",
            "accent": "#2f6feb",
            "tree_sel": "#2f6feb",
            "tree_selfg": "#ffffff",
        }
        self.palette_dark = {
            "bg": "#171a1f",
            "panel": "#1f2430",
            "field": "#232a36",
            "text": "#e7ecf3",
            "muted": "#aeb8c8",
            "accent": "#7cb0ff",
            "tree_sel": "#355a93",
            "tree_selfg": "#ffffff",
        }

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
        self._update_theme_toggle_icon()
        self._apply_theme(self.palette_light)
        self._render_biome_badge()
        os.makedirs(self.presets_dir, exist_ok=True)
        self._refresh_preset_list()
        self.load_config(silent=True)
        self.refresh_instance_list(manual=False)
        self.run_diagnostics_checks()
        self._schedule_stats_update()
        self._schedule_instance_poll()

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
        self.theme_toggle_btn = ttk.Button(
            header,
            text="\u2600",
            width=3,
            command=self.toggle_dark_mode_button,
        )
        self.theme_toggle_btn.pack(side=tk.RIGHT, anchor="ne")
        ttk.Label(header, text="AFKScope", font=("Segoe UI", 12, "bold")).pack(anchor="center")
        ttk.Label(
            header,
            text="ViGEm focus spoofing macro with identity mapping, watchdog, and export tools",
        ).pack(anchor="center", pady=(2, 0))

        controls_group = ttk.LabelFrame(container, text="Main Controls", padding=10)
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

        options_group = ttk.LabelFrame(container, text="Automation Options", padding=10)
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

        history_group = ttk.LabelFrame(container, text="Biome Alert History", padding=8)
        history_group.pack(fill="x", pady=(8, 0))
        self.biome_history_list = tk.Listbox(history_group, height=4)
        self.biome_history_list.pack(fill="x")

        target_group = ttk.LabelFrame(container, text="Per Instance Controls", padding=10)
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

        status_frame = ttk.LabelFrame(container, text="Session Stats", padding=10)
        status_frame.pack(fill="x", pady=(8, 0))
        ttk.Label(status_frame, textvariable=self.stats_var).pack(anchor="w")

        health_group = ttk.LabelFrame(container, text="Instance Health Panel", padding=10)
        health_group.pack(fill="x", pady=(8, 0))
        self.health_text = tk.Text(health_group, height=4, font=("Consolas", 9), state=tk.DISABLED)
        self.health_text.pack(fill="x")

        diag_group = ttk.LabelFrame(container, text="Diagnostics", padding=10)
        diag_group.pack(fill="x", pady=(8, 0))
        diag_row = ttk.Frame(diag_group)
        diag_row.pack(fill="x", pady=(0, 6))
        ttk.Button(diag_row, text="Run Checks", width=12, command=self.run_diagnostics_checks).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(diag_row, text="Export Debug Bundle", width=18, command=self.export_debug_bundle).pack(side=tk.LEFT)
        self.diagnostics_text = tk.Text(diag_group, height=5, font=("Consolas", 9), state=tk.DISABLED)
        self.diagnostics_text.pack(fill="x")

        status_row = ttk.Frame(container)
        status_row.pack(fill="x", pady=(8, 4))
        ttk.Label(status_row, text="Status:").pack(side=tk.LEFT)
        ttk.Label(status_row, textvariable=self.status_var).pack(side=tk.LEFT, padx=(6, 0))

        log_group = ttk.LabelFrame(container, text="Log", padding=6)
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

    def _mix(self, a: str, b: str, t: float) -> str:
        ar, ag, ab = self._hex_to_rgb(a)
        br, bg, bb = self._hex_to_rgb(b)
        rr = int(ar + (br - ar) * t)
        rg = int(ag + (bg - ag) * t)
        rb = int(ab + (bb - ab) * t)
        return self._rgb_to_hex((rr, rg, rb))

    def _theme_at(self, t: float) -> dict[str, str]:
        return {
            key: self._mix(self.palette_light[key], self.palette_dark[key], t)
            for key in self.palette_light
        }

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
        if hasattr(self, "biome_badge"):
            self.biome_badge.configure(
                highlightbackground=palette["panel"],
                highlightcolor=palette["accent"],
            )
            self._render_biome_badge()

    def _animate_theme_to(self, target_t: float, duration_ms: int = 280, steps: int = 14) -> None:
        if self.theme_animation_after_id:
            self.root.after_cancel(self.theme_animation_after_id)
            self.theme_animation_after_id = None

        start_t = self.current_theme_t
        delta = target_t - start_t
        if abs(delta) < 0.001:
            self.current_theme_t = target_t
            self._apply_theme(self._theme_at(self.current_theme_t))
            return

        self.theme_animating = True
        step_delay = max(10, duration_ms // steps)

        def _tick(i: int) -> None:
            progress = i / steps
            self.current_theme_t = start_t + delta * progress
            self._apply_theme(self._theme_at(self.current_theme_t))
            if i < steps:
                self.theme_animation_after_id = self.root.after(step_delay, _tick, i + 1)
            else:
                self.theme_animating = False
                self.theme_animation_after_id = None

        _tick(0)

    def _update_theme_toggle_icon(self) -> None:
        if hasattr(self, "theme_toggle_btn"):
            self.theme_toggle_btn.configure(text="\u263e" if self.dark_mode_var.get() else "\u2600")

    def toggle_dark_mode(self) -> None:
        target = 1.0 if self.dark_mode_var.get() else 0.0
        self._update_theme_toggle_icon()
        self._animate_theme_to(target)

    def toggle_dark_mode_button(self) -> None:
        self.dark_mode_var.set(not self.dark_mode_var.get())
        self.toggle_dark_mode()

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
            color = self._theme_at(self.current_theme_t)["field"]
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
                headers={"Content-Type": "application/json", "User-Agent": "AFKScope/1.0"},
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

    def ensure_gamepad(self) -> None:
        if vg is None:
            extra = f" ({vg_import_error})" if vg_import_error else ""
            raise RuntimeError(
                "vgamepad/ViGEmClient failed to load. Reinstall ViGEmBus and rebuild with collected binaries"
                + extra
            )
        vg_module = cast(Any, vg)
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
        headers = {"User-Agent": "AFKScope/1.0"}
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
        req = urlrequest.Request(image_url, headers={"User-Agent": "AFKScope/1.0"})
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
            start_str = self.pause_start_var.get().strip()
            end_str = self.pause_end_var.get().strip()
            start_hour, start_min = [int(x) for x in start_str.split(":")]
            end_hour, end_min = [int(x) for x in end_str.split(":")]
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

    def jump_once(self) -> bool:
        if self._is_in_pause_window():
            with self.metrics_lock:
                self.session_cycles += 1
            return False

        self.ensure_gamepad()
        vg_module = cast(Any, vg)
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

        gamepad.left_joystick(2000, 0)
        gamepad.update()
        time.sleep(0.05)
        gamepad.left_joystick(0, 0)
        gamepad.update()
        time.sleep(0.03)

        jump_button = vg_module.XUSB_BUTTON.XUSB_GAMEPAD_A
        gamepad.press_button(jump_button)
        gamepad.update()
        time.sleep(0.12)
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
        self._send_webhook("AFKScope", "Anti-AFK loop started.")
        threshold = self.parse_watchdog_threshold() if self.watchdog_enabled_var.get() else 999999

        while not self.stop_event.is_set():
            try:
                sent = self.jump_once()
                if sent:
                    self.failed_cycles = 0
                    self.log("Sent virtual jump (A) to enabled spoofed instances.")
                else:
                    self.failed_cycles += 1
                    self.log("No enabled Roblox windows found or cycle paused.")

                if self.watchdog_enabled_var.get() and self.failed_cycles >= threshold:
                    self._reset_gamepad_session()
                    self.failed_cycles = 0
            except Exception as exc:  # pragma: no cover
                self.failed_cycles += 1
                with self.metrics_lock:
                    self.session_errors += 1
                self.log(f"Error while sending jump: {exc}")
                self._send_webhook("AFKScope Error", f"Jump loop error: {exc}")
                self.root.after(0, self.stop)
                return

            if self.stop_event.wait(interval):
                break

        self.log("Anti-AFK loop stopped.")
        self._send_webhook("AFKScope", "Anti-AFK loop stopped.")

    def start(self) -> None:
        if self.is_running:
            return

        try:
            interval = self.parse_interval()
            self.parse_watchdog_threshold()
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

    def stop(self) -> None:
        self.stop_event.set()
        if self.worker_thread and self.worker_thread.is_alive():
            self.worker_thread.join(timeout=0.5)
        self.set_running_ui(False)

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
        self.root.after(2500, self._schedule_instance_poll)

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
            "dark_mode": bool(self.dark_mode_var.get()),
            "biome_alerts_enabled": bool(self.biome_alerts_enabled_var.get()),
            "rare_biome": self.rare_biome_var.get().strip().upper(),
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
        self.dark_mode_var.set(bool(data.get("dark_mode", False)))
        self.biome_alerts_enabled_var.set(bool(data.get("biome_alerts_enabled", False)))
        self.rare_biome_var.set(str(data.get("rare_biome", "GLITCHED")).strip().upper() or "GLITCHED")
        self.current_theme_t = 1.0 if self.dark_mode_var.get() else 0.0
        self._update_theme_toggle_icon()
        self._apply_theme(self._theme_at(self.current_theme_t))
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
        checks = [
            f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"vgamepad import: {'OK' if vg is not None else f'FAIL ({vg_import_error})'}",
            f"Gamepad session: {'READY' if self.gamepad is not None else 'NOT INITIALIZED'}",
            f"Roblox windows detected: {len(windows)}",
            f"Biome log source: {latest_log}",
            f"Current biome: {self.current_biome_name} ({self.current_biome_source})",
            f"Webhook configured: {'YES' if webhook_on else 'NO'}",
            f"Rare biome alerts: {'ON' if self.biome_alerts_enabled_var.get() else 'OFF'} ({self.rare_biome_var.get().strip().upper() or 'GLITCHED'})",
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
        self.save_config()
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


