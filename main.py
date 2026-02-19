import base64
import csv
import ctypes
import json
import hashlib
import math
import os
import queue
import random
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import tkinter as tk
import webbrowser
import zipfile
from ctypes import wintypes
from datetime import datetime, timezone
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

APP_VERSION = "0.1.6"
APP_CONFIG_VERSION = 1
APP_NAME = "StayActive"
APP_USER_AGENT = f"{APP_NAME}/{APP_VERSION}"
APP_ICON_ICO = "STAYACTIVE ICON.ico"
APP_ICON_PNG = "STAYACTIVE ICON.png"
THEME_COLOR_KEYS = ("bg", "panel", "field", "text", "muted", "accent", "tree_sel", "tree_selfg")
WM_HOTKEY = 0x0312
PM_REMOVE = 0x0001
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
DELETE_ACCESS = 0x00010000
EVENT_MODIFY_STATE = 0x0002
EVENT_ALL_ACCESS = 0x1F0003
SYNCHRONIZE = 0x00100000
ERROR_FILE_NOT_FOUND = 2
ERROR_ACCESS_DENIED = 5
PROCESS_DUP_HANDLE = 0x0040
PROCESS_SUSPEND_RESUME = 0x0800
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
DUPLICATE_CLOSE_SOURCE = 0x00000001
DUPLICATE_SAME_ACCESS = 0x00000002
TOKEN_QUERY = 0x0008
TOKEN_ADJUST_PRIVILEGES = 0x0020
SE_PRIVILEGE_ENABLED = 0x00000002
ERROR_NOT_ALL_ASSIGNED = 1300
SYSTEM_EXTENDED_HANDLE_INFORMATION_CLASS = 64
SYSTEM_HANDLE_INFORMATION_CLASS = 16
OBJECT_NAME_INFORMATION_CLASS = 1
OBJECT_TYPE_INFORMATION_CLASS = 2
STATUS_SUCCESS = 0
STATUS_INFO_LENGTH_MISMATCH = 0xC0000004
STATUS_BUFFER_OVERFLOW = 0x80000005
STATUS_BUFFER_TOO_SMALL = 0xC0000023
TH32CS_SNAPPROCESS = 0x00000002
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value


class _UNICODE_STRING(ctypes.Structure):
    _fields_ = [
        ("Length", wintypes.USHORT),
        ("MaximumLength", wintypes.USHORT),
        ("Buffer", wintypes.LPWSTR),
    ]


class _LUID(ctypes.Structure):
    _fields_ = [("LowPart", wintypes.DWORD), ("HighPart", wintypes.LONG)]


class _LUID_AND_ATTRIBUTES(ctypes.Structure):
    _fields_ = [("Luid", _LUID), ("Attributes", wintypes.DWORD)]


class _TOKEN_PRIVILEGES(ctypes.Structure):
    _fields_ = [("PrivilegeCount", wintypes.DWORD), ("Privileges", _LUID_AND_ATTRIBUTES * 1)]


class _PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.c_size_t),
        ("th32ModuleID", wintypes.DWORD),
        ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase", wintypes.LONG),
        ("dwFlags", wintypes.DWORD),
        ("szExeFile", wintypes.WCHAR * 260),
    ]


class _LASTINPUTINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.UINT),
        ("dwTime", wintypes.DWORD),
    ]


class AntiAfkApp:
    @staticmethod
    def _resource_path(relative_name: str) -> str:
        if hasattr(sys, "_MEIPASS"):
            base_path = getattr(sys, "_MEIPASS")
        else:
            base_path = os.path.dirname(os.path.abspath(__file__))
        return os.path.join(base_path, relative_name)

    @staticmethod
    def _app_data_dir() -> str:
        local = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
        if local:
            return os.path.join(local, APP_NAME)
        return os.path.join(os.path.expanduser("~"), f".{APP_NAME.lower()}")

    def _migrate_legacy_runtime_files(self) -> None:
        legacy_base = os.getcwd()
        try:
            if os.path.samefile(legacy_base, self.data_dir):
                return
        except Exception:
            pass
        os.makedirs(self.data_dir, exist_ok=True)
        file_names = (
            "stayactive_config.json",
            "stayactive_themes.json",
            "stayactive_recovery_state.json",
            "stayactive_recovery_snapshot.json",
        )
        for name in file_names:
            src = os.path.join(legacy_base, name)
            dst = os.path.join(self.data_dir, name)
            if not os.path.exists(src) or os.path.exists(dst):
                continue
            try:
                shutil.move(src, dst)
            except Exception as exc:
                self.startup_warnings.append(f"Startup migration skipped '{name}': {exc}")
        legacy_presets = os.path.join(legacy_base, "presets")
        if os.path.isdir(legacy_presets) and not os.path.exists(self.presets_dir):
            try:
                shutil.move(legacy_presets, self.presets_dir)
            except Exception as exc:
                self.startup_warnings.append(f"Startup migration skipped 'presets': {exc}")

    @staticmethod
    def _current_process_pseudo_handle() -> wintypes.HANDLE:
        # Stable pseudo-handle for current process across ctypes call boundaries.
        return wintypes.HANDLE(-1)

    @staticmethod
    def _ntstatus_unsigned(status: int) -> int:
        return ctypes.c_ulong(status).value

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title(f"{APP_NAME} - Sol's RNG Anti AFK")
        self.window_default_width = 1220
        self.window_default_height = 940
        self.window_min_width = 1100
        self.window_min_height = 820
        self.root.geometry(f"{self.window_default_width}x{self.window_default_height}")
        self.root.minsize(self.window_min_width, self.window_min_height)
        self.root.resizable(True, True)
        try:
            icon_path = self._resource_path(APP_ICON_ICO)
            if os.path.exists(icon_path):
                self.root.iconbitmap(icon_path)
        except Exception:
            pass

        self.user32 = ctypes.WinDLL("user32", use_last_error=True)
        self.kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self.ntdll = ctypes.WinDLL("ntdll", use_last_error=True)
        self.advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)

        self.worker_thread: threading.Thread | None = None
        self.stop_event = threading.Event()
        self.metrics_lock = threading.Lock()
        self.state_lock = threading.RLock()
        self.ui_dispatch_queue: queue.Queue[tuple[Callable[..., None], tuple[Any, ...]]] = queue.Queue()
        self.header_logo_photo: tk.PhotoImage | None = None
        self.header_logo_label: tk.Label | None = None
        self.header_icon_photo: Any | None = None
        self.header_icon_badge: tk.Label | None = None
        self.header_title_label: tk.Label | None = None
        self.header_subtitle_label: tk.Label | None = None

        self.is_running = False
        self.gamepad: Any | None = None
        self.startup_warnings: list[str] = []
        self.nt_suspend_process: Any | None = getattr(self.ntdll, "NtSuspendProcess", None)
        self.nt_resume_process: Any | None = getattr(self.ntdll, "NtResumeProcess", None)
        if callable(self.nt_suspend_process):
            suspend_fn = cast(Any, self.nt_suspend_process)
            suspend_fn.argtypes = [wintypes.HANDLE]
            suspend_fn.restype = ctypes.c_long
        if callable(self.nt_resume_process):
            resume_fn = cast(Any, self.nt_resume_process)
            resume_fn.argtypes = [wintypes.HANDLE]
            resume_fn.restype = ctypes.c_long
        self.process_limiter_supported = callable(self.nt_suspend_process) and callable(self.nt_resume_process)
        if not self.process_limiter_supported:
            self.startup_warnings.append("Process limiter unavailable on this Windows runtime.")
        self.data_dir = self._app_data_dir()
        self.config_path = os.path.join(self.data_dir, "stayactive_config.json")
        self.theme_config_path = os.path.join(self.data_dir, "stayactive_themes.json")
        self.recovery_state_path = os.path.join(self.data_dir, "stayactive_recovery_state.json")
        self.recovery_snapshot_path = os.path.join(self.data_dir, "stayactive_recovery_snapshot.json")
        self.presets_dir = os.path.join(self.data_dir, "presets")
        self._migrate_legacy_runtime_files()
        self.should_offer_setup_wizard = not os.path.exists(self.config_path)

        self.interval_var = tk.StringVar(value="5")
        self.status_var = tk.StringVar(value="Idle")
        self.stats_var = tk.StringVar(value="Runtime 00:00:00 | Cycles 0 | Jumps 0 | Errors 0")
        self.auto_realign_var = tk.BooleanVar(value=False)
        self.jump_mode_var = tk.StringVar(value="all")
        self.theme_name_var = tk.StringVar(value="Midnight")
        self.anti_idle_pattern_var = tk.StringVar(value="balanced")
        self.hotkeys_enabled_var = tk.BooleanVar(value=True)
        self.hotkey_guard_var = tk.BooleanVar(value=True)
        self.health_alert_enabled_var = tk.BooleanVar(value=True)
        self.health_alert_minutes_var = tk.StringVar(value="3")
        self.autosave_enabled_var = tk.BooleanVar(value=True)
        self.autosave_minutes_var = tk.StringVar(value="2")
        self.start_when_windows_found_var = tk.BooleanVar(value=True)
        self.safe_mode_var = tk.BooleanVar(value=False)
        self.manual_pause_minutes_var = tk.StringVar(value="10")
        self.profile_hotkey_1_var = tk.StringVar(value="default")
        self.profile_hotkey_2_var = tk.StringVar(value="farming")
        self.profile_hotkey_3_var = tk.StringVar(value="overnight")
        self.startup_restore_enabled_var = tk.BooleanVar(value=False)
        self.startup_preset_var = tk.StringVar(value="default")
        self.startup_auto_start_var = tk.BooleanVar(value=False)
        self.startup_auto_align_var = tk.BooleanVar(value=False)
        self.event_filter_var = tk.StringVar(value="all")
        self.scheduler_enabled_var = tk.BooleanVar(value=False)
        self.scheduler_slot1_time_var = tk.StringVar(value="08:00")
        self.scheduler_slot1_preset_var = tk.StringVar(value="day")
        self.scheduler_slot2_time_var = tk.StringVar(value="23:30")
        self.scheduler_slot2_preset_var = tk.StringVar(value="overnight")
        self.update_banner_var = tk.StringVar(value="Checking for updates...")
        self.latest_release_tag_var = tk.StringVar(value="Latest: -")
        self.process_limiter_enabled_var = tk.BooleanVar(value=False)
        self.process_limiter_auto_mode_var = tk.BooleanVar(value=False)
        self.process_limiter_only_when_running_var = tk.BooleanVar(value=True)
        self.process_limiter_target_percent_var = tk.StringVar(value="40")
        self.process_limiter_cycle_ms_var = tk.StringVar(value="180")
        self.process_limiter_status_var = tk.StringVar(value="Limiter idle.")
        self.instance_relaunch_enabled_var = tk.BooleanVar(value=False)
        self.instance_relaunch_grace_seconds_var = tk.StringVar(value="45")
        self.instance_relaunch_max_per_hour_var = tk.StringVar(value="8")
        self.instance_relaunch_launch_target_var = tk.StringVar(value="")
        self.instance_relaunch_status_var = tk.StringVar(value="Relaunch idle.")
        self.account_roster_enabled_var = tk.BooleanVar(value=False)
        self.account_roster_status_var = tk.StringVar(value="Roster OFF (0 locked)")
        self.watchdog_standby_mode_var = tk.BooleanVar(value=False)
        self.private_server_place_id_var = tk.StringVar(value="")
        self.private_server_code_var = tk.StringVar(value="")

        self.pause_enabled_var = tk.BooleanVar(value=False)
        self.pause_start_var = tk.StringVar(value="02:00")
        self.pause_end_var = tk.StringVar(value="06:00")

        self.webhook_enabled_var = tk.BooleanVar(value=False)
        self.webhook_url_var = tk.StringVar(value="")
        self.webhook_biome_url_var = tk.StringVar(value="")
        self.webhook_recovery_url_var = tk.StringVar(value="")
        self.webhook_health_url_var = tk.StringVar(value="")
        self.webhook_vendor_url_var = tk.StringVar(value="")
        self.max_log_lines = 2000
        self.recent_log_lines: list[str] = []
        self.runtime_watchdog_enabled = True
        self.runtime_no_window_threshold = 24
        self.runtime_jump_fail_threshold = 8
        self.runtime_start_when_windows_found = True
        self.runtime_recovery_enabled = True
        self.runtime_jump_mode = "all"
        self.runtime_safe_mode = False
        self.runtime_anti_idle_pattern = "balanced"
        self.runtime_pause_enabled = False
        self.runtime_pause_start = "02:00"
        self.runtime_pause_end = "06:00"
        self.runtime_process_limiter_enabled = False
        self.runtime_process_limiter_auto_mode = False
        self.runtime_process_limiter_only_when_running = True
        self.runtime_process_limiter_target_percent = 40
        self.runtime_process_limiter_cycle_ms = 180
        self.runtime_instance_relaunch_enabled = False
        self.runtime_instance_relaunch_grace_seconds = 45
        self.runtime_instance_relaunch_max_per_hour = 8
        self.runtime_instance_relaunch_launch_target = ""
        self.runtime_account_roster_enabled = False
        self.runtime_watchdog_standby_mode = False

        self.watchdog_enabled_var = tk.BooleanVar(value=True)
        self.watchdog_threshold_var = tk.StringVar(value="12")
        self.watchdog_no_windows_threshold_var = tk.StringVar(value="24")
        self.watchdog_jump_fail_threshold_var = tk.StringVar(value="8")
        self.preset_name_var = tk.StringVar(value="default")
        self.biome_alerts_enabled_var = tk.BooleanVar(value=False)
        self.rare_biome_var = tk.StringVar(value="GLITCHED")
        self.biome_action_var = tk.StringVar(value="webhook")
        self.biome_action_preset_var = tk.StringVar(value="default")
        self.rare_biome_confirm_enabled_var = tk.BooleanVar(value=True)
        self.rare_biome_confirm_seconds_var = tk.StringVar(value="4")
        self.vendor_alerts_enabled_var = tk.BooleanVar(value=False)
        self.vendor_alert_cooldown_var = tk.StringVar(value="180")
        self.recovery_enabled_var = tk.BooleanVar(value=True)
        self.latest_release_url = "https://github.com/0bl1terate3/StayActive/releases/latest"

        self.window_map: list[tuple[int, str, int, str]] = []
        self._process_name_cache: dict[int, str] = {}
        self.instance_enabled_by_hwnd: dict[int, bool] = {}
        self.loaded_enabled_by_pid: dict[int, bool] = {}
        self.instance_last_jump: dict[int, float] = {}
        self.instance_interval_override: dict[int, float] = {}
        self.instance_pattern_override: dict[int, str] = {}
        self.instance_priority_by_pid: dict[int, int] = {}
        self.instance_fail_count: dict[int, int] = {}
        self.instance_attempt_count: dict[int, int] = {}
        self.instance_quarantine_until: dict[int, float] = {}
        self.instance_send_fail_streak: dict[int, int] = {}
        self.instance_recovery_tier_by_hwnd: dict[int, int] = {}
        self.instance_recovery_last_log_at: dict[int, float] = {}
        self.instance_recovery_tier1_threshold = 2
        self.instance_recovery_tier2_threshold = 4
        self.instance_recovery_tier3_threshold = 6
        self.instance_recovery_tier1_backoff_seconds = 6
        self.instance_recovery_tier2_backoff_seconds = 18
        self.instance_recovery_tier3_backoff_seconds = 90
        self.instance_quarantine_fail_threshold = 6
        self.instance_quarantine_seconds = 180
        self.enabled_by_username: dict[str, bool] = {}
        self.override_by_username: dict[str, dict[str, Any]] = {}
        self.process_limiter_boost_until_by_pid: dict[int, float] = {}
        self.process_limiter_suspended_pids: set[int] = set()
        self.process_limiter_suspend_count = 0
        self.process_limiter_resume_count = 0
        self.process_limiter_last_error = ""
        self.process_limiter_last_error_at = 0.0
        self.instance_relaunch_target_count = 0
        self.instance_relaunch_drop_since: float | None = None
        self.instance_relaunch_last_attempt_at = 0.0
        self.instance_relaunch_wait_until = 0.0
        self.instance_relaunch_attempt_timestamps: list[float] = []
        self.instance_relaunch_min_interval_seconds = 20.0
        self.instance_relaunch_launcher_cache_path = ""
        self.instance_relaunch_launcher_cache_at = 0.0
        self.instance_relaunch_last_log_at = 0.0
        self.account_roster_user_ids: set[int] = set()
        self.account_roster_names_by_user_id: dict[int, str] = {}
        self.account_roster_missing_since_by_user_id: dict[int, float] = {}
        self.instance_relaunch_recovered_logged = False

        self.pid_username: dict[int, str] = {}
        self.pid_user_id: dict[int, int] = {}
        self.pid_log_hint: dict[int, str] = {}
        self.pid_equipped_aura: dict[int, str] = {}
        self.pid_aura_seen_at: dict[int, float] = {}
        self.pid_aura_log_path: dict[int, str] = {}
        self.pid_aura_log_offset: dict[int, int] = {}
        self.pid_aura_log_discovery_last_attempt: dict[int, float] = {}
        self.last_aura_poll_at = 0.0
        self.aura_poll_interval_seconds = 3.5
        self.aura_log_discovery_interval_seconds = 12.0
        self.aura_log_read_bytes = 220_000
        self.aura_stale_after_seconds = 300.0
        self.jump_send_retry_enabled = True
        self.jump_send_retry_delay_seconds = 0.16
        self.pid_create_time_cache: dict[int, float] = {}
        self.pid_avatar_photo: dict[int, tk.PhotoImage] = {}
        self.pid_identity_confidence: dict[int, str] = {}
        self.identity_lookup_inflight: set[int] = set()
        self.identity_last_attempt: dict[int, float] = {}
        self.identity_conflict_last_log_at = 0.0
        self.singleton_cleanup_last_attempt_by_pid: dict[int, float] = {}
        self.singleton_cleanup_attempt_count_by_pid: dict[int, int] = {}
        self.singleton_cleanup_attempt_interval_seconds = 20.0
        self.singleton_cleanup_max_attempts_per_pid = 4
        self.singleton_cleanup_last_outcome_by_pid: dict[int, str] = {}
        self.singleton_cleanup_pending_pids: set[int] = set()
        self.singleton_cleanup_inflight = False
        self.debug_privilege_checked = False
        self.debug_privilege_enabled = False
        self.debug_privilege_last_error: int = 0
        self.debug_privilege_last_stage: str = ""
        self.singleton_scan_last_entries = 0
        self.singleton_scan_last_open_process_ok = 0
        self.singleton_scan_last_open_process_fail = 0

        self.layout_cache: dict[int, tuple[int, int, int, int, int]] = {}
        self.last_window_count = -1
        self.last_instance_scan_at = 0.0
        self.runtime_scan_cache_ttl_seconds = 1.25
        self.last_health_ui_update_at = 0.0
        self.health_ui_update_interval_seconds = 1.0

        self.session_started_at: float | None = None
        self.session_cycles = 0
        self.session_jumps = 0
        self.session_errors = 0

        self.failed_cycles = 0
        self.no_window_cycles = 0
        self.jump_fail_cycles = 0
        self.round_robin_index = 0
        self.last_instance_health_alert: dict[int, float] = {}
        self.last_autosave_at = 0.0
        self.recovery_prompt_needed = self._detect_unclean_shutdown()
        self.quick_setup_window: tk.Toplevel | None = None
        self.waiting_for_windows = False
        self.pause_override_until: float | None = None
        self.last_not_due_log_at = 0.0
        self.roblox_input_pause_enabled = True
        self.roblox_input_pause_seconds = 2.0
        self.roblox_input_pause_until_by_hwnd: dict[int, float] = {}
        self.roblox_input_pause_logged_hwnds: set[int] = set()
        self.last_system_input_tick = 0
        self.scheduler_last_applied_key: str | None = None
        self.latest_release_asset_url = ""
        self.latest_release_asset_name = ""
        self.reports_dir = os.path.join(self.data_dir, "reports")
        self.runtime_log_path = os.path.join(self.reports_dir, "runtime.log")
        self.runtime_log_max_bytes = 2_000_000
        self.runtime_log_lock = threading.Lock()
        self.hotkey_help_window: tk.Toplevel | None = None
        self.last_normal_geometry = f"{self.window_default_width}x{self.window_default_height}"
        self.last_window_restore_log_at = 0.0
        self.last_ui_poll_error_at = 0.0
        self.last_iconic_heavy_poll_at = 0.0

        self.tray_icon = None
        self.tray_enabled = False
        self.hotkey_actions: dict[int, tuple[str, Callable[[], None]]] = {}
        self.global_hotkeys_registered = False
        self.hotkey_guard_last_block_at = 0.0
        self.webhook_queue: queue.Queue[tuple[str, str, str, int]] = queue.Queue()
        self.webhook_worker_running = False
        self.process_limiter_thread: threading.Thread | None = None
        self.process_limiter_stop_event = threading.Event()

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
        self.instance_override_seconds_var: tk.StringVar | None = None
        self.instance_override_pattern_var: tk.StringVar | None = None
        self.instance_priority_var: tk.StringVar | None = None

        self.username_patterns = [
            # MultiScope-style signal from Roblox logs; usually the cleanest identity marker.
            re.compile(r"Players\.([A-Za-z0-9_]{3,20})\.PlayerGui", re.IGNORECASE),
            re.compile(r"Player added:\s+([A-Za-z0-9_]{3,20})\s+\d+", re.IGNORECASE),
        ]
        self.user_id_patterns = (
            re.compile(r"\buserid:(\d+)\b", re.IGNORECASE),
            re.compile(r"\buser:(\d+)\b", re.IGNORECASE),
        )
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
            "telemetryreliability",
            "key",
            "value",
            "event",
            "state",
            "data",
            "result",
            "payload",
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
        self.recovery_timeline: list[str] = []
        self.biome_alert_cooldown_seconds = 45
        self.last_biome_alert_at: dict[str, float] = {}
        self.last_vendor_alert_at: dict[str, float] = {}
        self.pending_rare_biome_name = ""
        self.pending_rare_biome_since = 0.0
        self.rare_biome_alerted_state = ""
        self.runtime_vendor_alerts_enabled = False
        self.runtime_vendor_alert_cooldown = 180
        self.runtime_rare_biome_confirm_enabled = True
        self.runtime_rare_biome_confirm_seconds = 4.0

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
        self._vendor_line_patterns: list[tuple[str, re.Pattern[str]]] = [
            (
                "JESTER",
                re.compile(
                    r"\b(jester)\b.*\b(arrived|appeared|spawned|is\s+here|has\s+arrived)\b",
                    re.IGNORECASE,
                ),
            ),
            (
                "JESTER",
                re.compile(
                    r"\b(arrived|appeared|spawned)\b.*\b(jester)\b",
                    re.IGNORECASE,
                ),
            ),
            (
                "MERCHANT",
                re.compile(
                    r"\b(merchant|travel(?:l)?ing\s+merchant)\b.*\b(arrived|appeared|spawned|is\s+here|has\s+arrived)\b",
                    re.IGNORECASE,
                ),
            ),
            (
                "MERCHANT",
                re.compile(
                    r"\b(arrived|appeared|spawned)\b.*\b(merchant|travel(?:l)?ing\s+merchant)\b",
                    re.IGNORECASE,
                ),
            ),
        ]

        self._build_ui()
        self._load_custom_themes()
        self._apply_selected_theme()
        self._render_biome_badge()
        os.makedirs(self.presets_dir, exist_ok=True)
        os.makedirs(self.reports_dir, exist_ok=True)
        self._refresh_preset_list()
        self.load_config(silent=True)
        self._write_recovery_state_marker()
        self._install_exception_hooks()
        self._ensure_window_visible()
        self.root.bind("<Configure>", self._on_root_configure, add="+")
        self.root.after(25, self._drain_ui_dispatch_queue)
        self.root.after(50, self._finish_startup)

    def _ensure_window_visible(self) -> None:
        # Force the main window to appear in front if Windows restores it hidden/off-screen.
        try:
            self._repair_main_window_if_needed(force=True, reason="startup")
            self.root.attributes("-topmost", True)
            self.root.after(250, lambda: self.root.attributes("-topmost", False))
        except Exception:
            pass

    @staticmethod
    def _parse_geometry_size(geometry: str) -> tuple[int, int] | None:
        match = re.match(r"^\s*(\d+)x(\d+)", geometry)
        if not match:
            return None
        try:
            return int(match.group(1)), int(match.group(2))
        except ValueError:
            return None

    def _on_root_configure(self, _event: tk.Event | None = None) -> None:
        if self.tray_enabled:
            return
        try:
            state = str(self.root.state())
        except Exception:
            return
        if state not in {"normal", "zoomed"}:
            return
        try:
            width = int(self.root.winfo_width())
            height = int(self.root.winfo_height())
        except Exception:
            return
        if width >= max(480, self.window_min_width // 2) and height >= max(280, self.window_min_height // 2):
            try:
                self.last_normal_geometry = self.root.geometry()
            except Exception:
                pass

    def _repair_main_window_if_needed(self, force: bool, reason: str) -> bool:
        if self.tray_enabled and not force:
            return False
        try:
            state = str(self.root.state())
        except Exception:
            return False
        if state == "withdrawn" and not force:
            return False
        if state == "iconic" and not force:
            return False

        try:
            self.root.update_idletasks()
            width = int(self.root.winfo_width())
            height = int(self.root.winfo_height())
        except Exception:
            width, height = 0, 0
        too_small = width < max(480, self.window_min_width // 2) or height < max(280, self.window_min_height // 2)
        if not force and not too_small:
            return False

        target_geometry = self.last_normal_geometry.strip() or f"{self.window_default_width}x{self.window_default_height}"
        parsed = self._parse_geometry_size(target_geometry)
        if parsed is None or parsed[0] < self.window_min_width or parsed[1] < self.window_min_height:
            target_geometry = f"{self.window_default_width}x{self.window_default_height}+60+60"
        try:
            self.root.state("normal")
            self.root.deiconify()
            self.root.geometry(target_geometry)
            self.root.minsize(self.window_min_width, self.window_min_height)
            self.root.update_idletasks()
            self.root.lift()
            self.root.focus_force()
            self.last_normal_geometry = self.root.geometry()
            now = time.time()
            if (now - self.last_window_restore_log_at) >= 6.0:
                self.last_window_restore_log_at = now
                self.log(f"Window layout auto-recovered ({reason}).")
            return True
        except Exception:
            return False

    def _finish_startup(self) -> None:
        # Defer startup work so the UI appears even if environment checks are slow.
        try:
            runtime_path = sys.executable if getattr(sys, "frozen", False) else os.path.abspath(__file__)
            self.log(f"Runtime binary: {runtime_path}")
            if sys.version_info >= (3, 14):
                self.log(
                    "Warning: Python 3.14 runtime detected. "
                    "Use Python 3.10 or the release EXE for best long-run UI stability."
                )
            self._sync_runtime_settings_from_ui()
            if self.startup_warnings:
                for warning in self.startup_warnings:
                    self.log(warning)
                self.startup_warnings.clear()
            debug_ok = self._ensure_debug_privilege()
            if debug_ok:
                self.log("SeDebugPrivilege enabled at startup.")
            else:
                self.log(
                    "SeDebugPrivilege unavailable at startup "
                    f"(run elevated; stage={self.debug_privilege_last_stage}, error={self.debug_privilege_last_error})."
                )
            self.refresh_instance_list(manual=False)
            self.run_diagnostics_checks()
            self._set_global_hotkeys_enabled(self.hotkeys_enabled_var.get(), log_result=False)
            self._ensure_process_limiter_worker()
            self._schedule_stats_update()
            self._schedule_instance_poll()
            self._schedule_recovery_autosave()
            self._apply_startup_restore()
            self.root.after(2200, self._start_background_update_check)
            if self.recovery_prompt_needed:
                self.log("Detected previous unclean shutdown state.")
                self.root.after(250, self._prompt_recovery_restore)
            if self.should_offer_setup_wizard:
                self.root.after(350, self.open_quick_setup_wizard)
        except Exception as exc:
            self.log(f"Startup checks failed: {exc}")

    def _apply_startup_restore(self) -> None:
        if not self.startup_restore_enabled_var.get():
            return
        preset_name = self._sanitize_preset_name(self.startup_preset_var.get().strip() or "default")
        path = self._preset_path(preset_name)
        if os.path.exists(path):
            self.preset_name_var.set(preset_name)
            self.load_preset()
        else:
            self.log(f"Startup restore preset not found: {preset_name}")
        if self.startup_auto_align_var.get():
            self.align_windows(log_result=False)
        if self.startup_auto_start_var.get():
            self.start()

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
                png_path = self._resource_path(APP_ICON_PNG)
                if not os.path.exists(png_path):
                    raise FileNotFoundError("No PNG icon resource available.")
                icon = tk.PhotoImage(file=png_path)
                if icon.width() > 40:
                    step = max(1, icon.width() // 40)
                    icon = cast(tk.PhotoImage, icon.subsample(step))
                self.header_icon_photo = icon
            except Exception:
                try:
                    from PIL import Image as PilImage
                    from PIL import ImageTk

                    icon_path = self._resource_path(APP_ICON_ICO)
                    if not os.path.exists(icon_path):
                        raise FileNotFoundError("No icon resource available.")
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
                text=APP_NAME,
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
        update_banner = ttk.Frame(header)
        update_banner.pack(fill="x", pady=(4, 0))
        ttk.Label(update_banner, textvariable=self.update_banner_var).pack(side=tk.LEFT)
        ttk.Label(update_banner, textvariable=self.latest_release_tag_var).pack(side=tk.LEFT, padx=(10, 0))
        ttk.Button(update_banner, text="Download Latest", command=self.download_latest_release_asset).pack(
            side=tk.RIGHT
        )

        notebook = ttk.Notebook(container)
        notebook.pack(fill="both", expand=True)

        tab_control = ttk.Frame(notebook, padding=10)
        tab_instances = ttk.Frame(notebook, padding=10)
        tab_performance = ttk.Frame(notebook, padding=10)
        tab_monitor = ttk.Frame(notebook, padding=10)
        tab_log = ttk.Frame(notebook, padding=10)
        notebook.add(tab_control, text="Dashboard")
        notebook.add(tab_instances, text="Instances")
        notebook.add(tab_performance, text="Performance")
        notebook.add(tab_monitor, text="Health & Diagnostics")
        notebook.add(tab_log, text="Live Log")

        action_bar = ttk.LabelFrame(tab_control, text="Action Bar", padding=8)
        action_bar.pack(fill="x", pady=(0, 8))
        self.start_button = ttk.Button(action_bar, text="Start", width=11, command=self.start)
        self.start_button.pack(side=tk.LEFT, padx=(0, 5))
        self.stop_button = ttk.Button(action_bar, text="Stop", width=11, command=self.stop, state=tk.DISABLED)
        self.stop_button.pack(side=tk.LEFT, padx=(0, 5))
        self.test_button = ttk.Button(action_bar, text="Jump Now", width=11, command=self.test_jump)
        self.test_button.pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(action_bar, text="Pause Now", width=11, command=self.pause_for_minutes).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(action_bar, text="Resume", width=10, command=self.clear_manual_pause).pack(side=tk.LEFT, padx=(0, 10))
        self.refresh_button = ttk.Button(action_bar, text="Refresh", width=11, command=lambda: self.refresh_instance_list(manual=True))
        self.refresh_button.pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(action_bar, text="Hotkey Help", width=11, command=self.toggle_hotkey_help).pack(side=tk.LEFT, padx=(0, 10))
        ttk.Label(action_bar, textvariable=self.status_var).pack(side=tk.RIGHT)

        dash_notebook = ttk.Notebook(tab_control)
        dash_notebook.pack(fill="both", expand=True)
        dash_run = ttk.Frame(dash_notebook, padding=8)
        dash_automation = ttk.Frame(dash_notebook, padding=8)
        dash_alerts = ttk.Frame(dash_notebook, padding=8)
        dash_startup = ttk.Frame(dash_notebook, padding=8)
        dash_advanced = ttk.Frame(dash_notebook, padding=8)
        dash_notebook.add(dash_run, text="Run")
        dash_notebook.add(dash_automation, text="Automation")
        dash_notebook.add(dash_alerts, text="Alerts")
        dash_notebook.add(dash_startup, text="Startup")
        dash_notebook.add(dash_advanced, text="Advanced")

        quick_access = ttk.LabelFrame(dash_run, text="Quick Start", padding=10)
        quick_access.pack(fill="x", pady=(0, 8))
        ttk.Label(
            quick_access,
            text="1) Refresh instances  2) Enable/disable rows in Instances tab  3) Press Start  4) Use Hotkey Help for shortcuts",
        ).pack(anchor="w")
        qa_actions = ttk.Frame(quick_access)
        qa_actions.pack(fill="x", pady=(6, 0))
        ttk.Button(qa_actions, text="Refresh Instances", width=16, command=lambda: self.refresh_instance_list(manual=True)).pack(side=tk.LEFT)
        ttk.Button(qa_actions, text="Run Diagnostics", width=14, command=self.run_diagnostics_checks).pack(side=tk.LEFT, padx=(6, 0))
        ttk.Button(qa_actions, text="Check Updates", command=self.check_for_updates).pack(side=tk.LEFT, padx=(6, 0))
        ttk.Button(qa_actions, text="Download Latest", command=self.download_latest_release_asset).pack(side=tk.LEFT, padx=(6, 0))

        controls_group = ttk.LabelFrame(dash_run, text="Core Runtime", padding=10)
        controls_group.pack(fill="x")
        row1 = ttk.Frame(controls_group)
        row1.pack(fill="x")
        ttk.Label(row1, text="Jump interval (seconds):").pack(side=tk.LEFT)
        ttk.Entry(row1, textvariable=self.interval_var, width=8, justify="center").pack(side=tk.LEFT, padx=(8, 14))
        ttk.Checkbutton(row1, text="Auto realign", variable=self.auto_realign_var).pack(side=tk.LEFT, padx=(0, 14))
        ttk.Label(row1, text="Jump mode:").pack(side=tk.LEFT)
        ttk.Radiobutton(row1, text="All-at-once", variable=self.jump_mode_var, value="all").pack(side=tk.LEFT, padx=(6, 4))
        ttk.Radiobutton(row1, text="Round-robin", variable=self.jump_mode_var, value="round").pack(side=tk.LEFT)
        ttk.Radiobutton(row1, text="Weighted", variable=self.jump_mode_var, value="weighted").pack(side=tk.LEFT, padx=(8, 0))

        preset_group = ttk.LabelFrame(dash_run, text="Profiles", padding=10)
        preset_group.pack(fill="x", pady=(8, 0))
        preset_row = ttk.Frame(preset_group)
        preset_row.pack(fill="x")
        ttk.Label(preset_row, text="Active preset:").pack(side=tk.LEFT)
        self.preset_combo = ttk.Combobox(preset_row, textvariable=self.preset_name_var, width=24, state="normal")
        self.preset_combo.pack(side=tk.LEFT, padx=(8, 8))
        ttk.Button(preset_row, text="Load Preset", width=12, command=self.load_preset).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(preset_row, text="Save Preset", width=12, command=self.save_preset).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(preset_row, text="Delete Preset", width=12, command=self.delete_preset).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(preset_row, text="Refresh Presets", width=14, command=self._refresh_preset_list).pack(side=tk.LEFT)

        runtime_group = ttk.LabelFrame(dash_automation, text="Loop Behavior", padding=10)
        runtime_group.pack(fill="x")
        pattern_row = ttk.Frame(runtime_group)
        pattern_row.pack(fill="x")
        ttk.Label(pattern_row, text="Anti-idle pattern:").pack(side=tk.LEFT)
        self.pattern_combo = ttk.Combobox(
            pattern_row,
            textvariable=self.anti_idle_pattern_var,
            values=["balanced", "subtle", "aggressive", "randomized"],
            width=12,
            state="readonly",
        )
        self.pattern_combo.pack(side=tk.LEFT, padx=(8, 12))
        ttk.Checkbutton(
            pattern_row,
            text="Wait for Roblox windows before sending jumps",
            variable=self.start_when_windows_found_var,
        ).pack(side=tk.LEFT)
        ttk.Checkbutton(
            pattern_row,
            text="Safe mode (slower/more conservative)",
            variable=self.safe_mode_var,
        ).pack(side=tk.LEFT, padx=(12, 0))

        watchdog_group = ttk.LabelFrame(dash_automation, text="Watchdog & Recovery", padding=10)
        watchdog_group.pack(fill="x", pady=(8, 0))
        opt3 = ttk.Frame(watchdog_group)
        opt3.pack(fill="x")
        ttk.Checkbutton(opt3, text="Watchdog", variable=self.watchdog_enabled_var).pack(side=tk.LEFT)
        ttk.Label(opt3, text="No windows cycles:").pack(side=tk.LEFT, padx=(10, 4))
        ttk.Entry(opt3, textvariable=self.watchdog_no_windows_threshold_var, width=5, justify="center").pack(side=tk.LEFT)
        ttk.Label(opt3, text="Jump-fail cycles:").pack(side=tk.LEFT, padx=(10, 4))
        ttk.Entry(opt3, textvariable=self.watchdog_jump_fail_threshold_var, width=5, justify="center").pack(side=tk.LEFT)
        ttk.Checkbutton(opt3, text="Recovery sequence", variable=self.recovery_enabled_var).pack(side=tk.LEFT, padx=(12, 0))
        ttk.Checkbutton(
            opt3,
            text="Standby monitoring when loop is stopped",
            variable=self.watchdog_standby_mode_var,
        ).pack(side=tk.LEFT, padx=(12, 0))

        relaunch_row = ttk.Frame(watchdog_group)
        relaunch_row.pack(fill="x", pady=(8, 0))
        ttk.Checkbutton(
            relaunch_row,
            text="Auto-relaunch dropped instances",
            variable=self.instance_relaunch_enabled_var,
        ).pack(side=tk.LEFT)
        ttk.Label(relaunch_row, text="Grace (s):").pack(side=tk.LEFT, padx=(10, 4))
        ttk.Entry(
            relaunch_row,
            textvariable=self.instance_relaunch_grace_seconds_var,
            width=5,
            justify="center",
        ).pack(side=tk.LEFT)
        ttk.Label(relaunch_row, text="Max launches/hr:").pack(side=tk.LEFT, padx=(10, 4))
        ttk.Entry(
            relaunch_row,
            textvariable=self.instance_relaunch_max_per_hour_var,
            width=5,
            justify="center",
        ).pack(side=tk.LEFT)
        ttk.Label(relaunch_row, textvariable=self.instance_relaunch_status_var).pack(side=tk.RIGHT)

        relaunch_target_row = ttk.Frame(watchdog_group)
        relaunch_target_row.pack(fill="x", pady=(6, 0))
        ttk.Label(relaunch_target_row, text="Launch target (optional URL or Roblox exe path):").pack(side=tk.LEFT)
        ttk.Entry(
            relaunch_target_row,
            textvariable=self.instance_relaunch_launch_target_var,
            width=56,
        ).pack(side=tk.LEFT, padx=(8, 0), fill="x", expand=True)

        private_join_row = ttk.Frame(watchdog_group)
        private_join_row.pack(fill="x", pady=(6, 0))
        ttk.Label(private_join_row, text="Private server helper").pack(side=tk.LEFT)
        ttk.Label(private_join_row, text="Place ID:").pack(side=tk.LEFT, padx=(10, 4))
        ttk.Entry(private_join_row, textvariable=self.private_server_place_id_var, width=12, justify="center").pack(side=tk.LEFT)
        ttk.Label(private_join_row, text="Link code:").pack(side=tk.LEFT, padx=(8, 4))
        ttk.Entry(private_join_row, textvariable=self.private_server_code_var, width=24).pack(side=tk.LEFT)
        ttk.Button(private_join_row, text="Apply Join Target", width=18, command=self.apply_private_server_target).pack(
            side=tk.LEFT, padx=(8, 0)
        )

        roster_row = ttk.Frame(watchdog_group)
        roster_row.pack(fill="x", pady=(6, 0))
        ttk.Checkbutton(
            roster_row,
            text="Track locked account roster",
            variable=self.account_roster_enabled_var,
            command=self._refresh_account_roster_status,
        ).pack(side=tk.LEFT)
        ttk.Button(roster_row, text="Lock Current Accounts", width=20, command=self.lock_current_account_roster).pack(
            side=tk.LEFT, padx=(8, 4)
        )
        ttk.Button(roster_row, text="Clear Locked", width=12, command=self.clear_account_roster).pack(side=tk.LEFT)
        ttk.Label(roster_row, textvariable=self.account_roster_status_var).pack(side=tk.RIGHT)

        pause_group = ttk.LabelFrame(dash_automation, text="Pause Controls", padding=10)
        pause_group.pack(fill="x", pady=(8, 0))
        opt1 = ttk.Frame(pause_group)
        opt1.pack(fill="x")
        ttk.Checkbutton(opt1, text="Safe pause schedule", variable=self.pause_enabled_var).pack(side=tk.LEFT)
        ttk.Label(opt1, text="Start HH:MM").pack(side=tk.LEFT, padx=(10, 4))
        ttk.Entry(opt1, textvariable=self.pause_start_var, width=6, justify="center").pack(side=tk.LEFT)
        ttk.Label(opt1, text="End HH:MM").pack(side=tk.LEFT, padx=(10, 4))
        ttk.Entry(opt1, textvariable=self.pause_end_var, width=6, justify="center").pack(side=tk.LEFT)
        pause_quick_row = ttk.Frame(pause_group)
        pause_quick_row.pack(fill="x", pady=(6, 0))
        ttk.Label(pause_quick_row, text="Quick pause (minutes):").pack(side=tk.LEFT)
        ttk.Entry(pause_quick_row, textvariable=self.manual_pause_minutes_var, width=5, justify="center").pack(side=tk.LEFT, padx=(8, 6))
        ttk.Button(pause_quick_row, text="Pause Now", width=10, command=self.pause_for_minutes).pack(side=tk.LEFT)
        ttk.Button(pause_quick_row, text="Resume", width=10, command=self.clear_manual_pause).pack(side=tk.LEFT, padx=(6, 0))

        webhook_group = ttk.LabelFrame(dash_alerts, text="Webhook Alerts", padding=10)
        webhook_group.pack(fill="x")
        opt2 = ttk.Frame(webhook_group)
        opt2.pack(fill="x")
        ttk.Button(opt2, text="Test Webhook", command=self.test_webhook_health).pack(side=tk.RIGHT, padx=(8, 0))
        ttk.Entry(opt2, textvariable=self.webhook_url_var).pack(side=tk.RIGHT, fill="x", expand=True, padx=(8, 0))
        ttk.Checkbutton(opt2, text="Discord webhook alerts", variable=self.webhook_enabled_var).pack(side=tk.LEFT)
        route_row_1 = ttk.Frame(webhook_group)
        route_row_1.pack(fill="x", pady=(6, 0))
        ttk.Label(route_row_1, text="Biome URL").pack(side=tk.LEFT)
        ttk.Entry(route_row_1, textvariable=self.webhook_biome_url_var, width=30).pack(
            side=tk.LEFT, padx=(6, 10), fill="x", expand=True
        )
        ttk.Label(route_row_1, text="Recovery URL").pack(side=tk.LEFT)
        ttk.Entry(route_row_1, textvariable=self.webhook_recovery_url_var, width=30).pack(
            side=tk.LEFT, padx=(6, 0), fill="x", expand=True
        )
        route_row_2 = ttk.Frame(webhook_group)
        route_row_2.pack(fill="x", pady=(6, 0))
        ttk.Label(route_row_2, text="Health URL").pack(side=tk.LEFT)
        ttk.Entry(route_row_2, textvariable=self.webhook_health_url_var, width=30).pack(
            side=tk.LEFT, padx=(6, 10), fill="x", expand=True
        )
        ttk.Label(route_row_2, text="Vendor URL").pack(side=tk.LEFT)
        ttk.Entry(route_row_2, textvariable=self.webhook_vendor_url_var, width=30).pack(
            side=tk.LEFT, padx=(6, 0), fill="x", expand=True
        )

        health_group_controls = ttk.LabelFrame(dash_alerts, text="Instance Health Alerts", padding=10)
        health_group_controls.pack(fill="x", pady=(8, 0))
        health_row = ttk.Frame(health_group_controls)
        health_row.pack(fill="x")
        ttk.Checkbutton(health_row, text="Instance health alerts", variable=self.health_alert_enabled_var).pack(side=tk.LEFT)
        ttk.Label(health_row, text="No jump threshold (minutes):").pack(side=tk.LEFT, padx=(10, 4))
        ttk.Entry(health_row, textvariable=self.health_alert_minutes_var, width=5, justify="center").pack(side=tk.LEFT)
        ttk.Checkbutton(health_row, text="Auto-save recovery snapshot", variable=self.autosave_enabled_var).pack(side=tk.LEFT, padx=(12, 0))
        ttk.Label(health_row, text="Every (minutes):").pack(side=tk.LEFT, padx=(8, 4))
        ttk.Entry(health_row, textvariable=self.autosave_minutes_var, width=5, justify="center").pack(side=tk.LEFT)

        biome_group = ttk.LabelFrame(dash_alerts, text="Biome Alerts", padding=10)
        biome_group.pack(fill="x", pady=(8, 0))
        biome_row = ttk.Frame(biome_group)
        biome_row.pack(fill="x")
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
        alert_row = ttk.Frame(biome_group)
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
        confirm_row = ttk.Frame(biome_group)
        confirm_row.pack(fill="x", pady=(6, 0))
        ttk.Checkbutton(
            confirm_row,
            text="Require rare-biome confirmation",
            variable=self.rare_biome_confirm_enabled_var,
        ).pack(side=tk.LEFT)
        ttk.Label(confirm_row, text="Confirm for (s):").pack(side=tk.LEFT, padx=(10, 4))
        ttk.Entry(confirm_row, textvariable=self.rare_biome_confirm_seconds_var, width=5, justify="center").pack(side=tk.LEFT)
        action_row = ttk.Frame(biome_group)
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
        vendor_row = ttk.Frame(biome_group)
        vendor_row.pack(fill="x", pady=(6, 0))
        ttk.Checkbutton(vendor_row, text="Merchant/Jester webhook alerts", variable=self.vendor_alerts_enabled_var).pack(
            side=tk.LEFT
        )
        ttk.Label(vendor_row, text="Cooldown (s):").pack(side=tk.LEFT, padx=(10, 4))
        ttk.Entry(vendor_row, textvariable=self.vendor_alert_cooldown_var, width=5, justify="center").pack(side=tk.LEFT)

        startup_group = ttk.LabelFrame(dash_startup, text="Startup Behavior", padding=10)
        startup_group.pack(fill="x")
        startup_row = ttk.Frame(startup_group)
        startup_row.pack(fill="x")
        ttk.Checkbutton(startup_row, text="Startup restore", variable=self.startup_restore_enabled_var).pack(side=tk.LEFT)
        ttk.Label(startup_row, text="Preset:").pack(side=tk.LEFT, padx=(10, 4))
        self.startup_preset_combo = ttk.Combobox(
            startup_row,
            textvariable=self.startup_preset_var,
            width=16,
            state="normal",
        )
        self.startup_preset_combo.pack(side=tk.LEFT)
        ttk.Checkbutton(startup_row, text="Auto-start", variable=self.startup_auto_start_var).pack(side=tk.LEFT, padx=(10, 0))
        ttk.Checkbutton(startup_row, text="Auto-align", variable=self.startup_auto_align_var).pack(side=tk.LEFT, padx=(8, 0))

        scheduler_group = ttk.LabelFrame(dash_startup, text="Scheduler", padding=10)
        scheduler_group.pack(fill="x", pady=(8, 0))
        scheduler_row = ttk.Frame(scheduler_group)
        scheduler_row.pack(fill="x")
        ttk.Checkbutton(scheduler_row, text="Profile scheduler", variable=self.scheduler_enabled_var).pack(side=tk.LEFT)
        ttk.Label(scheduler_row, text="Slot 1").pack(side=tk.LEFT, padx=(10, 3))
        ttk.Entry(scheduler_row, textvariable=self.scheduler_slot1_time_var, width=6, justify="center").pack(side=tk.LEFT)
        ttk.Entry(scheduler_row, textvariable=self.scheduler_slot1_preset_var, width=12).pack(side=tk.LEFT, padx=(4, 8))
        ttk.Label(scheduler_row, text="Slot 2").pack(side=tk.LEFT, padx=(6, 3))
        ttk.Entry(scheduler_row, textvariable=self.scheduler_slot2_time_var, width=6, justify="center").pack(side=tk.LEFT)
        ttk.Entry(scheduler_row, textvariable=self.scheduler_slot2_preset_var, width=12).pack(side=tk.LEFT, padx=(4, 0))

        hotkey_profile_group = ttk.LabelFrame(dash_startup, text="Hotkey Profiles", padding=10)
        hotkey_profile_group.pack(fill="x", pady=(8, 0))
        hotkey_row = ttk.Frame(hotkey_profile_group)
        hotkey_row.pack(fill="x")
        ttk.Checkbutton(
            hotkey_row,
            text="Global hotkeys (Ctrl+Alt+S/J/R/T/1/2/3)",
            variable=self.hotkeys_enabled_var,
            command=self.on_hotkeys_toggle,
        ).pack(side=tk.LEFT)
        ttk.Checkbutton(
            hotkey_row,
            text="Safety lock: block Start/Stop + Tray hotkeys while Roblox is focused",
            variable=self.hotkey_guard_var,
        ).pack(side=tk.LEFT, padx=(12, 0))
        quick_profiles_row = ttk.Frame(hotkey_profile_group)
        quick_profiles_row.pack(fill="x", pady=(6, 0))
        ttk.Label(quick_profiles_row, text="Profiles for Ctrl+Alt+1/2/3:").pack(side=tk.LEFT)
        self.profile_hotkey_1_entry = ttk.Entry(quick_profiles_row, textvariable=self.profile_hotkey_1_var, width=12)
        self.profile_hotkey_1_entry.pack(side=tk.LEFT, padx=(8, 4))
        self.profile_hotkey_2_entry = ttk.Entry(quick_profiles_row, textvariable=self.profile_hotkey_2_var, width=12)
        self.profile_hotkey_2_entry.pack(side=tk.LEFT, padx=4)
        self.profile_hotkey_3_entry = ttk.Entry(quick_profiles_row, textvariable=self.profile_hotkey_3_var, width=12)
        self.profile_hotkey_3_entry.pack(side=tk.LEFT, padx=4)

        advanced_tools_group = ttk.LabelFrame(dash_advanced, text="Advanced Tools", padding=10)
        advanced_tools_group.pack(fill="x")
        row2 = ttk.Frame(advanced_tools_group)
        row2.pack(fill="x")
        self.align_button = ttk.Button(row2, text="Align", width=11, command=self.align_windows)
        self.align_button.pack(side=tk.LEFT, padx=(0, 5))
        self.restore_button = ttk.Button(row2, text="Restore", width=11, command=self.restore_windows)
        self.restore_button.pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(row2, text="Retry Identity", width=13, command=self.retry_selected_identity).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(row2, text="To Tray", width=11, command=self.minimize_to_tray).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(row2, text="Open Presets", width=12, command=self.open_presets_folder).pack(side=tk.LEFT, padx=(0, 5))

        row3 = ttk.Frame(advanced_tools_group)
        row3.pack(fill="x", pady=(8, 0))
        self.save_button = ttk.Button(row3, text="Save Config", width=12, command=self.save_config)
        self.save_button.pack(side=tk.LEFT, padx=(0, 5))
        self.load_button = ttk.Button(row3, text="Load Config", width=12, command=lambda: self.load_config(silent=False))
        self.load_button.pack(side=tk.LEFT, padx=(0, 10))
        ttk.Button(row3, text="Export JSON", width=12, command=lambda: self.export_instances("json")).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(row3, text="Export CSV", width=12, command=lambda: self.export_instances("csv")).pack(side=tk.LEFT, padx=(0, 10))
        ttk.Button(row3, text="Build EXE", width=12, command=self.build_exe).pack(side=tk.LEFT)

        history_group = ttk.LabelFrame(tab_monitor, text="Biome Alert History", padding=8)
        history_group.pack(fill="x", pady=(8, 0))
        self.biome_history_list = tk.Listbox(history_group, height=4)
        self.biome_history_list.pack(fill="x")

        timeline_group = ttk.LabelFrame(tab_monitor, text="Event Timeline", padding=8)
        timeline_group.pack(fill="x", pady=(8, 0))
        timeline_actions = ttk.Frame(timeline_group)
        timeline_actions.pack(fill="x", pady=(0, 4))
        ttk.Label(timeline_actions, text="Filter:").pack(side=tk.LEFT)
        self.event_filter_combo = ttk.Combobox(
            timeline_actions,
            textvariable=self.event_filter_var,
            values=["all", "errors", "watchdog", "biome", "vendor", "hotkeys", "health", "recovery", "scheduler", "updates"],
            width=12,
            state="readonly",
        )
        self.event_filter_combo.pack(side=tk.LEFT, padx=(6, 6))
        self.event_filter_combo.bind("<<ComboboxSelected>>", lambda _e: self._refresh_event_history_view())
        ttk.Button(timeline_actions, text="Export CSV", width=11, command=self.export_event_timeline_csv).pack(side=tk.LEFT)
        self.event_history_list = tk.Listbox(timeline_group, height=5)
        self.event_history_list.pack(fill="x")

        recovery_group = ttk.LabelFrame(tab_monitor, text="Recovery Timeline", padding=8)
        recovery_group.pack(fill="x", pady=(8, 0))
        recovery_actions = ttk.Frame(recovery_group)
        recovery_actions.pack(fill="x", pady=(0, 4))
        ttk.Button(recovery_actions, text="Export CSV", width=11, command=self.export_recovery_timeline_csv).pack(side=tk.LEFT)
        self.recovery_history_list = tk.Listbox(recovery_group, height=4)
        self.recovery_history_list.pack(fill="x")

        target_group = ttk.LabelFrame(tab_instances, text="Per Instance Controls", padding=10)
        target_group.pack(fill="both", expand=True, pady=(8, 0))

        target_top = ttk.Frame(target_group)
        target_top.pack(fill="x")
        ttk.Label(target_top, text="Double-click Enabled column to toggle per instance.").pack(side=tk.LEFT)
        ttk.Button(target_top, text="Enable All", command=self.enable_all_instances).pack(side=tk.RIGHT, padx=(6, 0))
        ttk.Button(target_top, text="Disable All", command=self.disable_all_instances).pack(side=tk.RIGHT)

        target_overrides = ttk.Frame(target_group)
        target_overrides.pack(fill="x", pady=(8, 0))
        ttk.Label(target_overrides, text="Selected override interval (s):").pack(side=tk.LEFT)
        self.instance_override_seconds_var = tk.StringVar(value="")
        ttk.Entry(target_overrides, textvariable=self.instance_override_seconds_var, width=7, justify="center").pack(
            side=tk.LEFT, padx=(6, 8)
        )
        ttk.Label(target_overrides, text="Pattern:").pack(side=tk.LEFT)
        self.instance_override_pattern_var = tk.StringVar(value="default")
        ttk.Combobox(
            target_overrides,
            textvariable=self.instance_override_pattern_var,
            values=["default", "balanced", "subtle", "aggressive", "randomized"],
            width=11,
            state="readonly",
        ).pack(side=tk.LEFT, padx=(6, 8))
        ttk.Label(target_overrides, text="Priority (1-9):").pack(side=tk.LEFT)
        self.instance_priority_var = tk.StringVar(value="1")
        ttk.Entry(target_overrides, textvariable=self.instance_priority_var, width=4, justify="center").pack(
            side=tk.LEFT, padx=(6, 8)
        )
        ttk.Button(target_overrides, text="Apply to Selected", command=self.apply_selected_instance_overrides).pack(
            side=tk.LEFT, padx=(0, 6)
        )
        ttk.Button(target_overrides, text="Clear Selected", command=self.clear_selected_instance_overrides).pack(side=tk.LEFT)

        tree_frame = ttk.Frame(target_group)
        tree_frame.pack(fill="both", expand=True, pady=(8, 0))

        columns = ("enabled", "priority", "pid", "hwnd", "process", "username", "confidence", "aura", "last_jump", "title")
        self.instance_tree = ttk.Treeview(tree_frame, columns=columns, show="tree headings", height=8)
        self.instance_tree.heading("#0", text="Avatar")
        self.instance_tree.heading("enabled", text="Enabled")
        self.instance_tree.heading("priority", text="Prio")
        self.instance_tree.heading("pid", text="PID")
        self.instance_tree.heading("hwnd", text="HWND")
        self.instance_tree.heading("process", text="Process")
        self.instance_tree.heading("username", text="Username")
        self.instance_tree.heading("confidence", text="Identity")
        self.instance_tree.heading("aura", text="Aura")
        self.instance_tree.heading("last_jump", text="Last Jump")
        self.instance_tree.heading("title", text="Window Title")
        self.instance_tree.column("#0", width=56, anchor="center", stretch=False)
        self.instance_tree.column("enabled", width=70, anchor="center")
        self.instance_tree.column("priority", width=52, anchor="center")
        self.instance_tree.column("pid", width=70, anchor="center")
        self.instance_tree.column("hwnd", width=95, anchor="center")
        self.instance_tree.column("process", width=140, anchor="w")
        self.instance_tree.column("username", width=125, anchor="w")
        self.instance_tree.column("confidence", width=95, anchor="center")
        self.instance_tree.column("aura", width=120, anchor="w")
        self.instance_tree.column("last_jump", width=90, anchor="center")
        self.instance_tree.column("title", width=270, anchor="w")
        self.instance_tree.pack(side=tk.LEFT, fill="both", expand=True)
        self.instance_tree.bind("<Double-1>", self.on_tree_double_click)

        tree_scroll = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=self.instance_tree.yview)
        tree_scroll.pack(side=tk.RIGHT, fill="y")
        self.instance_tree.configure(yscrollcommand=tree_scroll.set)

        limiter_group = ttk.LabelFrame(tab_performance, text="Process Limiter", padding=10)
        limiter_group.pack(fill="x", pady=(0, 8))
        limiter_row1 = ttk.Frame(limiter_group)
        limiter_row1.pack(fill="x")
        ttk.Checkbutton(
            limiter_row1,
            text="Enable duty-cycle limiter (suspend/resume Roblox processes)",
            variable=self.process_limiter_enabled_var,
        ).pack(side=tk.LEFT)
        ttk.Checkbutton(
            limiter_row1,
            text="Auto mode: force instant 0% freeze",
            variable=self.process_limiter_auto_mode_var,
        ).pack(side=tk.LEFT, padx=(12, 0))
        ttk.Checkbutton(
            limiter_row1,
            text="Only while macro is running",
            variable=self.process_limiter_only_when_running_var,
        ).pack(side=tk.LEFT, padx=(12, 0))

        limiter_row2 = ttk.Frame(limiter_group)
        limiter_row2.pack(fill="x", pady=(8, 0))
        ttk.Label(limiter_row2, text="Target active time (%):").pack(side=tk.LEFT)
        ttk.Entry(
            limiter_row2,
            textvariable=self.process_limiter_target_percent_var,
            width=5,
            justify="center",
        ).pack(side=tk.LEFT, padx=(6, 10))
        ttk.Label(limiter_row2, text="Cycle (ms):").pack(side=tk.LEFT)
        ttk.Entry(
            limiter_row2,
            textvariable=self.process_limiter_cycle_ms_var,
            width=6,
            justify="center",
        ).pack(side=tk.LEFT, padx=(6, 10))
        ttk.Button(
            limiter_row2,
            text="Apply",
            width=9,
            command=self.apply_process_limiter_settings,
        ).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(
            limiter_row2,
            text="Resume All",
            width=11,
            command=self.resume_all_limited_processes,
        ).pack(side=tk.LEFT)
        ttk.Label(limiter_row2, textvariable=self.process_limiter_status_var).pack(side=tk.RIGHT)

        limiter_note = ttk.LabelFrame(tab_performance, text="Notes", padding=10)
        limiter_note.pack(fill="x")
        ttk.Label(
            limiter_note,
            text=(
                "Limiter reduces CPU by cycling Roblox processes between active and suspended windows. "
                "This build boosts a process before each jump so input remains reliable."
            ),
            wraplength=1000,
            justify=tk.LEFT,
        ).pack(anchor="w")

        limiter_targets = ttk.LabelFrame(tab_performance, text="Detected Process States", padding=10)
        limiter_targets.pack(fill="both", expand=True, pady=(8, 0))
        limiter_tree_frame = ttk.Frame(limiter_targets)
        limiter_tree_frame.pack(fill="both", expand=True)
        limiter_columns = ("pid", "username", "state", "boost_until", "title")
        self.process_limiter_tree = ttk.Treeview(limiter_tree_frame, columns=limiter_columns, show="headings", height=8)
        self.process_limiter_tree.heading("pid", text="PID")
        self.process_limiter_tree.heading("username", text="Username")
        self.process_limiter_tree.heading("state", text="Limiter State")
        self.process_limiter_tree.heading("boost_until", text="Boost Until")
        self.process_limiter_tree.heading("title", text="Window Title")
        self.process_limiter_tree.column("pid", width=80, anchor="center")
        self.process_limiter_tree.column("username", width=140, anchor="w")
        self.process_limiter_tree.column("state", width=130, anchor="center")
        self.process_limiter_tree.column("boost_until", width=120, anchor="center")
        self.process_limiter_tree.column("title", width=500, anchor="w")
        self.process_limiter_tree.pack(side=tk.LEFT, fill="both", expand=True)
        limiter_scroll = ttk.Scrollbar(limiter_tree_frame, orient=tk.VERTICAL, command=self.process_limiter_tree.yview)
        limiter_scroll.pack(side=tk.RIGHT, fill="y")
        self.process_limiter_tree.configure(yscrollcommand=limiter_scroll.set)

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
        ttk.Button(diag_row, text="Check Updates", command=self.check_for_updates).pack(side=tk.LEFT, padx=(5, 5))
        ttk.Button(diag_row, text="Download Latest", command=self.download_latest_release_asset).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(diag_row, text="Open Release", width=12, command=self.open_latest_release_page).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(diag_row, text="Hotkey Help", width=12, command=self.toggle_hotkey_help).pack(side=tk.LEFT, padx=(0, 5))
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
        plain_line = line.rstrip("\n")
        self.recent_log_lines.append(plain_line)
        overflow_lines = len(self.recent_log_lines) - self.max_log_lines
        if overflow_lines > 0:
            self.recent_log_lines = self.recent_log_lines[overflow_lines:]
        self.log_box.configure(state=tk.NORMAL)
        self.log_box.insert(tk.END, line)
        line_count = int(self.log_box.index("end-1c").split(".")[0])
        overflow = line_count - self.max_log_lines
        if overflow > 0:
            self.log_box.delete("1.0", f"{overflow + 1}.0")
        self.log_box.see(tk.END)
        self.log_box.configure(state=tk.DISABLED)

    def _enqueue_on_ui_thread(self, callback: Callable[..., None], *args: Any) -> bool:
        if threading.current_thread() is threading.main_thread():
            return False
        try:
            self.ui_dispatch_queue.put((callback, args))
        except Exception:
            return True
        return True

    def _drain_ui_dispatch_queue(self) -> None:
        processed = 0
        try:
            while processed < 200:
                try:
                    callback, args = self.ui_dispatch_queue.get_nowait()
                except queue.Empty:
                    break
                processed += 1
                try:
                    callback(*args)
                except Exception as exc:
                    timestamp = time.strftime("%H:%M:%S")
                    self._write_runtime_log_line(f"[{timestamp}] UI dispatch error: {exc}\n")
        finally:
            try:
                self.root.after(25, self._drain_ui_dispatch_queue)
            except Exception:
                pass

    def _write_runtime_log_line(self, line: str) -> None:
        try:
            os.makedirs(self.reports_dir, exist_ok=True)
            with self.runtime_log_lock:
                try:
                    if os.path.exists(self.runtime_log_path):
                        size = os.path.getsize(self.runtime_log_path)
                        if size >= self.runtime_log_max_bytes:
                            rotated = self.runtime_log_path + ".1"
                            try:
                                if os.path.exists(rotated):
                                    os.remove(rotated)
                            except OSError:
                                pass
                            try:
                                os.replace(self.runtime_log_path, rotated)
                            except OSError:
                                pass
                except OSError:
                    pass
                with open(self.runtime_log_path, "a", encoding="utf-8", errors="replace") as handle:
                    handle.write(line)
        except Exception:
            pass

    def log(self, text: str) -> None:
        timestamp = time.strftime("%H:%M:%S")
        line = f"[{timestamp}] {text}\n"
        self._write_runtime_log_line(line)
        if not self._enqueue_on_ui_thread(self._append_log_line, line):
            self._append_log_line(line)

    def _install_exception_hooks(self) -> None:
        previous_thread_hook = getattr(threading, "excepthook", None)

        def _thread_hook(args: Any) -> None:
            try:
                details = "".join(traceback.format_exception(args.exc_type, args.exc_value, args.exc_traceback))
                self._write_crash_report("thread-exception", details)
            except Exception:
                pass
            if callable(previous_thread_hook):
                try:
                    previous_thread_hook(args)
                except Exception:
                    pass

        if previous_thread_hook is not None:
            threading.excepthook = _thread_hook  # type: ignore[assignment]

    def _write_crash_report(self, reason: str, details: str) -> str | None:
        try:
            os.makedirs(self.reports_dir, exist_ok=True)
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            path = os.path.join(self.reports_dir, f"crash-{stamp}.txt")
            events_tail = list(self.event_timeline[-200:])
            log_tail = list(self.recent_log_lines[-200:])
            if threading.current_thread() is threading.main_thread():
                try:
                    log_tail = self.log_box.get("1.0", tk.END).splitlines()[-200:]
                except Exception:
                    pass
            lines = [
                f"{APP_NAME} v{APP_VERSION}",
                f"Reason: {reason}",
                f"Time: {datetime.now().isoformat(timespec='seconds')}",
                "",
                "Exception:",
                details.strip(),
                "",
                "Recent events:",
                *events_tail,
                "",
                "Recent app log tail:",
                *log_tail,
            ]
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("\n".join(lines) + "\n")
            return path
        except Exception:
            return None

    def _write_session_report(self, reason: str) -> str | None:
        try:
            os.makedirs(self.reports_dir, exist_ok=True)
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            path = os.path.join(self.reports_dir, f"session-{stamp}-{reason}.json")
            runtime_seconds = 0
            if self.session_started_at is not None:
                runtime_seconds = int(max(0, time.time() - self.session_started_at))
            payload = {
                "app": APP_NAME,
                "version": APP_VERSION,
                "reason": reason,
                "time": datetime.now().isoformat(timespec="seconds"),
                "runtime_seconds": runtime_seconds,
                "session_cycles": self.session_cycles,
                "session_jumps": self.session_jumps,
                "session_errors": self.session_errors,
                "watchdog_no_windows_cycles": self.no_window_cycles,
                "watchdog_jump_fail_cycles": self.jump_fail_cycles,
                "current_biome": self.current_biome_name,
                "events_tail": self.event_timeline[-120:],
            }
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, indent=2)
            return path
        except Exception:
            return None

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
        parent = self.theme_maker_window if self.theme_maker_window is not None else self.root
        _rgb, picked = colorchooser.askcolor(color=initial, parent=parent)
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
            messagebox.showerror("Theme Maker", f"Imported file does not contain a valid {APP_NAME} theme palette.")
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
        if hasattr(self, "event_history_list"):
            self.event_history_list.configure(
                bg=palette["field"],
                fg=palette["text"],
                highlightbackground=palette["panel"],
                highlightcolor=palette["accent"],
                selectbackground=palette["tree_sel"],
                selectforeground=palette["tree_selfg"],
            )
        if hasattr(self, "recovery_history_list"):
            self.recovery_history_list.configure(
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

    @staticmethod
    def _normalize_equipped_aura(raw_state: str) -> str | None:
        text = raw_state.strip()
        if not text:
            return None
        if not text.lower().startswith("equipped"):
            return None
        aura = text[len("equipped") :].strip(" :-")
        if not aura:
            return None
        for _ in range(2):
            if len(aura) >= 2 and (
                (aura[0] == '"' and aura[-1] == '"')
                or (aura[0] == "'" and aura[-1] == "'")
                or (aura[0] == "_" and aura[-1] == "_")
            ):
                aura = aura[1:-1].strip()
        aura = re.sub(r"\s+", " ", aura).strip()
        if not aura:
            return None
        if aura.lower() in {"none", "null", "n/a", "na", "unknown"}:
            return "None"
        return aura

    def _extract_equipped_aura_from_line(self, line: str) -> str | None:
        line = line.strip()
        if not line:
            return None
        rpc_match = self._bloxstrap_presence_pattern.search(line)
        if not rpc_match:
            return None
        try:
            payload = json.loads(rpc_match.group("payload"))
        except json.JSONDecodeError:
            return None
        if not isinstance(payload, dict) or payload.get("command") != "SetRichPresence":
            return None
        data = payload.get("data")
        if not isinstance(data, dict):
            return None
        state = data.get("state")
        if not isinstance(state, str):
            return None
        return self._normalize_equipped_aura(state)

    def _poll_equipped_auras(self, pids: set[int] | None = None, force: bool = False) -> None:
        now = time.time()
        if not force and (now - self.last_aura_poll_at) < self.aura_poll_interval_seconds:
            return
        self.last_aura_poll_at = now

        if pids is None:
            with self.state_lock:
                target_pids = {pid for _hwnd, _title, pid, _pname in self.window_map if pid > 0}
        else:
            target_pids = {pid for pid in pids if pid > 0}
        if not target_pids:
            return

        with self.state_lock:
            path_hint = dict(self.pid_log_hint)
            aura_path = dict(self.pid_aura_log_path)
            aura_offset = dict(self.pid_aura_log_offset)
            discovery_at = dict(self.pid_aura_log_discovery_last_attempt)
            username_by_pid = dict(self.pid_username)

        new_path_by_pid: dict[int, str] = {}
        new_offset_by_pid: dict[int, int] = {}
        new_aura_by_pid: dict[int, str] = {}
        new_discovery_at_by_pid: dict[int, float] = {}
        changed: list[tuple[int, str, str]] = []

        for pid in sorted(target_pids):
            log_path = aura_path.get(pid)
            if not log_path or not os.path.exists(log_path):
                hinted = path_hint.get(pid)
                if hinted and os.path.exists(hinted):
                    log_path = hinted
                else:
                    last_discovery_at = discovery_at.get(pid, 0.0)
                    if force or (now - last_discovery_at) >= self.aura_log_discovery_interval_seconds:
                        new_discovery_at_by_pid[pid] = now
                        candidates = self._find_candidate_logs_for_pid(pid)
                        log_path = next((path for path in candidates if os.path.exists(path)), "")
                    else:
                        log_path = ""
            if not log_path:
                continue

            try:
                log_size = os.path.getsize(log_path)
            except OSError:
                continue

            offset = aura_offset.get(pid, 0)
            if aura_path.get(pid) != log_path:
                offset = max(0, log_size - self.aura_log_read_bytes)
            elif log_size < offset:
                offset = 0

            try:
                with open(log_path, "r", encoding="utf-8", errors="ignore") as handle:
                    handle.seek(offset)
                    chunk = handle.read(self.aura_log_read_bytes)
                    new_offset = handle.tell()
            except OSError:
                continue

            detected_aura: str | None = None
            for line in chunk.splitlines():
                aura = self._extract_equipped_aura_from_line(line)
                if aura is not None:
                    detected_aura = aura

            new_path_by_pid[pid] = log_path
            new_offset_by_pid[pid] = new_offset
            if detected_aura is not None:
                new_aura_by_pid[pid] = detected_aura

        if not (new_path_by_pid or new_offset_by_pid or new_aura_by_pid or new_discovery_at_by_pid):
            return

        with self.state_lock:
            for pid, log_path in new_path_by_pid.items():
                self.pid_aura_log_path[pid] = log_path
            for pid, offset in new_offset_by_pid.items():
                self.pid_aura_log_offset[pid] = offset
            for pid, timestamp in new_discovery_at_by_pid.items():
                self.pid_aura_log_discovery_last_attempt[pid] = timestamp
            for pid, aura in new_aura_by_pid.items():
                previous = self.pid_equipped_aura.get(pid, "")
                self.pid_equipped_aura[pid] = aura
                if aura != previous:
                    username = username_by_pid.get(pid, "unknown")
                    changed.append((pid, username, aura))

        for pid, username, aura in changed[:6]:
            self.log(f"Aura updated for PID {pid} ({username}): {aura}")
        if len(changed) > 6:
            self.log(f"Aura updated for {len(changed)} instances.")

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

    def _extract_vendor_from_line(self, line: str) -> str | None:
        text = line.strip()
        if not text:
            return None
        for vendor, pattern in self._vendor_line_patterns:
            if pattern.search(text):
                return vendor
        return None

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
        if self._enqueue_on_ui_thread(self._record_event, text):
            return
        stamp = time.strftime("%H:%M:%S")
        line = f"{stamp} | {text}"
        self.event_timeline.append(line)
        self.event_timeline = self.event_timeline[-160:]
        if self._is_recovery_event_text(text):
            self.recovery_timeline.append(line)
            self.recovery_timeline = self.recovery_timeline[-180:]
            self._refresh_recovery_history_view()
        self._refresh_event_history_view()

    @staticmethod
    def _is_recovery_event_text(text: str) -> bool:
        hay = text.strip().lower()
        if not hay:
            return False
        keywords = ("recovery", "watchdog", "relaunch", "roster", "quarantine")
        return any(keyword in hay for keyword in keywords)

    def _event_matches_filter(self, event_line: str) -> bool:
        mode = self.event_filter_var.get().strip().lower()
        if mode in {"", "all"}:
            return True
        hay = event_line.lower()
        if mode == "errors":
            return ("error" in hay) or ("failed" in hay)
        if mode == "watchdog":
            return "watchdog" in hay
        if mode == "biome":
            return "biome" in hay
        if mode == "vendor":
            return ("merchant" in hay) or ("jester" in hay) or ("vendor" in hay)
        if mode == "hotkeys":
            return "hotkey" in hay
        if mode == "health":
            return "health" in hay
        if mode == "recovery":
            return self._is_recovery_event_text(hay)
        if mode == "scheduler":
            return "scheduler" in hay
        if mode == "updates":
            return "update" in hay
        return True

    def _refresh_event_history_view(self) -> None:
        if hasattr(self, "event_history_list"):
            self.event_history_list.delete(0, tk.END)
            visible = [item for item in self.event_timeline if self._event_matches_filter(item)]
            for item in visible[-60:]:
                self.event_history_list.insert(tk.END, item)

    def _refresh_recovery_history_view(self) -> None:
        if hasattr(self, "recovery_history_list"):
            self.recovery_history_list.delete(0, tk.END)
            for item in self.recovery_timeline[-60:]:
                self.recovery_history_list.insert(tk.END, item)

    def export_event_timeline_csv(self) -> None:
        path = filedialog.asksaveasfilename(defaultextension=".csv", filetypes=[("CSV", "*.csv")])
        if not path:
            return
        rows: list[dict[str, str]] = []
        for line in self.event_timeline:
            if not self._event_matches_filter(line):
                continue
            stamp, _, message = line.partition(" | ")
            rows.append({"time": stamp.strip(), "event": message.strip()})
        try:
            with open(path, "w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=["time", "event"])
                writer.writeheader()
                writer.writerows(rows)
            self.log(f"Event timeline exported: {path}")
            self._record_event("Event CSV exported")
        except Exception as exc:
            messagebox.showerror("Export events failed", str(exc))

    def export_recovery_timeline_csv(self) -> None:
        path = filedialog.asksaveasfilename(defaultextension=".csv", filetypes=[("CSV", "*.csv")])
        if not path:
            return
        rows: list[dict[str, str]] = []
        for line in self.recovery_timeline:
            stamp, _, message = line.partition(" | ")
            rows.append({"time": stamp.strip(), "event": message.strip()})
        try:
            with open(path, "w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=["time", "event"])
                writer.writeheader()
                writer.writerows(rows)
            self.log(f"Recovery timeline exported: {path}")
            self._record_event("Recovery timeline CSV exported")
        except Exception as exc:
            messagebox.showerror("Export recovery timeline failed", str(exc))

    def _maybe_send_biome_alert(self, biome: str) -> None:
        if not self.biome_alerts_enabled_var.get():
            return
        tracked = self.rare_biome_var.get().strip().upper()
        if not tracked or biome != tracked:
            if self.rare_biome_alerted_state and self.rare_biome_alerted_state != tracked:
                self.rare_biome_alerted_state = ""
            if self.pending_rare_biome_name:
                self.pending_rare_biome_name = ""
                self.pending_rare_biome_since = 0.0
            return

        if self.current_biome_seen_at is not None and (time.time() - self.current_biome_seen_at) > 120:
            return

        if self.rare_biome_alerted_state == biome:
            return

        now = time.time()
        if self.runtime_rare_biome_confirm_enabled:
            if self.pending_rare_biome_name != biome:
                self.pending_rare_biome_name = biome
                self.pending_rare_biome_since = now
                self._record_event(f"Rare biome candidate: {biome}")
                return
            elapsed = now - self.pending_rare_biome_since
            if elapsed < self.runtime_rare_biome_confirm_seconds:
                return
        else:
            self.pending_rare_biome_name = ""
            self.pending_rare_biome_since = 0.0

        last = self.last_biome_alert_at.get(biome, 0.0)
        if now - last < self.biome_alert_cooldown_seconds:
            return
        self.last_biome_alert_at[biome] = now
        self.rare_biome_alerted_state = biome
        self._send_webhook(
            f"{APP_NAME} Rare Biome",
            f"Detected tracked rare biome: {biome}",
            channel="biome",
        )
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

    def _maybe_send_vendor_alert(self, vendor: str, source: str) -> None:
        if not self.runtime_vendor_alerts_enabled:
            return
        now = time.time()
        last = self.last_vendor_alert_at.get(vendor, 0.0)
        if (now - last) < self.runtime_vendor_alert_cooldown:
            return
        self.last_vendor_alert_at[vendor] = now
        readable = vendor.title()
        self.log(f"{readable} event detected ({source}).")
        self._record_event(f"Vendor alert: {readable} ({source})")
        self._send_webhook(
            f"{APP_NAME} {readable} Alert",
            f"Detected {readable} event from {source}.",
            channel="vendor",
        )

    def _set_current_biome(self, biome: str, source: str) -> None:
        if biome not in BIOME_COLOR_MAP:
            return
        changed = biome != self.current_biome_name
        if changed:
            self.pending_rare_biome_name = ""
            self.pending_rare_biome_since = 0.0
            self.rare_biome_alerted_state = ""
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
            vendor = self._extract_vendor_from_line(line)
            if vendor is not None:
                self._maybe_send_vendor_alert(vendor, "roblox-log")

        if detected_biome:
            self._set_current_biome(detected_biome, detected_source)
        elif self.current_biome_name == "GLITCHED":
            self._render_biome_badge()

    def _configured_webhook_url_map(self) -> dict[str, str]:
        return {
            "default": self.webhook_url_var.get().strip(),
            "biome": self.webhook_biome_url_var.get().strip(),
            "recovery": self.webhook_recovery_url_var.get().strip(),
            "health": self.webhook_health_url_var.get().strip(),
            "vendor": self.webhook_vendor_url_var.get().strip(),
        }

    def _configured_webhook_urls(self) -> list[str]:
        ordered: list[str] = []
        seen: set[str] = set()
        for value in self._configured_webhook_url_map().values():
            if not value or value in seen:
                continue
            ordered.append(value)
            seen.add(value)
        return ordered

    def _resolve_webhook_targets(self, channel: str) -> list[str]:
        routes = self._configured_webhook_url_map()
        targets: list[str] = []
        seen: set[str] = set()
        for key in (channel.strip().lower(), "default"):
            candidate = routes.get(key, "").strip()
            if not candidate or candidate in seen:
                continue
            targets.append(candidate)
            seen.add(candidate)
        return targets

    def _send_webhook(self, title: str, description: str, channel: str = "default") -> None:
        if self._enqueue_on_ui_thread(self._send_webhook, title, description, channel):
            return
        if not self.webhook_enabled_var.get():
            return
        targets = self._resolve_webhook_targets(channel)
        if not targets:
            return
        queued = False
        for url in targets:
            if not self._is_valid_webhook_url(url):
                self.log("Webhook skipped: configured URL is invalid.")
                continue
            self.webhook_queue.put((url, title, description, 0))
            queued = True
        if queued:
            self._ensure_webhook_worker()

    def _ensure_webhook_worker(self) -> None:
        if self.webhook_worker_running:
            return
        self.webhook_worker_running = True
        threading.Thread(target=self._webhook_worker, daemon=True).start()

    def _webhook_worker(self) -> None:
        while True:
            try:
                url, title, description, attempt = self.webhook_queue.get(timeout=0.4)
            except queue.Empty:
                self.webhook_worker_running = False
                if self.webhook_queue.empty():
                    return
                self.webhook_worker_running = True
                continue

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
            except Exception as exc:
                if attempt < 3:
                    delay = 2 ** attempt
                    time.sleep(delay)
                    self.webhook_queue.put((url, title, description, attempt + 1))
                else:
                    self.log(f"Webhook send failed after retries: {exc}")

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

    def apply_process_limiter_settings(self) -> None:
        try:
            if self.process_limiter_enabled_var.get():
                self.parse_process_limiter_cycle_ms()
                if not self.process_limiter_supported:
                    raise ValueError("Process limiter is unavailable on this Windows runtime.")
                if self.process_limiter_auto_mode_var.get():
                    self.process_limiter_target_percent_var.set("0")
                    self.process_limiter_only_when_running_var.set(False)
                else:
                    self.parse_process_limiter_target_percent()
        except Exception as exc:
            messagebox.showerror("Process limiter", str(exc))
            return
        self._sync_runtime_settings_from_ui()
        self._refresh_process_limiter_status()
        self.log("Process limiter settings applied.")

    def resume_all_limited_processes(self) -> None:
        resumed = self._process_limiter_resume_all(log_result=False)
        self.log(f"Process limiter resumed {resumed} suspended process(es).")
        self._refresh_process_limiter_status()

    def _refresh_process_limiter_tree(self) -> None:
        if not hasattr(self, "process_limiter_tree"):
            return
        with self.state_lock:
            windows = list(self.window_map)
            usernames = dict(self.pid_username)
            suspended = set(self.process_limiter_suspended_pids)
            boost_until = dict(self.process_limiter_boost_until_by_pid)
        now = time.time()
        rows: dict[int, tuple[str, str, str, str, str]] = {}
        for _hwnd, title, pid, _pname in windows:
            username = usernames.get(pid, "Unknown")
            state = "Suspended" if pid in suspended else "Active"
            boosted = boost_until.get(pid, 0.0)
            if boosted > now and state != "Suspended":
                state = "Boosted"
            boost_text = time.strftime("%H:%M:%S", time.localtime(boosted)) if boosted > now else "-"
            rows[pid] = (str(pid), username, state, boost_text, title[:120])

        tree = self.process_limiter_tree
        for item in tree.get_children():
            tree.delete(item)
        for pid in sorted(rows):
            tree.insert("", tk.END, values=rows[pid])

    def _refresh_process_limiter_status(self) -> None:
        with self.state_lock:
            total = len({pid for _hwnd, _title, pid, _pname in self.window_map})
            suspended = len(self.process_limiter_suspended_pids)
            enabled = self.runtime_process_limiter_enabled
            auto_mode = self.runtime_process_limiter_auto_mode
            only_running = self.runtime_process_limiter_only_when_running
            percent = self.runtime_process_limiter_target_percent
            cycle_ms = self.runtime_process_limiter_cycle_ms
            errors = self.process_limiter_last_error
            supports = self.process_limiter_supported
        if not supports:
            text = "Limiter unavailable on this runtime."
        elif not enabled:
            text = f"Limiter off | targets {total} | suspended {suspended}"
        else:
            scope = "run-only" if only_running else "always"
            if auto_mode:
                text = f"Limiter on (AUTO 0% freeze, {scope}) | targets {total} | suspended {suspended}"
            elif percent <= 0:
                text = f"Limiter on (0% freeze, {scope}) | targets {total} | suspended {suspended}"
            else:
                text = f"Limiter on ({percent}%/{cycle_ms}ms, {scope}) | targets {total} | suspended {suspended}"
            if errors:
                text += f" | last error: {errors[:80]}"
        self.process_limiter_status_var.set(text)
        self._refresh_process_limiter_tree()

    def _process_limiter_mark_error(self, message: str) -> None:
        now = time.time()
        should_log = False
        with self.state_lock:
            self.process_limiter_last_error = message
            if (now - self.process_limiter_last_error_at) >= 20:
                self.process_limiter_last_error_at = now
                should_log = True
        if should_log:
            self.log(f"Process limiter: {message}")

    def _process_limiter_target_pids_snapshot(self) -> set[int]:
        with self.state_lock:
            window_pids = {pid for _hwnd, _title, pid, _pname in self.window_map if pid > 0 and pid != os.getpid()}
        process_pids = {pid for pid in self._all_roblox_process_pids() if pid > 0 and pid != os.getpid()}
        if process_pids:
            return process_pids | window_pids
        return window_pids

    def _process_limiter_should_throttle(self) -> bool:
        if not self.runtime_process_limiter_enabled or not self.process_limiter_supported:
            return False
        if self.runtime_process_limiter_only_when_running and not self.is_running:
            return False
        return True

    def parse_process_limiter_target_percent(self) -> int:
        raw = self.process_limiter_target_percent_var.get().strip()
        try:
            value = int(raw)
        except ValueError as exc:
            raise ValueError("Process limiter target percent must be an integer.") from exc
        if value < 0 or value > 100:
            raise ValueError("Process limiter target percent must be between 0 and 100.")
        return value

    def parse_process_limiter_cycle_ms(self) -> int:
        raw = self.process_limiter_cycle_ms_var.get().strip()
        try:
            value = int(raw)
        except ValueError as exc:
            raise ValueError("Process limiter cycle must be an integer (ms).") from exc
        if value < 80 or value > 2000:
            raise ValueError("Process limiter cycle must be between 80 and 2000 ms.")
        return value

    def parse_instance_relaunch_grace_seconds(self) -> int:
        raw = self.instance_relaunch_grace_seconds_var.get().strip()
        try:
            value = int(raw)
        except ValueError as exc:
            raise ValueError("Auto-relaunch grace must be an integer (seconds).") from exc
        if value < 0 or value > 600:
            raise ValueError("Auto-relaunch grace must be between 0 and 600 seconds.")
        return value

    def parse_instance_relaunch_max_per_hour(self) -> int:
        raw = self.instance_relaunch_max_per_hour_var.get().strip()
        try:
            value = int(raw)
        except ValueError as exc:
            raise ValueError("Auto-relaunch max launches/hr must be an integer.") from exc
        if value < 1 or value > 120:
            raise ValueError("Auto-relaunch max launches/hr must be between 1 and 120.")
        return value

    def parse_vendor_alert_cooldown_seconds(self) -> int:
        raw = self.vendor_alert_cooldown_var.get().strip()
        try:
            value = int(raw)
        except ValueError as exc:
            raise ValueError("Vendor alert cooldown must be an integer (seconds).") from exc
        if value < 15 or value > 3600:
            raise ValueError("Vendor alert cooldown must be between 15 and 3600 seconds.")
        return value

    def parse_rare_biome_confirm_seconds(self) -> float:
        raw = self.rare_biome_confirm_seconds_var.get().strip()
        try:
            value = float(raw)
        except ValueError as exc:
            raise ValueError("Rare biome confirmation must be a number (seconds).") from exc
        if value < 0 or value > 60:
            raise ValueError("Rare biome confirmation must be between 0 and 60 seconds.")
        return value

    @staticmethod
    def _extract_private_server_code(raw: str) -> str:
        value = raw.strip()
        if not value:
            return ""

        def _extract_from_text(text: str, depth: int = 0) -> str:
            if depth > 3:
                return ""
            parsed = urlparse.urlparse(text)
            query_text = parsed.query
            if not query_text and "?" in text:
                query_text = text.split("?", 1)[1]
            if query_text:
                query = urlparse.parse_qs(query_text, keep_blank_values=False)
                for key in ("privateServerLinkCode", "linkCode", "code"):
                    values = query.get(key, [])
                    if values:
                        candidate = values[0].strip()
                        if candidate:
                            return candidate
                deep_values = query.get("deep_link_value", [])
                for deep_value in deep_values:
                    nested = urlparse.unquote(str(deep_value)).strip()
                    if not nested:
                        continue
                    nested_code = _extract_from_text(nested, depth + 1)
                    if nested_code:
                        return nested_code
            return ""

        code = _extract_from_text(value)
        if code:
            return code

        # Accept fragments like:
        # - "abcdef1234&type=Server"
        # - "code=abcdef1234&type=Server"
        token = value.split("#", 1)[0].split("?", 1)[0].strip()
        for prefix in ("privateServerLinkCode=", "linkCode=", "code="):
            if token.lower().startswith(prefix.lower()):
                token = token[len(prefix) :]
                break
        token = token.split("&", 1)[0].strip()
        if re.fullmatch(r"[A-Za-z0-9_-]{8,}", token):
            return token
        return ""

    def apply_private_server_target(self) -> None:
        raw_place_id = self.private_server_place_id_var.get().strip()
        raw_code = self.private_server_code_var.get().strip()
        if raw_place_id:
            try:
                place_id = int(raw_place_id)
            except ValueError:
                messagebox.showerror("Private server target", "Place ID must be a positive integer.")
                return
            if place_id <= 0:
                messagebox.showerror("Private server target", "Place ID must be a positive integer.")
                return
        link_code = self._extract_private_server_code(raw_code)
        if not link_code or not re.fullmatch(r"[A-Za-z0-9_-]{8,}", link_code):
            messagebox.showerror("Private server target", "Link code looks invalid. Paste only the code or a valid share URL.")
            return
        # Prefer Roblox share URL format for private server joins.
        target = f"https://www.roblox.com/share?code={urlparse.quote(link_code, safe='')}&type=Server"
        self.private_server_code_var.set(link_code)
        self.instance_relaunch_launch_target_var.set(target)
        self.log("Private server launch target applied.")
        self._record_event("Private server launch target updated")
        self._sync_runtime_settings_from_ui()

    @staticmethod
    def _is_valid_instance_relaunch_target(raw: str) -> bool:
        value = raw.strip()
        if not value:
            return True
        lowered = value.lower()
        if lowered.startswith("roblox://") or lowered.startswith("roblox-player://"):
            return True
        if lowered.startswith("https://www.roblox.com/") or lowered.startswith("https://roblox.com/"):
            return True
        if os.path.isfile(value):
            filename = os.path.basename(value).strip().lower()
            return filename in {"robloxplayerlauncher.exe", "robloxplayerbeta.exe"}
        return False

    def _sync_runtime_settings_from_ui(self) -> None:
        self.runtime_watchdog_enabled = bool(self.watchdog_enabled_var.get())
        if self.runtime_watchdog_enabled:
            try:
                self.runtime_no_window_threshold = self.parse_no_windows_watchdog_threshold()
            except Exception:
                pass
            try:
                self.runtime_jump_fail_threshold = self.parse_jump_fail_watchdog_threshold()
            except Exception:
                pass
        self.runtime_start_when_windows_found = bool(self.start_when_windows_found_var.get())
        self.runtime_recovery_enabled = bool(self.recovery_enabled_var.get())
        jump_mode = self.jump_mode_var.get().strip().lower()
        self.runtime_jump_mode = jump_mode if jump_mode in {"all", "round", "weighted"} else "all"
        self.runtime_safe_mode = bool(self.safe_mode_var.get())
        anti_pattern = self.anti_idle_pattern_var.get().strip().lower()
        self.runtime_anti_idle_pattern = (
            anti_pattern if anti_pattern in {"balanced", "subtle", "aggressive", "randomized"} else "balanced"
        )
        self.runtime_pause_enabled = bool(self.pause_enabled_var.get())
        self.runtime_pause_start = self.pause_start_var.get().strip()
        self.runtime_pause_end = self.pause_end_var.get().strip()
        self.runtime_process_limiter_enabled = bool(self.process_limiter_enabled_var.get()) and self.process_limiter_supported
        self.runtime_process_limiter_auto_mode = bool(self.process_limiter_auto_mode_var.get())
        self.runtime_process_limiter_only_when_running = bool(self.process_limiter_only_when_running_var.get())
        try:
            self.runtime_process_limiter_target_percent = self.parse_process_limiter_target_percent()
        except Exception:
            pass
        try:
            self.runtime_process_limiter_cycle_ms = self.parse_process_limiter_cycle_ms()
        except Exception:
            pass
        if self.runtime_process_limiter_auto_mode:
            self.runtime_process_limiter_only_when_running = False
            self.runtime_process_limiter_target_percent = 0
        self.runtime_instance_relaunch_enabled = bool(self.instance_relaunch_enabled_var.get())
        try:
            self.runtime_instance_relaunch_grace_seconds = self.parse_instance_relaunch_grace_seconds()
        except Exception:
            pass
        try:
            self.runtime_instance_relaunch_max_per_hour = self.parse_instance_relaunch_max_per_hour()
        except Exception:
            pass
        self.runtime_instance_relaunch_launch_target = self.instance_relaunch_launch_target_var.get().strip()
        self.runtime_account_roster_enabled = bool(self.account_roster_enabled_var.get())
        self.runtime_watchdog_standby_mode = bool(self.watchdog_standby_mode_var.get())
        self.runtime_vendor_alerts_enabled = bool(self.vendor_alerts_enabled_var.get())
        try:
            self.runtime_vendor_alert_cooldown = self.parse_vendor_alert_cooldown_seconds()
        except Exception:
            pass
        self.runtime_rare_biome_confirm_enabled = bool(self.rare_biome_confirm_enabled_var.get())
        try:
            self.runtime_rare_biome_confirm_seconds = self.parse_rare_biome_confirm_seconds()
        except Exception:
            pass

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

    def parse_no_windows_watchdog_threshold(self) -> int:
        raw = self.watchdog_no_windows_threshold_var.get().strip() or self.watchdog_threshold_var.get().strip()
        try:
            value = int(raw)
        except ValueError as exc:
            raise ValueError("No-window watchdog threshold must be an integer.") from exc
        if value < 1:
            raise ValueError("No-window watchdog threshold must be >= 1.")
        return value

    def parse_jump_fail_watchdog_threshold(self) -> int:
        raw = self.watchdog_jump_fail_threshold_var.get().strip() or self.watchdog_threshold_var.get().strip()
        try:
            value = int(raw)
        except ValueError as exc:
            raise ValueError("Jump-fail watchdog threshold must be an integer.") from exc
        if value < 1:
            raise ValueError("Jump-fail watchdog threshold must be >= 1.")
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
        self.parse_no_windows_watchdog_threshold()
        self.parse_jump_fail_watchdog_threshold()
        if self.health_alert_enabled_var.get():
            self.parse_health_alert_minutes()
        if self.autosave_enabled_var.get():
            self.parse_autosave_minutes()
        self.parse_manual_pause_minutes()
        self._validate_pause_schedule()
        if self.scheduler_enabled_var.get():
            self._scheduler_slots()
        if self.webhook_enabled_var.get():
            urls = self._configured_webhook_urls()
            if not urls:
                raise ValueError("Webhook is enabled but no webhook URL is configured.")
            for url in urls:
                if not self._is_valid_webhook_url(url):
                    raise ValueError("Webhook URL must be a valid HTTPS URL.")
        if self.process_limiter_enabled_var.get():
            if not self.process_limiter_supported:
                raise ValueError("Process limiter is enabled, but suspend/resume APIs are unavailable.")
            self.parse_process_limiter_cycle_ms()
            if not self.process_limiter_auto_mode_var.get():
                self.parse_process_limiter_target_percent()
        if self.vendor_alerts_enabled_var.get():
            self.parse_vendor_alert_cooldown_seconds()
        if self.rare_biome_confirm_enabled_var.get():
            self.parse_rare_biome_confirm_seconds()
        if self.instance_relaunch_enabled_var.get():
            self.parse_instance_relaunch_grace_seconds()
            self.parse_instance_relaunch_max_per_hour()
            target = self.instance_relaunch_launch_target_var.get().strip()
            if not self._is_valid_instance_relaunch_target(target):
                raise ValueError(
                    "Auto-relaunch target must be empty, a Roblox URL "
                    "(roblox://, roblox-player://, or https://www.roblox.com/...), "
                    "or a valid RobloxPlayer*.exe path."
                )

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
            f"{APP_NAME} detected a previous unclean shutdown.\n\nRestore settings from the latest auto-save snapshot?",
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
            text=f"Welcome to {APP_NAME}. Configure a safe baseline and save it in one step.",
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
        ttk.Combobox(grid, textvariable=jump_mode_var, values=["all", "round", "weighted"], state="readonly", width=10).grid(
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
                self.log("Global hotkeys enabled (Ctrl+Alt+S/J/R/T/1/2/3).")
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
            (5, "Load Profile 1", ord("1"), lambda: self._hotkey_load_profile(1)),
            (6, "Load Profile 2", ord("2"), lambda: self._hotkey_load_profile(2)),
            (7, "Load Profile 3", ord("3"), lambda: self._hotkey_load_profile(3)),
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

    def _hotkey_load_profile(self, slot: int) -> None:
        preset = "default"
        if slot == 1:
            preset = self.profile_hotkey_1_var.get().strip() or "default"
        elif slot == 2:
            preset = self.profile_hotkey_2_var.get().strip() or "default"
        elif slot == 3:
            preset = self.profile_hotkey_3_var.get().strip() or "default"
        self.preset_name_var.set(self._sanitize_preset_name(preset))
        self.load_preset()

    def toggle_hotkey_help(self) -> None:
        if self.hotkey_help_window is not None and self.hotkey_help_window.winfo_exists():
            self.hotkey_help_window.destroy()
            self.hotkey_help_window = None
            return
        window = tk.Toplevel(self.root)
        self.hotkey_help_window = window
        window.title("Hotkey Help")
        window.geometry("360x250")
        window.resizable(False, False)
        window.transient(self.root)
        container = ttk.Frame(window, padding=10)
        container.pack(fill="both", expand=True)
        ttk.Label(container, text=f"{APP_NAME} Global Hotkeys", font=("Segoe UI", 10, "bold")).pack(anchor="w")
        rows = [
            ("Ctrl+Alt+S", "Start / Stop"),
            ("Ctrl+Alt+J", "Jump Now"),
            ("Ctrl+Alt+R", "Refresh Instances"),
            ("Ctrl+Alt+T", "Minimize To Tray"),
            ("Ctrl+Alt+1", f"Load preset: {self.profile_hotkey_1_var.get().strip() or 'default'}"),
            ("Ctrl+Alt+2", f"Load preset: {self.profile_hotkey_2_var.get().strip() or 'default'}"),
            ("Ctrl+Alt+3", f"Load preset: {self.profile_hotkey_3_var.get().strip() or 'default'}"),
        ]
        for key, desc in rows:
            line = ttk.Frame(container)
            line.pack(fill="x", pady=2)
            ttk.Label(line, text=key, width=14).pack(side=tk.LEFT)
            ttk.Label(line, text=desc).pack(side=tk.LEFT)
        ttk.Label(
            container,
            text="Tip: if a hotkey does not register, another app may already own it.",
            wraplength=330,
        ).pack(anchor="w", pady=(10, 0))
        ttk.Button(container, text="Close", command=self.toggle_hotkey_help).pack(anchor="e", pady=(10, 0))

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
                if self._should_block_hotkey(label):
                    continue
                self._record_event(f"Hotkey: {label}")
                self.root.after(0, action)
        except Exception:
            pass
        self.root.after(120, self._poll_global_hotkeys)

    def _should_block_hotkey(self, label: str) -> bool:
        if not self.hotkey_guard_var.get():
            return False
        if label not in {"Start/Stop", "To Tray"}:
            return False
        hwnd = int(self.user32.GetForegroundWindow() or 0)
        if not self._is_roblox_hwnd(hwnd):
            return False
        now = time.time()
        if (now - self.hotkey_guard_last_block_at) >= 4.0:
            self.hotkey_guard_last_block_at = now
            self.log(f"Blocked hotkey '{label}' while Roblox was focused.")
            self._record_event(f"Hotkey blocked: {label}")
        return True

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

    @staticmethod
    def _singleton_event_names_for_session(session_id: int | None) -> tuple[str, ...]:
        names = {
            "Local\\ROBLOX_singletonEvent",
            "Global\\ROBLOX_singletonEvent",
            "ROBLOX_singletonEvent",
        }
        if session_id is not None and session_id >= 0:
            names.add(f"\\Sessions\\{session_id}\\BaseNamedObjects\\ROBLOX_singletonEvent")
            names.add(f"Sessions\\{session_id}\\BaseNamedObjects\\ROBLOX_singletonEvent")
        return tuple(names)

    def _current_session_id(self) -> int | None:
        session_id = wintypes.DWORD(0)
        ok = self.kernel32.ProcessIdToSessionId(wintypes.DWORD(os.getpid()), ctypes.byref(session_id))
        if not ok:
            return None
        return int(session_id.value)

    def _singleton_event_names(self) -> tuple[str, ...]:
        return self._singleton_event_names_for_session(self._current_session_id())

    def _all_roblox_process_pids(self) -> set[int]:
        pids: set[int] = set()
        candidate_names = {
            "robloxplayerbeta.exe",
            "windows10universal.exe",
            "robloxplayerlauncher.exe",
        }
        create_snapshot = self.kernel32.CreateToolhelp32Snapshot
        create_snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
        create_snapshot.restype = wintypes.HANDLE
        process_first = self.kernel32.Process32FirstW
        process_first.argtypes = [wintypes.HANDLE, ctypes.POINTER(_PROCESSENTRY32W)]
        process_first.restype = wintypes.BOOL
        process_next = self.kernel32.Process32NextW
        process_next.argtypes = [wintypes.HANDLE, ctypes.POINTER(_PROCESSENTRY32W)]
        process_next.restype = wintypes.BOOL

        snapshot = create_snapshot(TH32CS_SNAPPROCESS, 0)
        if snapshot == INVALID_HANDLE_VALUE or not snapshot:
            return pids
        try:
            entry = _PROCESSENTRY32W()
            entry.dwSize = ctypes.sizeof(_PROCESSENTRY32W)
            ok = bool(process_first(snapshot, ctypes.byref(entry)))
            while ok:
                image_name = str(entry.szExeFile).strip().lower()
                if image_name in candidate_names:
                    pids.add(int(entry.th32ProcessID))
                ok = bool(process_next(snapshot, ctypes.byref(entry)))
        except Exception:
            return pids
        finally:
            self.kernel32.CloseHandle(snapshot)
        return pids

    def _nt_query_object_text(self, handle: int, info_class: int) -> str | None:
        nt_query_object = getattr(self.ntdll, "NtQueryObject", None)
        if nt_query_object is None:
            return None
        nt_query_object.argtypes = [wintypes.HANDLE, wintypes.ULONG, ctypes.c_void_p, wintypes.ULONG, ctypes.POINTER(wintypes.ULONG)]
        nt_query_object.restype = ctypes.c_long

        needed = wintypes.ULONG(0)
        status = self._ntstatus_unsigned(int(nt_query_object(handle, info_class, None, 0, ctypes.byref(needed))))
        if status not in {STATUS_INFO_LENGTH_MISMATCH, STATUS_BUFFER_OVERFLOW, STATUS_BUFFER_TOO_SMALL}:
            return None
        size = max(needed.value, 512)
        buffer = ctypes.create_string_buffer(size)
        status = self._ntstatus_unsigned(int(nt_query_object(handle, info_class, buffer, size, ctypes.byref(needed))))
        if status != STATUS_SUCCESS:
            return None
        try:
            ustr = ctypes.cast(buffer, ctypes.POINTER(_UNICODE_STRING)).contents
            if not ustr.Buffer or ustr.Length <= 0:
                return ""
            return ctypes.wstring_at(ustr.Buffer, int(ustr.Length // 2))
        except Exception:
            return None

    def _query_object_type_name(self, handle: int) -> str | None:
        return self._nt_query_object_text(handle, OBJECT_TYPE_INFORMATION_CLASS)

    def _query_object_name(self, handle: int) -> str | None:
        return self._nt_query_object_text(handle, OBJECT_NAME_INFORMATION_CLASS)

    def _enumerate_system_handle_entries(self) -> list[tuple[int, int, int]]:
        entries = self._enumerate_system_handle_entries_extended()
        if entries:
            return entries
        # Fallback for environments where class 64 yields no parsable data.
        return self._enumerate_system_handle_entries_legacy()

    def _enumerate_system_handle_entries_extended(self) -> list[tuple[int, int, int]]:
        nt_query_system_information = getattr(self.ntdll, "NtQuerySystemInformation", None)
        if nt_query_system_information is None:
            return []
        nt_query_system_information.argtypes = [
            wintypes.ULONG,
            ctypes.c_void_p,
            wintypes.ULONG,
            ctypes.POINTER(wintypes.ULONG),
        ]
        nt_query_system_information.restype = ctypes.c_long

        size = 0x20000
        needed = wintypes.ULONG(0)
        while True:
            buffer = ctypes.create_string_buffer(size)
            status = self._ntstatus_unsigned(int(
                nt_query_system_information(
                    SYSTEM_EXTENDED_HANDLE_INFORMATION_CLASS,
                    buffer,
                    size,
                    ctypes.byref(needed),
                )
            ))
            if status == STATUS_SUCCESS:
                break
            if status not in {STATUS_INFO_LENGTH_MISMATCH, STATUS_BUFFER_OVERFLOW, STATUS_BUFFER_TOO_SMALL}:
                return []
            size = max(size * 2, int(needed.value) + 0x10000)
            if size > 64 * 1024 * 1024:
                return []

        raw = ctypes.string_at(buffer, size)
        ptr_size = ctypes.sizeof(ctypes.c_void_p)
        if len(raw) < ptr_size * 2:
            return []

        if ptr_size == 8:
            count = struct.unpack_from("<Q", raw, 0)[0]
            entry_fmt = "<QQQIHHII"
        else:
            count = struct.unpack_from("<I", raw, 0)[0]
            entry_fmt = "<IIIIHHII"
        entry_size = struct.calcsize(entry_fmt)
        offset = ptr_size * 2
        max_entries_by_size = (len(raw) - offset) // entry_size
        total = int(min(count, max_entries_by_size))

        entries: list[tuple[int, int, int]] = []
        for index in range(total):
            base = offset + (index * entry_size)
            parsed = struct.unpack_from(entry_fmt, raw, base)
            object_ptr = int(parsed[0])
            owner_pid = int(parsed[1])
            handle_value = int(parsed[2])
            if handle_value:
                entries.append((object_ptr, owner_pid, handle_value))
        return entries

    def _enumerate_system_handle_entries_legacy(self) -> list[tuple[int, int, int]]:
        nt_query_system_information = getattr(self.ntdll, "NtQuerySystemInformation", None)
        if nt_query_system_information is None:
            return []
        nt_query_system_information.argtypes = [
            wintypes.ULONG,
            ctypes.c_void_p,
            wintypes.ULONG,
            ctypes.POINTER(wintypes.ULONG),
        ]
        nt_query_system_information.restype = ctypes.c_long

        size = 0x10000
        needed = wintypes.ULONG(0)
        while True:
            buffer = ctypes.create_string_buffer(size)
            status = self._ntstatus_unsigned(int(
                nt_query_system_information(
                    SYSTEM_HANDLE_INFORMATION_CLASS,
                    buffer,
                    size,
                    ctypes.byref(needed),
                )
            ))
            if status == STATUS_SUCCESS:
                break
            if status not in {STATUS_INFO_LENGTH_MISMATCH, STATUS_BUFFER_OVERFLOW, STATUS_BUFFER_TOO_SMALL}:
                return []
            size = max(size * 2, int(needed.value) + 0x4000)
            if size > 64 * 1024 * 1024:
                return []

        raw = ctypes.string_at(buffer, size)
        if len(raw) < 4:
            return []
        count = struct.unpack_from("<I", raw, 0)[0]
        ptr_size = ctypes.sizeof(ctypes.c_void_p)
        if ptr_size == 8:
            entry_fmt = "<HHBBHQI4x"
            offsets = (8, 4)
        else:
            entry_fmt = "<HHBBHII"
            offsets = (4,)
        entry_size = struct.calcsize(entry_fmt)

        for offset in offsets:
            if len(raw) <= offset:
                continue
            max_entries_by_size = (len(raw) - offset) // entry_size
            total = int(min(count, max_entries_by_size))
            if total <= 0:
                continue
            out: list[tuple[int, int, int]] = []
            for index in range(total):
                base = offset + (index * entry_size)
                parsed = struct.unpack_from(entry_fmt, raw, base)
                owner_pid = int(parsed[0])
                handle_value = int(parsed[4])
                object_ptr = int(parsed[5])
                if handle_value:
                    out.append((object_ptr, owner_pid, handle_value))
            if out:
                return out
        return []

    def _enumerate_system_handles_for_pid(self, pid: int) -> list[int]:
        return [handle for _obj, owner_pid, handle in self._enumerate_system_handle_entries() if owner_pid == pid]

    def _singleton_event_object_ids(self) -> set[int]:
        open_event = self.kernel32.OpenEventW
        open_event.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
        open_event.restype = wintypes.HANDLE
        this_pid = os.getpid()
        opened_handles: list[int] = []
        for name in self._singleton_event_names():
            handle = open_event(SYNCHRONIZE, False, name)
            if handle:
                opened_handles.append(int(handle))
        if not opened_handles:
            return set()

        entries = self._enumerate_system_handle_entries()
        object_ids: set[int] = set()
        try:
            for raw_handle in opened_handles:
                for object_ptr, owner_pid, handle_value in entries:
                    if owner_pid == this_pid and handle_value == raw_handle and object_ptr:
                        object_ids.add(object_ptr)
                        break
        finally:
            for raw_handle in opened_handles:
                self.kernel32.CloseHandle(wintypes.HANDLE(raw_handle))
        return object_ids

    def _ensure_debug_privilege(self) -> bool:
        if self.debug_privilege_checked:
            return self.debug_privilege_enabled
        self.debug_privilege_checked = True
        self.debug_privilege_last_error = 0
        self.debug_privilege_last_stage = ""
        token = wintypes.HANDLE(0)
        ctypes.set_last_error(0)
        open_ok = self.advapi32.OpenProcessToken(
            self._current_process_pseudo_handle(),
            TOKEN_QUERY | TOKEN_ADJUST_PRIVILEGES,
            ctypes.byref(token),
        )
        if not open_ok or not token.value:
            self.debug_privilege_last_stage = "OpenProcessToken"
            self.debug_privilege_last_error = int(ctypes.get_last_error())
            return False
        try:
            luid = _LUID()
            name = ctypes.c_wchar_p("SeDebugPrivilege")
            ctypes.set_last_error(0)
            lookup_ok = self.advapi32.LookupPrivilegeValueW(None, name, ctypes.byref(luid))
            if not lookup_ok:
                self.debug_privilege_last_stage = "LookupPrivilegeValueW"
                self.debug_privilege_last_error = int(ctypes.get_last_error())
                return False
            token_privileges = _TOKEN_PRIVILEGES()
            token_privileges.PrivilegeCount = 1
            token_privileges.Privileges[0].Luid = luid
            token_privileges.Privileges[0].Attributes = SE_PRIVILEGE_ENABLED
            ctypes.set_last_error(0)
            adjust_ok = self.advapi32.AdjustTokenPrivileges(
                token,
                False,
                ctypes.byref(token_privileges),
                0,
                None,
                None,
            )
            if not adjust_ok:
                self.debug_privilege_last_stage = "AdjustTokenPrivileges"
                self.debug_privilege_last_error = int(ctypes.get_last_error())
                return False
            self.debug_privilege_last_error = int(ctypes.get_last_error())
            if self.debug_privilege_last_error == ERROR_NOT_ALL_ASSIGNED:
                self.debug_privilege_last_stage = "AdjustTokenPrivileges/NotAssigned"
                return False
            self.debug_privilege_enabled = True
            return True
        finally:
            self.kernel32.CloseHandle(token)

    def _close_singleton_event_handles_for_pids(self, pids: set[int]) -> tuple[int, int]:
        if not pids:
            return 0, 0
        self._ensure_debug_privilege()
        target_object_ids = self._singleton_event_object_ids()
        entries = self._enumerate_system_handle_entries()
        current_process = self._current_process_pseudo_handle()
        source_handles: dict[int, int] = {}
        matched = 0
        closed = 0
        try:
            for object_ptr, owner_pid, handle_value in entries:
                if owner_pid not in pids or object_ptr not in target_object_ids:
                    continue
                source_handle = source_handles.get(owner_pid)
                if source_handle is None:
                    source_handle = int(self.kernel32.OpenProcess(PROCESS_DUP_HANDLE, False, owner_pid))
                    source_handles[owner_pid] = source_handle
                if not source_handle:
                    continue
                matched += 1
                closed_dup = wintypes.HANDLE(0)
                close_ok = self.kernel32.DuplicateHandle(
                    wintypes.HANDLE(source_handle),
                    wintypes.HANDLE(handle_value),
                    current_process,
                    ctypes.byref(closed_dup),
                    0,
                    False,
                    DUPLICATE_SAME_ACCESS | DUPLICATE_CLOSE_SOURCE,
                )
                if close_ok:
                    closed += 1
                    if closed_dup.value:
                        self.kernel32.CloseHandle(closed_dup)
        finally:
            for handle in source_handles.values():
                if handle:
                    self.kernel32.CloseHandle(wintypes.HANDLE(handle))
        if matched == 0 and target_object_ids:
            return closed, matched
        if matched == 0:
            # Fallback: match by duplicated-handle object name like Process Explorer handle search.
            return self._close_named_singleton_event_handles_for_pids(pids)
        return closed, matched

    def _close_named_singleton_event_handles_for_pids(self, pids: set[int]) -> tuple[int, int]:
        entries = self._enumerate_system_handle_entries()
        current_process = self._current_process_pseudo_handle()
        source_handles: dict[int, int] = {}
        matched = 0
        closed = 0
        try:
            for _object_ptr, owner_pid, handle_value in entries:
                if owner_pid not in pids:
                    continue
                source_handle = source_handles.get(owner_pid)
                if source_handle is None:
                    source_handle = int(self.kernel32.OpenProcess(PROCESS_DUP_HANDLE, False, owner_pid))
                    source_handles[owner_pid] = source_handle
                if not source_handle:
                    continue
                duplicated = wintypes.HANDLE(0)
                dup_ok = self.kernel32.DuplicateHandle(
                    wintypes.HANDLE(source_handle),
                    wintypes.HANDLE(handle_value),
                    current_process,
                    ctypes.byref(duplicated),
                    0,
                    False,
                    DUPLICATE_SAME_ACCESS,
                )
                if not dup_ok or not duplicated.value:
                    continue
                try:
                    obj_type = self._query_object_type_name(int(duplicated.value))
                    if not obj_type or obj_type.strip().lower() != "event":
                        continue
                    obj_name = self._query_object_name(int(duplicated.value)) or ""
                    if "roblox_singletonevent" not in obj_name.lower():
                        continue
                    matched += 1
                    closed_dup = wintypes.HANDLE(0)
                    close_ok = self.kernel32.DuplicateHandle(
                        wintypes.HANDLE(source_handle),
                        wintypes.HANDLE(handle_value),
                        current_process,
                        ctypes.byref(closed_dup),
                        0,
                        False,
                        DUPLICATE_SAME_ACCESS | DUPLICATE_CLOSE_SOURCE,
                    )
                    if close_ok:
                        closed += 1
                        if closed_dup.value:
                            self.kernel32.CloseHandle(closed_dup)
                finally:
                    self.kernel32.CloseHandle(duplicated)
        finally:
            for handle in source_handles.values():
                if handle:
                    self.kernel32.CloseHandle(wintypes.HANDLE(handle))
        return closed, matched

    def _close_named_singleton_event_handles_globally(self) -> tuple[int, int]:
        # Process Explorer-style behavior: search all process handles by object name
        # and close matching source handles directly with DUPLICATE_CLOSE_SOURCE.
        entries = self._enumerate_system_handle_entries()
        self.singleton_scan_last_entries = len(entries)
        self.singleton_scan_last_open_process_ok = 0
        self.singleton_scan_last_open_process_fail = 0
        current_process = self._current_process_pseudo_handle()
        source_handles: dict[int, int] = {}
        matched = 0
        closed = 0
        try:
            for _object_ptr, owner_pid, handle_value in entries:
                source_handle = source_handles.get(owner_pid)
                if source_handle is None:
                    source_handle = int(self.kernel32.OpenProcess(PROCESS_DUP_HANDLE, False, owner_pid))
                    if source_handle:
                        self.singleton_scan_last_open_process_ok += 1
                    else:
                        self.singleton_scan_last_open_process_fail += 1
                    source_handles[owner_pid] = source_handle
                if not source_handle:
                    continue
                duplicated = wintypes.HANDLE(0)
                dup_ok = self.kernel32.DuplicateHandle(
                    wintypes.HANDLE(source_handle),
                    wintypes.HANDLE(handle_value),
                    current_process,
                    ctypes.byref(duplicated),
                    0,
                    False,
                    DUPLICATE_SAME_ACCESS,
                )
                if not dup_ok or not duplicated.value:
                    continue
                try:
                    obj_type = self._query_object_type_name(int(duplicated.value))
                    if not obj_type or obj_type.strip().lower() != "event":
                        continue
                    obj_name = self._query_object_name(int(duplicated.value)) or ""
                    if "roblox_singletonevent" not in obj_name.lower():
                        continue
                    matched += 1
                    closed_dup = wintypes.HANDLE(0)
                    close_ok = self.kernel32.DuplicateHandle(
                        wintypes.HANDLE(source_handle),
                        wintypes.HANDLE(handle_value),
                        current_process,
                        ctypes.byref(closed_dup),
                        0,
                        False,
                        DUPLICATE_SAME_ACCESS | DUPLICATE_CLOSE_SOURCE,
                    )
                    if close_ok:
                        closed += 1
                        if closed_dup.value:
                            self.kernel32.CloseHandle(closed_dup)
                finally:
                    self.kernel32.CloseHandle(duplicated)
        finally:
            for handle in source_handles.values():
                if handle:
                    self.kernel32.CloseHandle(wintypes.HANDLE(handle))
        return closed, matched

    def _close_singleton_event_handles_retry_window(self, duration_seconds: float = 2.0, interval_seconds: float = 0.25) -> tuple[int, int, int]:
        total_closed = 0
        total_matched = 0
        passes = 0
        deadline = time.perf_counter() + max(0.2, duration_seconds)
        sleep_seconds = min(0.5, max(0.2, interval_seconds))
        while time.perf_counter() < deadline:
            passes += 1
            closed, matched = self._close_named_singleton_event_handles_globally()
            total_closed += closed
            total_matched += matched
            state = self._probe_roblox_singleton_event_state()
            if state == "absent":
                break
            time.sleep(sleep_seconds)
        return total_closed, total_matched, passes

    def _probe_roblox_singleton_event_state(self) -> str:
        open_event = self.kernel32.OpenEventW
        open_event.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
        open_event.restype = wintypes.HANDLE
        inaccessible_seen = False
        for name in self._singleton_event_names():
            ctypes.set_last_error(0)
            handle = open_event(SYNCHRONIZE, False, name)
            if handle:
                self.kernel32.CloseHandle(handle)
                return "present"
            err = ctypes.get_last_error()
            if err == ERROR_ACCESS_DENIED:
                inaccessible_seen = True
            if err == ERROR_FILE_NOT_FOUND:
                continue
        return "inaccessible" if inaccessible_seen else "absent"

    def _try_delete_roblox_singleton_event_once(self) -> bool:
        access_modes = (DELETE_ACCESS, DELETE_ACCESS | EVENT_MODIFY_STATE, EVENT_ALL_ACCESS)
        nt_make_temporary = getattr(self.ntdll, "NtMakeTemporaryObject", None)
        if nt_make_temporary is not None:
            nt_make_temporary.argtypes = [wintypes.HANDLE]
            nt_make_temporary.restype = ctypes.c_long
        open_event = self.kernel32.OpenEventW
        open_event.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
        open_event.restype = wintypes.HANDLE

        for name in self._singleton_event_names():
            for access in access_modes:
                handle = open_event(access, False, name)
                if not handle:
                    continue
                try:
                    if nt_make_temporary is not None and int(nt_make_temporary(handle)) == 0:
                        return True
                finally:
                    self.kernel32.CloseHandle(handle)
        return False

    def _auto_delete_roblox_singleton_event(self, pids: set[int]) -> None:
        if not pids:
            return
        now = time.time()
        terminal_outcomes = {"deleted_or_not_present"}
        with self.state_lock:
            due_pids = {
                pid
                for pid in pids
                if self.singleton_cleanup_attempt_count_by_pid.get(pid, 0) < self.singleton_cleanup_max_attempts_per_pid
                and self.singleton_cleanup_last_outcome_by_pid.get(pid, "") not in terminal_outcomes
                if (now - self.singleton_cleanup_last_attempt_by_pid.get(pid, 0.0))
                >= self.singleton_cleanup_attempt_interval_seconds
            }
            if not due_pids:
                return
            for pid in due_pids:
                self.singleton_cleanup_last_attempt_by_pid[pid] = now
                self.singleton_cleanup_attempt_count_by_pid[pid] = self.singleton_cleanup_attempt_count_by_pid.get(pid, 0) + 1
        before = self._probe_roblox_singleton_event_state()
        attempt_ok = self._try_delete_roblox_singleton_event_once()
        after = self._probe_roblox_singleton_event_state()
        force_closed = 0
        force_matched = 0
        debug_ok = self._ensure_debug_privilege()
        if after in {"present", "inaccessible"} and debug_ok:
            force_closed, force_matched = self._close_singleton_event_handles_for_pids(due_pids)
            after = self._probe_roblox_singleton_event_state()
            if after in {"present", "inaccessible"}:
                global_closed, global_matched, retry_passes = self._close_singleton_event_handles_retry_window(
                    duration_seconds=2.0,
                    interval_seconds=0.25,
                )
                force_closed += global_closed
                force_matched += global_matched
                after = self._probe_roblox_singleton_event_state()
            else:
                retry_passes = 0
        else:
            retry_passes = 0

        if after == "absent":
            outcome = "deleted_or_not_present"
        elif after == "present":
            outcome = "still_exists"
        elif after == "inaccessible" and not debug_ok:
            outcome = "debug_privilege_missing"
        else:
            outcome = "cannot_verify"

        with self.state_lock:
            changed_pids = [pid for pid in sorted(due_pids) if self.singleton_cleanup_last_outcome_by_pid.get(pid) != outcome]
            for pid in changed_pids:
                self.singleton_cleanup_last_outcome_by_pid[pid] = outcome
        if changed_pids:
            pid_list = ",".join(str(pid) for pid in changed_pids)
            self.log(
                "Auto-cleanup PIDs "
                f"[{pid_list}]: {outcome} "
                f"(before={before}, attempt_ok={attempt_ok}, force_closed={force_closed}/{force_matched}, "
                f"retry_passes={retry_passes}, after={after}, debug_priv={self.debug_privilege_enabled}, "
                f"debug_stage={self.debug_privilege_last_stage}, debug_err={self.debug_privilege_last_error}, "
                f"scan_entries={self.singleton_scan_last_entries}, openproc_ok={self.singleton_scan_last_open_process_ok}, "
                f"openproc_fail={self.singleton_scan_last_open_process_fail})."
            )

    def _enqueue_singleton_cleanup(self, pids: set[int]) -> None:
        clean_pids = {pid for pid in pids if pid > 0}
        if not clean_pids:
            return
        start_worker = False
        with self.state_lock:
            self.singleton_cleanup_pending_pids.update(clean_pids)
            if not self.singleton_cleanup_inflight:
                self.singleton_cleanup_inflight = True
                start_worker = True
        if not start_worker:
            return
        threading.Thread(target=self._singleton_cleanup_worker, daemon=True).start()

    def _singleton_cleanup_worker(self) -> None:
        while True:
            with self.state_lock:
                pids = set(self.singleton_cleanup_pending_pids)
                self.singleton_cleanup_pending_pids.clear()
            if not pids:
                with self.state_lock:
                    self.singleton_cleanup_inflight = False
                return
            try:
                self._auto_delete_roblox_singleton_event(pids)
            except Exception as exc:
                self.log(f"Singleton cleanup worker error: {exc}")

    def find_roblox_windows(self) -> list[tuple[int, str, int, str]]:
        windows: list[tuple[int, str, int, str]] = []
        roblox_pids: set[int] = set()
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
                roblox_pids.add(pid)
                windows.append((int(hwnd), title, pid, process_name))
            return True

        callback = enum_proc(_enum_cb)
        self.user32.EnumWindows(callback, 0)
        roblox_pids.update(self._all_roblox_process_pids())
        self._enqueue_singleton_cleanup(roblox_pids)
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

    def _extract_username_candidates_from_text(self, text: str, max_results: int = 16) -> list[str]:
        candidates: list[str] = []
        seen: set[str] = set()
        for pattern in self.username_patterns:
            for match in pattern.finditer(text):
                username = match.group(1).strip()
                lower = username.lower()
                if not username or lower in self.excluded_usernames or lower in seen:
                    continue
                seen.add(lower)
                candidates.append(username)
                if len(candidates) >= max_results:
                    return candidates
        return candidates

    def _extract_user_id_candidates_from_text(self, text: str, max_results: int = 12) -> list[int]:
        candidates: list[int] = []
        seen: set[int] = set()
        for pattern in self.user_id_patterns:
            for match in pattern.finditer(text):
                try:
                    user_id = int(match.group(1))
                except ValueError:
                    continue
                if user_id <= 0 or user_id in seen:
                    continue
                seen.add(user_id)
                candidates.append(user_id)
                if len(candidates) >= max_results:
                    return candidates
        return candidates

    @staticmethod
    def _parse_log_start_epoch_from_filename(path_or_name: str) -> float | None:
        filename = os.path.basename(path_or_name)
        match = re.search(r"_(\d{8}T\d{6})Z_", filename)
        if not match:
            return None
        try:
            timestamp = datetime.strptime(match.group(1), "%Y%m%dT%H%M%S").replace(tzinfo=timezone.utc)
        except ValueError:
            return None
        return timestamp.timestamp()

    def _get_process_create_time(self, pid: int) -> float | None:
        cached = self.pid_create_time_cache.get(pid)
        if cached is not None:
            return cached
        handle = int(self.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid))
        if not handle:
            return None
        try:
            creation = wintypes.FILETIME()
            exit_time = wintypes.FILETIME()
            kernel_time = wintypes.FILETIME()
            user_time = wintypes.FILETIME()
            ok = bool(
                self.kernel32.GetProcessTimes(
                    handle,
                    ctypes.byref(creation),
                    ctypes.byref(exit_time),
                    ctypes.byref(kernel_time),
                    ctypes.byref(user_time),
                )
            )
            if not ok:
                return None
            ticks = (int(creation.dwHighDateTime) << 32) | int(creation.dwLowDateTime)
            if ticks <= 0:
                return None
            epoch = (ticks - 116444736000000000) / 10_000_000
            self.pid_create_time_cache[pid] = epoch
            return epoch
        finally:
            self.kernel32.CloseHandle(handle)

    def _is_log_claimed_by_other_pid(self, pid: int, log_path: str) -> bool:
        target = os.path.normcase(os.path.abspath(log_path))
        with self.state_lock:
            active_pids = {active_pid for _hwnd, _title, active_pid, _pname in self.window_map}
            for other_pid, hinted_path in self.pid_log_hint.items():
                if other_pid == pid or other_pid not in active_pids:
                    continue
                if os.path.normcase(os.path.abspath(hinted_path)) == target:
                    return True
        return False

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
        process_start = self._get_process_create_time(pid)
        hint = self.pid_log_hint.get(pid)
        hint_norm = os.path.normcase(os.path.abspath(hint)) if hint else ""

        ranked_entries: list[list[float | str]] = []
        for mtime, full in candidates[:150]:
            filename = os.path.basename(full)
            filename_lower = filename.lower()
            normalized = os.path.normcase(os.path.abspath(full))
            score = 0.0

            if hint_norm and normalized == hint_norm:
                score += 1_000_000.0
            if (
                f"_{pid_hex_upper}_" in filename
                or f"_{pid_hex_lower}_" in filename_lower
                or f"_{pid_hex_upper}." in filename
                or f"_{pid_hex_lower}." in filename_lower
            ):
                score += 250_000.0

            if "_player_" in filename_lower:
                score += 10_000.0

            log_start = self._parse_log_start_epoch_from_filename(filename)
            if process_start is not None and log_start is not None:
                delta = abs(log_start - process_start)
                # Strongly prefer logs created near process start time.
                score += max(0.0, 120_000.0 - min(delta, 1200.0) * 100.0)

            if self._is_log_claimed_by_other_pid(pid, full):
                score -= 200_000.0

            ranked_entries.append([score, mtime, full])

        ranked_entries.sort(key=lambda item: (float(item[0]), float(item[1])), reverse=True)

        # Lightweight header probe for PID markers on top candidates.
        for entry in ranked_entries[:40]:
            score = float(entry[0])
            full = str(entry[2])
            if score >= 300_000.0:
                continue
            try:
                with open(full, "r", encoding="utf-8", errors="ignore") as f:
                    header = f.read(65536)
            except OSError:
                continue
            if f"pid:{pid}" in header or f"PID: {pid}" in header:
                entry[0] = score + 300_000.0

        ranked_entries.sort(key=lambda item: (float(item[0]), float(item[1])), reverse=True)
        ranked = [str(path) for _score, _mtime, path in ranked_entries[:40]]

        if hint and os.path.exists(hint) and hint not in ranked:
            ranked = [hint] + ranked
        return ranked

    def _is_user_id_claimed_by_other_pid(self, pid: int, user_id: int) -> bool:
        with self.state_lock:
            active_pids = {active_pid for _hwnd, _title, active_pid, _pname in self.window_map}
            for other_pid, other_uid in self.pid_user_id.items():
                if other_pid == pid or other_pid not in active_pids:
                    continue
                if other_uid == user_id:
                    return True
        return False

    def _is_username_claimed_by_other_pid(self, pid: int, username: str) -> bool:
        name = username.strip().lower()
        if not name:
            return False
        with self.state_lock:
            active_pids = {active_pid for _hwnd, _title, active_pid, _pname in self.window_map}
            for other_pid, other_username in self.pid_username.items():
                if other_pid == pid or other_pid not in active_pids:
                    continue
                if other_username.strip().lower() == name:
                    return True
        return False

    def _detect_username_for_pid(self, pid: int) -> tuple[str | None, int | None, str]:
        fallback_username: str | None = None
        api_attempts = 0
        api_attempt_limit = 12
        for log_path in self._find_candidate_logs_for_pid(pid):
            if self._is_log_claimed_by_other_pid(pid, log_path):
                continue
            try:
                with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
                    text = f.read(2_000_000)
            except OSError:
                continue
            user_id_candidates = self._extract_user_id_candidates_from_text(text)
            user_id_set = set(user_id_candidates)
            username_candidates = self._extract_username_candidates_from_text(text)
            if fallback_username is None and username_candidates:
                fallback_username = username_candidates[0]

            # Best-effort pairing: if log has both username-like and userid-like signals,
            # keep only usernames that resolve to one of the observed user IDs.
            for username in username_candidates:
                if api_attempts >= api_attempt_limit:
                    break
                api_attempts += 1
                resolved_user_id = self._resolve_user_id(username)
                if resolved_user_id is None:
                    continue
                if user_id_set and resolved_user_id not in user_id_set:
                    continue
                if self._is_user_id_claimed_by_other_pid(pid, resolved_user_id):
                    continue
                self.pid_log_hint[pid] = log_path
                return username, resolved_user_id, "api"

            for user_id in user_id_candidates:
                if self._is_user_id_claimed_by_other_pid(pid, user_id):
                    continue
                resolved_name = self._resolve_username_from_user_id(user_id)
                if resolved_name:
                    self.pid_log_hint[pid] = log_path
                    return resolved_name, user_id, "api"
            for username in username_candidates:
                if api_attempts >= api_attempt_limit:
                    break
                api_attempts += 1
                user_id = self._resolve_user_id(username)
                if user_id is not None:
                    if self._is_user_id_claimed_by_other_pid(pid, user_id):
                        continue
                    self.pid_log_hint[pid] = log_path
                    return username, user_id, "api"
        if fallback_username is not None:
            return fallback_username, None, "log"
        return None, None, "unknown"

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

    def _resolve_username_from_user_id(self, user_id: int) -> str | None:
        data = self._fetch_json(f"https://users.roblox.com/v1/users/{user_id}")
        if not data:
            return None
        username = data.get("name")
        if not isinstance(username, str):
            return None
        username = username.strip()
        if not username or username.lower() in self.excluded_usernames:
            return None
        return username

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
        with self.state_lock:
            if pid in self.identity_lookup_inflight:
                return
            self.identity_lookup_inflight.add(pid)
            self.identity_last_attempt[pid] = time.time()
        threading.Thread(target=self._identity_lookup_worker, args=(pid,), daemon=True).start()

    def _identity_lookup_worker(self, pid: int) -> None:
        try:
            username, user_id, confidence = self._detect_username_for_pid(pid)
            avatar_bytes: bytes | None = None
            if user_id is not None:
                avatar_bytes = self._resolve_avatar_bytes(user_id)
            self._enqueue_on_ui_thread(self._apply_identity_result, pid, username, user_id, confidence, avatar_bytes)
        except Exception as exc:
            self.log(f"Identity lookup worker error for PID {pid}: {exc}")
            self._enqueue_on_ui_thread(self._apply_identity_result, pid, None, None, "error", None)

    def _apply_identity_result(
        self,
        pid: int,
        username: str | None,
        user_id: int | None,
        confidence: str,
        avatar_bytes: bytes | None,
    ) -> None:
        conflict_reason = ""
        with self.state_lock:
            self.identity_lookup_inflight.discard(pid)
            active_pids = {active_pid for _hwnd, _title, active_pid, _pname in self.window_map}
            if user_id is not None:
                owner_pid = next(
                    (
                        other_pid
                        for other_pid, other_uid in self.pid_user_id.items()
                        if other_pid != pid and other_pid in active_pids and other_uid == user_id
                    ),
                    None,
                )
                if owner_pid is not None:
                    conflict_reason = f"user_id {user_id} already mapped to PID {owner_pid}"
            if not conflict_reason and username:
                uname = username.strip().lower()
                owner_pid = next(
                    (
                        other_pid
                        for other_pid, other_name in self.pid_username.items()
                        if other_pid != pid and other_pid in active_pids and other_name.strip().lower() == uname
                    ),
                    None,
                )
                if owner_pid is not None:
                    conflict_reason = f"username '{username}' already mapped to PID {owner_pid}"

            if conflict_reason:
                self.pid_username.pop(pid, None)
                self.pid_user_id.pop(pid, None)
                self.pid_log_hint.pop(pid, None)
                self.pid_identity_confidence[pid] = "conflict"
                self.identity_last_attempt[pid] = max(0.0, time.time() - 10.0)
            else:
                if username:
                    self.pid_username[pid] = username
                    self.enabled_by_username.setdefault(username.lower(), True)
                    cached = self.override_by_username.get(username.lower())
                    if isinstance(cached, dict):
                        cached_interval = cached.get("interval")
                        if isinstance(cached_interval, (float, int)) and cached_interval > 0:
                            self.instance_interval_override[pid] = float(cached_interval)
                        cached_pattern = cached.get("pattern")
                        if isinstance(cached_pattern, str) and cached_pattern in {"balanced", "subtle", "aggressive", "randomized"}:
                            self.instance_pattern_override[pid] = cached_pattern
                        cached_priority = cached.get("priority")
                        if isinstance(cached_priority, int) and 1 <= cached_priority <= 9:
                            self.instance_priority_by_pid[pid] = cached_priority
                self.pid_identity_confidence[pid] = confidence
                if user_id is not None:
                    self.pid_user_id[pid] = user_id
        if conflict_reason:
            now = time.time()
            should_log = False
            with self.state_lock:
                if (now - self.identity_conflict_last_log_at) >= 8.0:
                    self.identity_conflict_last_log_at = now
                    should_log = True
            if should_log:
                self.log(f"Identity conflict for PID {pid}: {conflict_reason}. Marked as conflict; will retry.")
            self.refresh_instance_list(manual=False)
            return
        if avatar_bytes:
            try:
                encoded = base64.b64encode(avatar_bytes).decode("ascii")
                image = tk.PhotoImage(data=encoded, format="png")
                if image.width() > 32:
                    step = max(1, (image.width() + 31) // 32)
                    image = cast(tk.PhotoImage, image.subsample(step))
                with self.state_lock:
                    self.pid_avatar_photo[pid] = image
            except tk.TclError:
                pass
        self.refresh_instance_list(manual=False)

    def refresh_instance_list(self, manual: bool) -> None:
        if self._enqueue_on_ui_thread(self.refresh_instance_list, manual):
            return
        scanned_windows = self.find_roblox_windows()
        with self.state_lock:
            previous_count = len(self.window_map)
            old_map = {hwnd: (title, pid, pname) for hwnd, title, pid, pname in self.window_map}
            self.window_map = scanned_windows
            self.last_instance_scan_at = time.time()

            for old_hwnd, (_title, old_pid, _pname) in old_map.items():
                username = self.pid_username.get(old_pid)
                if username:
                    uname = username.lower()
                    self.enabled_by_username[uname] = self.instance_enabled_by_hwnd.get(old_hwnd, True)
                    self.override_by_username[uname] = {
                        "interval": self.instance_interval_override.get(old_pid),
                        "pattern": self.instance_pattern_override.get(old_pid),
                        "priority": self.instance_priority_by_pid.get(old_pid, 1),
                    }

            active_hwnds = {hwnd for hwnd, _, _, _ in self.window_map}
            active_pids = {pid for _hwnd, _title, pid, _pname in self.window_map}
            self.instance_enabled_by_hwnd = {
                hwnd: enabled for hwnd, enabled in self.instance_enabled_by_hwnd.items() if hwnd in active_hwnds
            }
            self.instance_last_jump = {hwnd: ts for hwnd, ts in self.instance_last_jump.items() if hwnd in active_hwnds}
            self.instance_send_fail_streak = {
                hwnd: count for hwnd, count in self.instance_send_fail_streak.items() if hwnd in active_hwnds
            }
            self.instance_recovery_tier_by_hwnd = {
                hwnd: tier for hwnd, tier in self.instance_recovery_tier_by_hwnd.items() if hwnd in active_hwnds
            }
            self.instance_recovery_last_log_at = {
                hwnd: ts for hwnd, ts in self.instance_recovery_last_log_at.items() if hwnd in active_hwnds
            }
            now = time.time()
            self.roblox_input_pause_until_by_hwnd = {
                hwnd: ts for hwnd, ts in self.roblox_input_pause_until_by_hwnd.items() if hwnd in active_hwnds and ts > now
            }
            self.roblox_input_pause_logged_hwnds = {
                hwnd for hwnd in self.roblox_input_pause_logged_hwnds if hwnd in self.roblox_input_pause_until_by_hwnd
            }
            self.pid_log_hint = {pid: path for pid, path in self.pid_log_hint.items() if pid in active_pids}
            self.pid_equipped_aura = {pid: aura for pid, aura in self.pid_equipped_aura.items() if pid in active_pids}
            self.pid_aura_log_path = {pid: path for pid, path in self.pid_aura_log_path.items() if pid in active_pids}
            self.pid_aura_log_offset = {pid: offset for pid, offset in self.pid_aura_log_offset.items() if pid in active_pids}
            self.pid_aura_log_discovery_last_attempt = {
                pid: ts for pid, ts in self.pid_aura_log_discovery_last_attempt.items() if pid in active_pids
            }
            self.pid_create_time_cache = {pid: ts for pid, ts in self.pid_create_time_cache.items() if pid in active_pids}
            self.singleton_cleanup_last_attempt_by_pid = {
                pid: ts for pid, ts in self.singleton_cleanup_last_attempt_by_pid.items() if pid in active_pids
            }
            self.singleton_cleanup_attempt_count_by_pid = {
                pid: count for pid, count in self.singleton_cleanup_attempt_count_by_pid.items() if pid in active_pids
            }
            self.singleton_cleanup_last_outcome_by_pid = {
                pid: outcome for pid, outcome in self.singleton_cleanup_last_outcome_by_pid.items() if pid in active_pids
            }
            self.process_limiter_boost_until_by_pid = {
                pid: ts
                for pid, ts in self.process_limiter_boost_until_by_pid.items()
                if pid in active_pids and ts > now
            }

            for hwnd, _title, pid, _pname in self.window_map:
                if hwnd not in self.instance_enabled_by_hwnd:
                    username = self.pid_username.get(pid, "").lower()
                    if username and username in self.enabled_by_username:
                        self.instance_enabled_by_hwnd[hwnd] = self.enabled_by_username[username]
                    else:
                        self.instance_enabled_by_hwnd[hwnd] = self.loaded_enabled_by_pid.get(pid, True)
                username = self.pid_username.get(pid, "").lower()
                if username and username in self.override_by_username:
                    cached = self.override_by_username[username]
                    cached_interval = cached.get("interval")
                    if isinstance(cached_interval, (float, int)) and cached_interval > 0:
                        self.instance_interval_override[pid] = float(cached_interval)
                    cached_pattern = cached.get("pattern")
                    if isinstance(cached_pattern, str) and cached_pattern in {"balanced", "subtle", "aggressive", "randomized"}:
                        self.instance_pattern_override[pid] = cached_pattern
                    cached_priority = cached.get("priority")
                    if isinstance(cached_priority, int) and 1 <= cached_priority <= 9:
                        self.instance_priority_by_pid[pid] = cached_priority

            window_snapshot = list(self.window_map)
        self._poll_equipped_auras(pids=active_pids, force=manual)
        for item in self.instance_tree.get_children():
            self.instance_tree.delete(item)

        for hwnd, title, pid, pname in sorted(window_snapshot, key=lambda x: x[2]):
            enabled = self.instance_enabled_by_hwnd.get(hwnd, True)
            username = self.pid_username.get(pid)
            if not username:
                username = "Detecting..." if pid in self.identity_lookup_inflight else "Unknown"
            confidence = self.pid_identity_confidence.get(pid, "unknown")
            aura = self.pid_equipped_aura.get(pid, "-")
            priority = self.instance_priority_by_pid.get(pid, 1)
            last_jump = self.instance_last_jump.get(hwnd)
            last_jump_str = time.strftime("%H:%M:%S", time.localtime(last_jump)) if last_jump else "-"
            avatar = self.pid_avatar_photo.get(pid)
            values = (
                "Yes" if enabled else "No",
                str(priority),
                str(pid),
                str(hwnd),
                pname or "unknown.exe",
                username,
                confidence,
                aura,
                last_jump_str,
                title[:100],
            )
            item_id = self.instance_tree.insert("", tk.END, iid=str(hwnd), text="", image=avatar if avatar else "")
            self.instance_tree.item(item_id, values=list(values))

        now = time.time()
        pids = {pid for _hwnd, _title, pid, _pname in window_snapshot}
        lookup_started = False
        for pid in pids:
            if pid in self.pid_username:
                continue
            if pid in self.identity_lookup_inflight:
                continue
            if now - self.identity_last_attempt.get(pid, 0) >= 20:
                self._start_identity_lookup(pid)
                lookup_started = True
            if lookup_started:
                # Avoid racing multiple workers against the same newest log file.
                break

        if len(window_snapshot) != self.last_window_count:
            self.last_window_count = len(window_snapshot)
            self.log(f"Detected Roblox windows: {len(window_snapshot)}")

        if self.auto_realign_var.get() and len(window_snapshot) > 0 and len(window_snapshot) != previous_count:
            self.align_windows(log_result=False)
            self.log("Auto-realigned windows after instance count change.")

        self._refresh_account_roster_status()
        self.update_health_panel()
        self._refresh_process_limiter_status()
        if manual:
            self.log("Instance list refreshed.")

    def update_health_panel(self) -> None:
        with self.state_lock:
            window_snapshot = list(self.window_map)
            enabled_by_hwnd = dict(self.instance_enabled_by_hwnd)
            username_by_pid = dict(self.pid_username)
            user_id_by_pid = dict(self.pid_user_id)
            confidence_by_pid = dict(self.pid_identity_confidence)
            last_jump_by_hwnd = dict(self.instance_last_jump)
            attempt_by_hwnd = dict(self.instance_attempt_count)
            fail_by_hwnd = dict(self.instance_fail_count)
            send_fail_streak_by_hwnd = dict(self.instance_send_fail_streak)
            recovery_tier_by_hwnd = dict(self.instance_recovery_tier_by_hwnd)
            priority_by_pid = dict(self.instance_priority_by_pid)
            quarantine_until_by_hwnd = dict(self.instance_quarantine_until)
            roster_enabled = bool(self.account_roster_enabled_var.get())
            roster_ids = set(self.account_roster_user_ids)
            roster_names = dict(self.account_roster_names_by_user_id)
        lines: list[str] = []
        biome_seen = "-"
        if self.current_biome_seen_at is not None:
            biome_seen = time.strftime("%H:%M:%S", time.localtime(self.current_biome_seen_at))
        lines.append(f"Biome {self.current_biome_name} | source {self.current_biome_source} | seen {biome_seen}")
        if roster_enabled and roster_ids:
            active_pids = {pid for _hwnd, _title, pid, _pname in window_snapshot}
            active_user_ids = {user_id_by_pid[pid] for pid in active_pids if pid in user_id_by_pid}
            missing_ids = sorted(user_id for user_id in roster_ids if user_id not in active_user_ids)
            lines.append(f"Roster {len(roster_ids)} locked | missing {len(missing_ids)}")
            if missing_ids:
                labels = []
                for user_id in missing_ids[:4]:
                    label = roster_names.get(user_id, "").strip()
                    labels.append(f"{label} ({user_id})" if label else str(user_id))
                suffix = ", ..." if len(missing_ids) > 4 else ""
                lines.append("Missing accounts: " + ", ".join(labels) + suffix)
        if not window_snapshot:
            lines.append("No Roblox instances detected.")
        else:
            enabled_count = 0
            for hwnd, title, pid, _pname in window_snapshot:
                enabled = enabled_by_hwnd.get(hwnd, True)
                if enabled:
                    enabled_count += 1
                username = username_by_pid.get(pid, "unknown")
                confidence = confidence_by_pid.get(pid, "unknown")
                last_jump = last_jump_by_hwnd.get(hwnd)
                last_jump_str = time.strftime("%H:%M:%S", time.localtime(last_jump)) if last_jump else "never"
                age_str = "-"
                if last_jump is not None:
                    age = int(max(0, time.time() - last_jump))
                    age_str = f"{age}s"
                attempts = attempt_by_hwnd.get(hwnd, 0)
                fails = fail_by_hwnd.get(hwnd, 0)
                send_fail_streak = send_fail_streak_by_hwnd.get(hwnd, 0)
                recovery_tier = recovery_tier_by_hwnd.get(hwnd, 0)
                priority = priority_by_pid.get(pid, 1)
                reliability = "n/a" if attempts == 0 else f"{max(0.0, (attempts - fails) * 100 / attempts):.0f}%"
                quarantine_left = max(0, int(quarantine_until_by_hwnd.get(hwnd, 0.0) - time.time()))
                quarantine_text = f" | quarantine {quarantine_left}s" if quarantine_left > 0 else ""
                recovery_text = ""
                if send_fail_streak > 0:
                    recovery_text = f" | recovery t{recovery_tier} streak {send_fail_streak}"
                status = "ENABLED" if enabled else "DISABLED"
                lines.append(
                    f"PID {pid} | prio {priority} | {username} ({confidence}) | HWND {hwnd} | {status} | last jump {last_jump_str} ({age_str}) | reliability {reliability}{quarantine_text}{recovery_text} | {title[:20]}"
                )
            lines.insert(1, f"Enabled {enabled_count}/{len(window_snapshot)} instances")

        self.health_text.configure(state=tk.NORMAL)
        self.health_text.delete("1.0", tk.END)
        self.health_text.insert(tk.END, "\n".join(lines))
        self.health_text.configure(state=tk.DISABLED)

    def _toggle_hwnd_enabled(self, hwnd: int) -> None:
        with self.state_lock:
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
            with self.state_lock:
                pid = next((pid for h, _t, pid, _p in self.window_map if h == hwnd), None)
            if pid is None:
                continue
            with self.state_lock:
                self.pid_username.pop(pid, None)
                self.pid_user_id.pop(pid, None)
                self.pid_avatar_photo.pop(pid, None)
                self.pid_identity_confidence.pop(pid, None)
                self.identity_last_attempt[pid] = 0
            self._start_identity_lookup(pid)
        self.log("Requested identity retry for selected instances.")

    def enable_all_instances(self) -> None:
        with self.state_lock:
            for hwnd, _title, pid, _pname in self.window_map:
                self.instance_enabled_by_hwnd[hwnd] = True
                username = self.pid_username.get(pid)
                if username:
                    self.enabled_by_username[username.lower()] = True
        self.refresh_instance_list(manual=False)
        self.log("Enabled all detected instances.")

    def disable_all_instances(self) -> None:
        with self.state_lock:
            for hwnd, _title, pid, _pname in self.window_map:
                self.instance_enabled_by_hwnd[hwnd] = False
                username = self.pid_username.get(pid)
                if username:
                    self.enabled_by_username[username.lower()] = False
        self.refresh_instance_list(manual=False)
        self.log("Disabled all detected instances.")

    def apply_selected_instance_overrides(self) -> None:
        selected = self.instance_tree.selection()
        if not selected:
            self.log("Override apply skipped: no row selected.")
            return
        raw_interval = self.instance_override_seconds_var.get().strip() if self.instance_override_seconds_var is not None else ""
        raw_pattern = self.instance_override_pattern_var.get().strip().lower() if self.instance_override_pattern_var is not None else "default"
        raw_priority = self.instance_priority_var.get().strip() if self.instance_priority_var is not None else "1"
        interval_override: float | None = None
        priority_value = 1
        if raw_interval:
            try:
                interval_override = float(raw_interval)
            except ValueError:
                messagebox.showerror("Instance Override", "Interval override must be a number.")
                return
            if interval_override <= 0:
                messagebox.showerror("Instance Override", "Interval override must be > 0.")
                return
        try:
            priority_value = self._parse_priority(raw_priority)
        except Exception as exc:
            messagebox.showerror("Instance Override", str(exc))
            return
        if raw_pattern not in {"default", "balanced", "subtle", "aggressive", "randomized"}:
            messagebox.showerror("Instance Override", "Invalid override pattern.")
            return
        applied = 0
        for item in selected:
            try:
                hwnd = int(item)
            except ValueError:
                continue
            with self.state_lock:
                pid = next((pid for h, _t, pid, _p in self.window_map if h == hwnd), None)
            if pid is None:
                continue
            with self.state_lock:
                if interval_override is None:
                    self.instance_interval_override.pop(pid, None)
                else:
                    self.instance_interval_override[pid] = interval_override
                if raw_pattern == "default":
                    self.instance_pattern_override.pop(pid, None)
                else:
                    self.instance_pattern_override[pid] = raw_pattern
                self.instance_priority_by_pid[pid] = priority_value
            applied += 1
        if applied > 0:
            self.log(f"Applied per-instance overrides to {applied} instance(s).")
            self._record_event(f"Overrides applied: {applied}")
            self.refresh_instance_list(manual=False)

    def clear_selected_instance_overrides(self) -> None:
        selected = self.instance_tree.selection()
        if not selected:
            return
        cleared = 0
        for item in selected:
            try:
                hwnd = int(item)
            except ValueError:
                continue
            with self.state_lock:
                pid = next((pid for h, _t, pid, _p in self.window_map if h == hwnd), None)
            if pid is None:
                continue
            with self.state_lock:
                self.instance_interval_override.pop(pid, None)
                self.instance_pattern_override.pop(pid, None)
                self.instance_priority_by_pid.pop(pid, None)
            cleared += 1
        if cleared > 0:
            self.log(f"Cleared per-instance overrides for {cleared} instance(s).")
            self._record_event(f"Overrides cleared: {cleared}")

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
        if self.pause_override_until is not None:
            if time.time() < self.pause_override_until:
                return True
            self.pause_override_until = None
        if not self.runtime_pause_enabled:
            return False
        try:
            start_hour, start_min = self._parse_hhmm(self.runtime_pause_start, "Pause start")
            end_hour, end_min = self._parse_hhmm(self.runtime_pause_end, "Pause end")
        except Exception:
            return False

        now = datetime.now()
        now_mins = now.hour * 60 + now.minute
        start_mins = start_hour * 60 + start_min
        end_mins = end_hour * 60 + end_min

        if start_mins <= end_mins:
            return start_mins <= now_mins < end_mins
        return now_mins >= start_mins or now_mins < end_mins

    def parse_manual_pause_minutes(self) -> int:
        raw = self.manual_pause_minutes_var.get().strip()
        try:
            value = int(raw)
        except ValueError as exc:
            raise ValueError("Quick pause minutes must be an integer.") from exc
        if value < 1:
            raise ValueError("Quick pause minutes must be >= 1.")
        return value

    @staticmethod
    def _parse_priority(raw: str) -> int:
        try:
            value = int(raw.strip())
        except ValueError as exc:
            raise ValueError("Priority must be an integer.") from exc
        if value < 1 or value > 9:
            raise ValueError("Priority must be between 1 and 9.")
        return value

    def _scheduler_slots(self) -> list[tuple[int, str]]:
        slots: list[tuple[int, str]] = []
        for time_var, preset_var in (
            (self.scheduler_slot1_time_var, self.scheduler_slot1_preset_var),
            (self.scheduler_slot2_time_var, self.scheduler_slot2_preset_var),
        ):
            preset = self._sanitize_preset_name(preset_var.get().strip() or "default")
            hour, minute = self._parse_hhmm(time_var.get(), "Scheduler time")
            slots.append((hour * 60 + minute, preset))
        return slots

    def _dangerous_setting_warnings(self) -> list[str]:
        warnings: list[str] = []
        try:
            interval = self.parse_interval()
            if interval < 2:
                warnings.append("Jump interval under 2 seconds may be unstable.")
        except Exception:
            pass
        try:
            jump_fail_threshold = self.parse_jump_fail_watchdog_threshold()
            if jump_fail_threshold < 3:
                warnings.append("Jump-fail watchdog under 3 cycles can cause frequent resets.")
        except Exception:
            pass
        try:
            no_windows_threshold = self.parse_no_windows_watchdog_threshold()
            if no_windows_threshold < 5:
                warnings.append("No-windows watchdog under 5 cycles may spam refresh/recovery.")
        except Exception:
            pass
        if self.process_limiter_enabled_var.get():
            try:
                if self.process_limiter_auto_mode_var.get():
                    warnings.append("Process limiter auto mode forces immediate 0% freeze on Roblox processes.")
                else:
                    limiter_percent = self.parse_process_limiter_target_percent()
                    if limiter_percent == 0:
                        warnings.append("Process limiter at 0% fully freezes Roblox processes and blocks anti-AFK input.")
                    elif limiter_percent < 20:
                        warnings.append("Process limiter under 20% active time can cause delayed in-game reactions.")
            except Exception:
                pass
        if self.instance_relaunch_enabled_var.get():
            try:
                max_per_hour = self.parse_instance_relaunch_max_per_hour()
                if max_per_hour > 20:
                    warnings.append("Auto-relaunch max launches/hr over 20 can spam Roblox relaunch attempts.")
            except Exception:
                pass
        if self.webhook_enabled_var.get():
            urls = self._configured_webhook_urls()
            if not urls:
                warnings.append("Webhook is enabled but no URL is configured.")
            for url in urls:
                if not self._is_valid_webhook_url(url):
                    warnings.append("One or more webhook URLs are invalid (must be HTTPS).")
                    break
        if self.vendor_alerts_enabled_var.get():
            try:
                cooldown = self.parse_vendor_alert_cooldown_seconds()
                if cooldown < 30:
                    warnings.append("Vendor alert cooldown under 30s may create duplicate alerts.")
            except Exception:
                pass
        return warnings

    def pause_for_minutes(self) -> None:
        try:
            minutes = self.parse_manual_pause_minutes()
        except Exception as exc:
            messagebox.showerror("Pause", str(exc))
            return
        self.pause_override_until = time.time() + (minutes * 60)
        self.log(f"Manual pause enabled for {minutes} minute(s).")
        self._record_event(f"Manual pause {minutes}m")

    def clear_manual_pause(self) -> None:
        if self.pause_override_until is None:
            return
        self.pause_override_until = None
        self.log("Manual pause cleared.")
        self._record_event("Manual pause cleared")

    def _current_input_tick(self) -> int:
        info = _LASTINPUTINFO()
        info.cbSize = ctypes.sizeof(_LASTINPUTINFO)
        if not self.user32.GetLastInputInfo(ctypes.byref(info)):
            return self.last_system_input_tick
        return int(info.dwTime)

    def _is_roblox_hwnd(self, hwnd: int) -> bool:
        if hwnd <= 0 or not self.user32.IsWindow(hwnd):
            return False
        with self.state_lock:
            for known_hwnd, _title, _pid, _pname in self.window_map:
                if known_hwnd == hwnd:
                    return True
        pid_ref = wintypes.DWORD(0)
        self.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid_ref))
        pid = int(pid_ref.value)
        if pid <= 0:
            return False
        pname = self._get_process_name(pid).lower()
        return pname in {"robloxplayerbeta.exe", "windows10universal.exe"}

    def _release_virtual_inputs(self) -> None:
        if self.gamepad is None:
            return
        try:
            vg_module = cast(Any, self._ensure_vgamepad_module())
            jump_button = vg_module.XUSB_BUTTON.XUSB_GAMEPAD_A
            self.gamepad.left_joystick(0, 0)
            self.gamepad.release_button(jump_button)
            self.gamepad.update()
        except Exception:
            pass

    def _is_window_input_paused(self, hwnd: int, now: float | None = None) -> bool:
        if now is None:
            now = time.time()
        with self.state_lock:
            until = self.roblox_input_pause_until_by_hwnd.get(hwnd, 0.0)
            if until > now:
                return True
            if hwnd in self.roblox_input_pause_until_by_hwnd:
                self.roblox_input_pause_until_by_hwnd.pop(hwnd, None)
                if hwnd in self.roblox_input_pause_logged_hwnds:
                    self.roblox_input_pause_logged_hwnds.discard(hwnd)
                    self.log(f"Auto-pause ended for Roblox window {hwnd}.")
        return False

    def _update_roblox_input_pause(self) -> None:
        if not self.roblox_input_pause_enabled or not self.is_running:
            return
        tick = self._current_input_tick()
        if tick == self.last_system_input_tick:
            return
        self.last_system_input_tick = tick
        hwnd = int(self.user32.GetForegroundWindow() or 0)
        if not self._is_roblox_hwnd(hwnd):
            return
        now = time.time()
        pause_for = max(0.2, min(self.roblox_input_pause_seconds, 10.0))
        with self.state_lock:
            self.roblox_input_pause_until_by_hwnd[hwnd] = now + pause_for
            if hwnd not in self.roblox_input_pause_logged_hwnds:
                self.roblox_input_pause_logged_hwnds.add(hwnd)
                self.log(f"Auto-paused anti-AFK for Roblox window {hwnd}: active user input.")
        self._release_virtual_inputs()

    def _process_limiter_open_process(self, pid: int) -> int | None:
        if pid <= 0 or pid == os.getpid():
            return None
        rights = PROCESS_SUSPEND_RESUME | PROCESS_QUERY_LIMITED_INFORMATION
        handle = int(self.kernel32.OpenProcess(rights, False, pid))
        if handle <= 0:
            return None
        return handle

    def _process_limiter_suspend_pid(self, pid: int) -> bool:
        if not self.process_limiter_supported:
            return False
        suspend_fn = self.nt_suspend_process
        if suspend_fn is None:
            return False
        handle = self._process_limiter_open_process(pid)
        if handle is None:
            return False
        status = STATUS_INFO_LENGTH_MISMATCH
        try:
            status = int(cast(Any, suspend_fn)(wintypes.HANDLE(handle)))
        except Exception as exc:
            self._process_limiter_mark_error(f"suspend failed for PID {pid}: {exc}")
            return False
        finally:
            self.kernel32.CloseHandle(wintypes.HANDLE(handle))
        if self._ntstatus_unsigned(status) == STATUS_SUCCESS:
            return True
        self._process_limiter_mark_error(f"suspend NTSTATUS 0x{self._ntstatus_unsigned(status):08X} for PID {pid}")
        return False

    def _process_limiter_resume_pid(self, pid: int) -> bool:
        if not self.process_limiter_supported:
            return False
        resume_fn = self.nt_resume_process
        if resume_fn is None:
            return False
        handle = self._process_limiter_open_process(pid)
        if handle is None:
            return False
        status = STATUS_INFO_LENGTH_MISMATCH
        try:
            status = int(cast(Any, resume_fn)(wintypes.HANDLE(handle)))
        except Exception as exc:
            self._process_limiter_mark_error(f"resume failed for PID {pid}: {exc}")
            return False
        finally:
            self.kernel32.CloseHandle(wintypes.HANDLE(handle))
        if self._ntstatus_unsigned(status) == STATUS_SUCCESS:
            return True
        self._process_limiter_mark_error(f"resume NTSTATUS 0x{self._ntstatus_unsigned(status):08X} for PID {pid}")
        return False

    def _process_limiter_suspend_many(self, pids: set[int]) -> None:
        for pid in sorted(pids):
            with self.state_lock:
                if pid in self.process_limiter_suspended_pids:
                    continue
            if self._process_limiter_suspend_pid(pid):
                with self.state_lock:
                    self.process_limiter_suspended_pids.add(pid)
                    self.process_limiter_suspend_count += 1

    def _process_limiter_resume_many(self, pids: set[int], force: bool = False) -> int:
        resumed = 0
        for pid in sorted(pids):
            with self.state_lock:
                was_suspended = pid in self.process_limiter_suspended_pids
            if not force and not was_suspended:
                continue
            ok = self._process_limiter_resume_pid(pid)
            if was_suspended:
                with self.state_lock:
                    self.process_limiter_suspended_pids.discard(pid)
                    if ok:
                        self.process_limiter_resume_count += 1
                        resumed += 1
        return resumed

    def _process_limiter_resume_all(self, log_result: bool = True) -> int:
        with self.state_lock:
            targets = set(self.process_limiter_suspended_pids)
            self.process_limiter_boost_until_by_pid.clear()
        resumed = self._process_limiter_resume_many(targets, force=True)
        with self.state_lock:
            self.process_limiter_suspended_pids.clear()
        if log_result and resumed > 0:
            self.log(f"Process limiter resumed {resumed} process(es).")
        return resumed

    def _process_limiter_request_boost(self, pid: int, seconds: float = 0.45) -> None:
        if self.runtime_process_limiter_target_percent <= 0:
            return
        if pid <= 0:
            return
        until = time.time() + max(0.15, min(seconds, 2.0))
        with self.state_lock:
            previous = self.process_limiter_boost_until_by_pid.get(pid, 0.0)
            if until > previous:
                self.process_limiter_boost_until_by_pid[pid] = until
            suspended = pid in self.process_limiter_suspended_pids
        if suspended:
            self._process_limiter_resume_many({pid})

    def _process_limiter_worker(self) -> None:
        while not self.process_limiter_stop_event.is_set():
            try:
                target_pids = self._process_limiter_target_pids_snapshot()
                now = time.time()
                stale_suspended: set[int] = set()
                with self.state_lock:
                    self.process_limiter_boost_until_by_pid = {
                        pid: ts
                        for pid, ts in self.process_limiter_boost_until_by_pid.items()
                        if pid in target_pids and ts > now
                    }
                    stale_suspended = self.process_limiter_suspended_pids - target_pids
                if stale_suspended:
                    self._process_limiter_resume_many(stale_suspended, force=True)

                if not self._process_limiter_should_throttle():
                    self._process_limiter_resume_all(log_result=False)
                    if self.process_limiter_stop_event.wait(0.25):
                        break
                    continue
                if not target_pids:
                    if self.process_limiter_stop_event.wait(0.3):
                        break
                    continue

                cycle_seconds = max(0.08, self.runtime_process_limiter_cycle_ms / 1000.0)
                active_seconds = max(0.03, cycle_seconds * (self.runtime_process_limiter_target_percent / 100.0))
                idle_seconds = max(0.03, cycle_seconds - active_seconds)
                if self.runtime_process_limiter_target_percent >= 100:
                    self._process_limiter_resume_all(log_result=False)
                    if self.process_limiter_stop_event.wait(0.25):
                        break
                    continue
                if self.runtime_process_limiter_target_percent <= 0:
                    with self.state_lock:
                        self.process_limiter_boost_until_by_pid.clear()
                    self._process_limiter_suspend_many(target_pids)
                    if self.process_limiter_stop_event.wait(max(0.08, cycle_seconds)):
                        break
                    continue

                self._process_limiter_resume_many(target_pids)
                if self.process_limiter_stop_event.wait(active_seconds):
                    break
                now = time.time()
                with self.state_lock:
                    boosted = {pid for pid, ts in self.process_limiter_boost_until_by_pid.items() if ts > now}
                throttle_targets = {pid for pid in target_pids if pid not in boosted}
                if throttle_targets:
                    self._process_limiter_suspend_many(throttle_targets)
                if self.process_limiter_stop_event.wait(idle_seconds):
                    break
            except Exception as exc:
                self._process_limiter_mark_error(f"worker error: {exc}")
                if self.process_limiter_stop_event.wait(0.4):
                    break
        self._process_limiter_resume_all(log_result=False)

    def _ensure_process_limiter_worker(self) -> None:
        if not self.process_limiter_supported:
            return
        if self.process_limiter_thread and self.process_limiter_thread.is_alive():
            return
        self.process_limiter_stop_event.clear()
        self.process_limiter_thread = threading.Thread(target=self._process_limiter_worker, daemon=True)
        self.process_limiter_thread.start()

    def _stop_process_limiter_worker(self) -> None:
        self.process_limiter_stop_event.set()
        if self.process_limiter_thread and self.process_limiter_thread.is_alive():
            self.process_limiter_thread.join(timeout=1.0)
        self.process_limiter_thread = None
        self._process_limiter_resume_all(log_result=False)

    def _set_instance_relaunch_status(self, text: str) -> None:
        self.instance_relaunch_status_var.set(text)

    def _reset_instance_relaunch_state(self, reset_target: bool) -> None:
        self.instance_relaunch_drop_since = None
        self.instance_relaunch_recovered_logged = False
        self.instance_relaunch_last_attempt_at = 0.0
        self.instance_relaunch_wait_until = 0.0
        self.instance_relaunch_attempt_timestamps.clear()
        self.instance_relaunch_last_log_at = 0.0
        self.account_roster_missing_since_by_user_id.clear()
        if reset_target:
            self.instance_relaunch_target_count = 0
        self._set_instance_relaunch_status("Relaunch idle.")

    def _prune_instance_relaunch_history(self, now: float) -> None:
        self.instance_relaunch_attempt_timestamps = [
            ts for ts in self.instance_relaunch_attempt_timestamps if (now - ts) <= 3600
        ]

    def _account_label_for_user_id(self, user_id: int) -> str:
        with self.state_lock:
            name = self.account_roster_names_by_user_id.get(user_id, "").strip()
        if name:
            return f"{name} ({user_id})"
        return str(user_id)

    def _account_roster_missing_snapshot(self) -> tuple[list[int], int, int]:
        with self.state_lock:
            expected = set(self.account_roster_user_ids)
            if not expected:
                return [], 0, 0
            active_pids = {pid for _hwnd, _title, pid, _pname in self.window_map}
            active_user_ids: set[int] = set()
            unresolved_identity = 0
            for pid in active_pids:
                user_id = self.pid_user_id.get(pid)
                if isinstance(user_id, int) and user_id > 0:
                    active_user_ids.add(user_id)
                else:
                    unresolved_identity += 1
        missing = sorted(user_id for user_id in expected if user_id not in active_user_ids)
        return missing, len(active_user_ids), unresolved_identity

    def _refresh_account_roster_status(self) -> None:
        if self._enqueue_on_ui_thread(self._refresh_account_roster_status):
            return
        with self.state_lock:
            locked_count = len(self.account_roster_user_ids)
        if not self.account_roster_enabled_var.get():
            self.account_roster_status_var.set(f"Roster OFF ({locked_count} locked)")
            return
        if locked_count <= 0:
            self.account_roster_status_var.set("Roster ON (lock accounts)")
            return
        missing, active_known, unresolved_identity = self._account_roster_missing_snapshot()
        if missing:
            self.account_roster_status_var.set(f"Roster missing {len(missing)}/{locked_count}")
            return
        suffix = f", {unresolved_identity} unresolved" if unresolved_identity > 0 else ""
        self.account_roster_status_var.set(f"Roster healthy {min(active_known, locked_count)}/{locked_count}{suffix}")

    def lock_current_account_roster(self) -> None:
        with self.state_lock:
            active_pids = sorted({pid for _hwnd, _title, pid, _pname in self.window_map})
            pid_user_id = dict(self.pid_user_id)
            pid_username = dict(self.pid_username)
            existing_names = dict(self.account_roster_names_by_user_id)
        if not active_pids:
            self.log("Account roster lock skipped: no Roblox windows detected.")
            return

        locked_user_ids: set[int] = set()
        names_by_user_id: dict[int, str] = {}
        unresolved_pids: list[int] = []
        for pid in active_pids:
            user_id = pid_user_id.get(pid)
            username = pid_username.get(pid, "").strip()
            if isinstance(user_id, int) and user_id > 0:
                locked_user_ids.add(user_id)
                if username:
                    names_by_user_id[user_id] = username
                else:
                    fallback = existing_names.get(user_id, "").strip()
                    if fallback:
                        names_by_user_id[user_id] = fallback
            else:
                unresolved_pids.append(pid)

        if not locked_user_ids:
            self.log("Account roster lock failed: no resolved account identities yet.")
            messagebox.showinfo("Lock Accounts", "No resolved account identities yet. Wait for detection and try again.")
            return

        with self.state_lock:
            self.account_roster_user_ids = set(locked_user_ids)
            self.account_roster_names_by_user_id = dict(names_by_user_id)
            self.account_roster_missing_since_by_user_id.clear()
            self.instance_relaunch_target_count = len(self.account_roster_user_ids)
            self.instance_relaunch_drop_since = None
        self.account_roster_enabled_var.set(True)
        self._refresh_account_roster_status()
        self.log(f"Locked account roster with {len(locked_user_ids)} account(s).")
        self._record_event(f"Account roster locked ({len(locked_user_ids)})")
        if unresolved_pids:
            self.log(f"Roster lock note: skipped {len(unresolved_pids)} instance(s) with unresolved identity.")

    def clear_account_roster(self) -> None:
        with self.state_lock:
            removed = len(self.account_roster_user_ids)
            self.account_roster_user_ids.clear()
            self.account_roster_names_by_user_id.clear()
            self.account_roster_missing_since_by_user_id.clear()
            if self.is_running:
                self.instance_relaunch_target_count = len({hwnd for hwnd, _title, _pid, _pname in self.window_map})
            self.instance_relaunch_drop_since = None
        self._refresh_account_roster_status()
        if removed > 0:
            self.log(f"Cleared account roster ({removed} account(s)).")
            self._record_event("Account roster cleared")

    def _discover_roblox_launcher_path(self, force_refresh: bool = False) -> str:
        now = time.time()
        if (
            not force_refresh
            and self.instance_relaunch_launcher_cache_path
            and os.path.exists(self.instance_relaunch_launcher_cache_path)
            and (now - self.instance_relaunch_launcher_cache_at) < 120
        ):
            return self.instance_relaunch_launcher_cache_path

        roots: list[str] = []
        local = os.environ.get("LOCALAPPDATA")
        if local:
            roots.append(os.path.join(local, "Roblox", "Versions"))
        roots.extend(
            [
                os.path.join(os.path.expanduser("~"), "AppData", "Local", "Roblox", "Versions"),
            ]
        )

        candidates: list[tuple[float, str]] = []
        preferred_names = ("RobloxPlayerLauncher.exe", "RobloxPlayerBeta.exe")
        for root in roots:
            if not os.path.isdir(root):
                continue
            try:
                for entry in os.scandir(root):
                    if not entry.is_dir():
                        continue
                    for filename in preferred_names:
                        path = os.path.join(entry.path, filename)
                        if os.path.isfile(path):
                            try:
                                score = os.path.getmtime(path)
                            except OSError:
                                score = 0.0
                            candidates.append((score, path))
            except OSError:
                continue

        chosen = ""
        if candidates:
            candidates.sort(key=lambda item: item[0], reverse=True)
            chosen = candidates[0][1]
        self.instance_relaunch_launcher_cache_path = chosen
        self.instance_relaunch_launcher_cache_at = now
        return chosen

    def _launch_roblox_instance(self) -> bool:
        target = self.runtime_instance_relaunch_launch_target.strip()
        try:
            if target:
                if os.name == "nt":
                    os.startfile(target)  # type: ignore[attr-defined]
                else:
                    webbrowser.open(target)
                return True
        except Exception as exc:
            self.log(f"Auto-relaunch target launch failed: {exc}")

        launcher = self._discover_roblox_launcher_path(force_refresh=False)
        if not launcher:
            launcher = self._discover_roblox_launcher_path(force_refresh=True)
        if not launcher:
            self.log("Auto-relaunch failed: Roblox launcher not found.")
            return False
        try:
            subprocess.Popen([launcher], close_fds=True)
            return True
        except Exception as exc:
            self.log(f"Auto-relaunch failed to start launcher: {exc}")
            return False

    def _check_dropped_instance_relaunch(self) -> None:
        monitor_active = self.is_running or self.runtime_watchdog_standby_mode
        if not self.runtime_instance_relaunch_enabled or not monitor_active:
            if self.is_running and not self.runtime_instance_relaunch_enabled:
                with self.state_lock:
                    self.instance_relaunch_target_count = len({hwnd for hwnd, _title, _pid, _pname in self.window_map})
                    self.account_roster_missing_since_by_user_id.clear()
            self.instance_relaunch_drop_since = None
            self.instance_relaunch_recovered_logged = False
            if self.runtime_watchdog_standby_mode and not self.is_running and not self.runtime_instance_relaunch_enabled:
                self._set_instance_relaunch_status("Standby active (auto-relaunch disabled).")
            elif not self.is_running and not self.runtime_watchdog_standby_mode:
                self._set_instance_relaunch_status("Relaunch idle (standby off).")
            else:
                self._set_instance_relaunch_status("Relaunch idle.")
            return

        now = time.time()
        use_roster_mode = bool(self.runtime_account_roster_enabled)
        with self.state_lock:
            current_count = len({hwnd for hwnd, _title, _pid, _pname in self.window_map})
            locked_roster_ids = set(self.account_roster_user_ids)
            active_pids = {pid for _hwnd, _title, pid, _pname in self.window_map}
            active_user_ids = {uid for pid, uid in self.pid_user_id.items() if pid in active_pids}
            unresolved_identity = sum(1 for pid in active_pids if pid not in self.pid_user_id)

        if use_roster_mode and locked_roster_ids:
            target_count = len(locked_roster_ids)
            self.instance_relaunch_target_count = target_count
            missing_ids = sorted(uid for uid in locked_roster_ids if uid not in active_user_ids)
            with self.state_lock:
                for user_id in missing_ids:
                    self.account_roster_missing_since_by_user_id.setdefault(user_id, now)
                self.account_roster_missing_since_by_user_id = {
                    user_id: ts
                    for user_id, ts in self.account_roster_missing_since_by_user_id.items()
                    if user_id in missing_ids
                }
                mature_missing_ids = [
                    user_id
                    for user_id in missing_ids
                    if (now - self.account_roster_missing_since_by_user_id.get(user_id, now))
                    >= self.runtime_instance_relaunch_grace_seconds
                ]
            if not missing_ids:
                if self.instance_relaunch_drop_since is not None and not self.instance_relaunch_recovered_logged:
                    self.log("Auto-relaunch recovered locked roster coverage.")
                    self._record_event("Auto-relaunch recovered (roster)")
                    self._send_webhook(
                        f"{APP_NAME} Relaunch Recovery",
                        "Locked roster is healthy again.",
                        channel="recovery",
                    )
                    self.instance_relaunch_recovered_logged = True
                self.instance_relaunch_drop_since = None
                extras = max(0, current_count - target_count)
                extra_suffix = f" (+{extras} extra)" if extras > 0 else ""
                self._set_instance_relaunch_status(f"Healthy roster {target_count}/{target_count}{extra_suffix}.")
                return
            self.instance_relaunch_recovered_logged = False
            unresolved_cover = min(unresolved_identity, len(missing_ids))
            uncovered_missing = max(0, len(missing_ids) - unresolved_cover)
            if uncovered_missing <= 0:
                self._set_instance_relaunch_status(
                    f"Roster waiting on identity ({len(missing_ids)} unresolved roster slot(s))."
                )
                return
            if now < self.instance_relaunch_wait_until:
                wait_left = max(0, int(self.instance_relaunch_wait_until - now))
                self._set_instance_relaunch_status(
                    f"Waiting spawn for roster ({uncovered_missing} missing, {wait_left}s)."
                )
                return
            mature_uncovered = max(0, len(mature_missing_ids) - unresolved_cover)
            if mature_uncovered <= 0:
                with self.state_lock:
                    oldest_missing = min(self.account_roster_missing_since_by_user_id.get(uid, now) for uid in missing_ids)
                grace_left = max(0, int(self.runtime_instance_relaunch_grace_seconds - (now - oldest_missing)))
                identity_hint = " (awaiting identity)" if unresolved_identity > 0 else ""
                self._set_instance_relaunch_status(
                    f"Roster missing {uncovered_missing}/{target_count}{identity_hint}; relaunch in {grace_left}s."
                )
                return
            if (now - self.instance_relaunch_last_attempt_at) < self.instance_relaunch_min_interval_seconds:
                retry_left = max(0, int(self.instance_relaunch_min_interval_seconds - (now - self.instance_relaunch_last_attempt_at)))
                self._set_instance_relaunch_status(
                    f"Relaunch cooldown {retry_left}s (roster missing {uncovered_missing}/{target_count})."
                )
                return

            self._prune_instance_relaunch_history(now)
            launches_used = len(self.instance_relaunch_attempt_timestamps)
            launches_left = max(0, self.runtime_instance_relaunch_max_per_hour - launches_used)
            if launches_left <= 0:
                if (now - self.instance_relaunch_last_log_at) >= 45:
                    self.instance_relaunch_last_log_at = now
                    self.log(
                        "Auto-relaunch paused: hourly launch cap reached "
                        f"({self.runtime_instance_relaunch_max_per_hour}/hr)."
                    )
                    self._record_event("Auto-relaunch hourly cap reached")
                    self._send_webhook(
                        f"{APP_NAME} Relaunch Cap Reached",
                        f"Hourly relaunch cap reached ({self.runtime_instance_relaunch_max_per_hour}/hr).",
                        channel="recovery",
                    )
                self._set_instance_relaunch_status(
                    f"Launch cap reached ({self.runtime_instance_relaunch_max_per_hour}/hr)."
                )
                return

            to_launch = max(1, min(mature_uncovered, launches_left))
            launched = 0
            for _ in range(to_launch):
                if self._launch_roblox_instance():
                    launched += 1
                    self.instance_relaunch_attempt_timestamps.append(now)
            self.instance_relaunch_last_attempt_at = now
            if launched > 0:
                self.instance_relaunch_wait_until = now + max(12.0, self.runtime_instance_relaunch_grace_seconds / 2.0)
                self.instance_relaunch_drop_since = now
                labels = ", ".join(self._account_label_for_user_id(uid) for uid in missing_ids[:4])
                if len(missing_ids) > 4:
                    labels += ", ..."
                self.log(
                    f"Auto-relaunch started {launched} Roblox instance(s) for missing roster account(s): {labels}."
                )
                self._record_event(f"Auto-relaunch x{launched} (roster)")
                self._send_webhook(
                    f"{APP_NAME} Auto Relaunch",
                    f"Started {launched} relaunch attempt(s); roster missing {uncovered_missing}/{target_count}.",
                    channel="recovery",
                )
                self._set_instance_relaunch_status(
                    f"Relaunch started x{launched}; roster missing {uncovered_missing}/{target_count}."
                )
                self.refresh_instance_list(manual=False)
                return

            self.instance_relaunch_drop_since = now
            self._set_instance_relaunch_status("Relaunch attempt failed; retrying later.")
            return

        with self.state_lock:
            self.account_roster_missing_since_by_user_id.clear()
        if current_count > self.instance_relaunch_target_count:
            self.instance_relaunch_target_count = current_count
            self.instance_relaunch_drop_since = None
            self.instance_relaunch_recovered_logged = False
            self._set_instance_relaunch_status(f"Watching {current_count} instance(s).")
            return
        if self.instance_relaunch_target_count <= 0:
            self.instance_relaunch_target_count = current_count
            self.instance_relaunch_recovered_logged = False
            self._set_instance_relaunch_status("Waiting for baseline instances.")
            return

        missing = self.instance_relaunch_target_count - current_count
        if missing <= 0:
            if self.instance_relaunch_drop_since is not None and not self.instance_relaunch_recovered_logged:
                self.log("Auto-relaunch recovered baseline instance count.")
                self._record_event("Auto-relaunch recovered")
                self._send_webhook(
                    f"{APP_NAME} Relaunch Recovery",
                    f"Instance count recovered to {current_count}/{self.instance_relaunch_target_count}.",
                    channel="recovery",
                )
                self.instance_relaunch_recovered_logged = True
            self.instance_relaunch_drop_since = None
            self._set_instance_relaunch_status(f"Healthy {current_count}/{self.instance_relaunch_target_count}.")
            return
        self.instance_relaunch_recovered_logged = False

        if now < self.instance_relaunch_wait_until:
            wait_left = max(0, int(self.instance_relaunch_wait_until - now))
            self._set_instance_relaunch_status(
                f"Waiting spawn {current_count}/{self.instance_relaunch_target_count} ({wait_left}s)."
            )
            return
        if self.instance_relaunch_drop_since is None:
            self.instance_relaunch_drop_since = now
            self._record_event("Auto-relaunch drop detected")
            if self.runtime_instance_relaunch_grace_seconds > 0:
                self._set_instance_relaunch_status(
                    f"Drop detected {current_count}/{self.instance_relaunch_target_count}; grace window."
                )
                return
            self._set_instance_relaunch_status(
                f"Drop detected {current_count}/{self.instance_relaunch_target_count}; launching now."
            )
        if (now - self.instance_relaunch_drop_since) < self.runtime_instance_relaunch_grace_seconds:
            grace_left = max(0, int(self.runtime_instance_relaunch_grace_seconds - (now - self.instance_relaunch_drop_since)))
            self._set_instance_relaunch_status(
                f"Drop persists {current_count}/{self.instance_relaunch_target_count}; relaunch in {grace_left}s."
            )
            return
        if (now - self.instance_relaunch_last_attempt_at) < self.instance_relaunch_min_interval_seconds:
            retry_left = max(0, int(self.instance_relaunch_min_interval_seconds - (now - self.instance_relaunch_last_attempt_at)))
            self._set_instance_relaunch_status(
                f"Relaunch cooldown {retry_left}s ({current_count}/{self.instance_relaunch_target_count})."
            )
            return

        self._prune_instance_relaunch_history(now)
        launches_used = len(self.instance_relaunch_attempt_timestamps)
        launches_left = max(0, self.runtime_instance_relaunch_max_per_hour - launches_used)
        if launches_left <= 0:
            if (now - self.instance_relaunch_last_log_at) >= 45:
                self.instance_relaunch_last_log_at = now
                self.log(
                    "Auto-relaunch paused: hourly launch cap reached "
                    f"({self.runtime_instance_relaunch_max_per_hour}/hr)."
                )
                self._record_event("Auto-relaunch hourly cap reached")
                self._send_webhook(
                    f"{APP_NAME} Relaunch Cap Reached",
                    f"Hourly relaunch cap reached ({self.runtime_instance_relaunch_max_per_hour}/hr).",
                    channel="recovery",
                )
            self._set_instance_relaunch_status(
                f"Launch cap reached ({self.runtime_instance_relaunch_max_per_hour}/hr)."
            )
            return

        to_launch = max(1, min(missing, launches_left))
        launched = 0
        for _ in range(to_launch):
            if self._launch_roblox_instance():
                launched += 1
                self.instance_relaunch_attempt_timestamps.append(now)
        self.instance_relaunch_last_attempt_at = now
        if launched > 0:
            self.instance_relaunch_wait_until = now + max(12.0, self.runtime_instance_relaunch_grace_seconds / 2.0)
            self.instance_relaunch_drop_since = now
            self.log(
                f"Auto-relaunch started {launched} Roblox instance(s) "
                f"(detected {current_count}/{self.instance_relaunch_target_count})."
            )
            self._record_event(f"Auto-relaunch x{launched}")
            self._send_webhook(
                f"{APP_NAME} Auto Relaunch",
                f"Started {launched} relaunch attempt(s) at {current_count}/{self.instance_relaunch_target_count}.",
                channel="recovery",
            )
            self._set_instance_relaunch_status(
                f"Relaunch started x{launched}; waiting for clients ({current_count}/{self.instance_relaunch_target_count})."
            )
            self.refresh_instance_list(manual=False)
            return

        self.instance_relaunch_drop_since = now
        self._set_instance_relaunch_status("Relaunch attempt failed; retrying later.")

    def _effective_pattern(self, pid: int) -> str:
        pattern = self.instance_pattern_override.get(pid, "").strip().lower()
        if pattern in {"balanced", "subtle", "aggressive", "randomized"}:
            return pattern
        return self.runtime_anti_idle_pattern

    def _effective_interval(self, pid: int, base_interval: float) -> float:
        override = self.instance_interval_override.get(pid)
        value = override if override is not None else base_interval
        if self.runtime_safe_mode:
            value = max(value, 7.0)
        return max(0.5, value)

    def _profile_from_pattern(self, pattern: str) -> tuple[int, float, float, float]:
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
        if self.runtime_safe_mode:
            stick_x = max(700, min(stick_x, 2200))
            stick_hold = max(stick_hold, 0.06)
            gap = max(gap, 0.04)
            button_hold = max(button_hold, 0.16)
        return stick_x, stick_hold, gap, button_hold

    def _resolve_target_hwnds(self, base_interval: float) -> tuple[list[tuple[int, int]], bool]:
        now = time.time()
        with self.state_lock:
            use_cached = bool(self.window_map) and (now - self.last_instance_scan_at) <= self.runtime_scan_cache_ttl_seconds
            windows = list(self.window_map) if use_cached else []
        if not windows:
            windows = self.find_roblox_windows()
        had_windows = bool(windows)
        enabled: list[tuple[int, int]] = []
        priority_by_hwnd: dict[int, int] = {}
        with self.state_lock:
            for hwnd, _title, pid, _pname in windows:
                if self._is_window_input_paused(hwnd, now):
                    continue
                if not self.instance_enabled_by_hwnd.get(hwnd, True):
                    continue
                quarantine_until = self.instance_quarantine_until.get(hwnd, 0.0)
                if quarantine_until > now:
                    continue
                interval = self._effective_interval(pid, base_interval)
                last_jump = self.instance_last_jump.get(hwnd, 0.0)
                if last_jump and (now - last_jump) < interval:
                    continue
                enabled.append((hwnd, pid))
                priority_by_hwnd[hwnd] = self.instance_priority_by_pid.get(pid, 1)
            if not enabled:
                return [], had_windows

            if self.runtime_jump_mode == "round":
                self.round_robin_index = self.round_robin_index % len(enabled)
                hwnd, pid = enabled[self.round_robin_index]
                self.round_robin_index = (self.round_robin_index + 1) % len(enabled)
                return [(hwnd, pid)], had_windows
            if self.runtime_jump_mode == "weighted":
                wheel: list[tuple[int, int]] = []
                for hwnd, pid in enabled:
                    weight = max(1, min(9, priority_by_hwnd.get(hwnd, 1)))
                    wheel.extend([(hwnd, pid)] * weight)
                if not wheel:
                    return [], had_windows
                self.round_robin_index = self.round_robin_index % len(wheel)
                chosen = wheel[self.round_robin_index]
                self.round_robin_index = (self.round_robin_index + 1) % len(wheel)
                return [chosen], had_windows
            return enabled, had_windows

    def _reset_gamepad_session(self) -> None:
        self.gamepad = None
        self.ensure_gamepad()
        self.log("Watchdog reset: reinitialized gamepad session.")
        self._send_webhook(
            f"{APP_NAME} Watchdog",
            "Gamepad session reset after repeated failed cycles.",
            channel="recovery",
        )

    def _run_recovery_sequence(self) -> None:
        if self._enqueue_on_ui_thread(self._run_recovery_sequence):
            return
        try:
            self.refresh_instance_list(manual=False)
            self.restore_windows()
            if self.auto_realign_var.get():
                self.align_windows(log_result=False)
            self._record_event("Recovery sequence executed")
            self._send_webhook(f"{APP_NAME} Recovery", "Recovery sequence executed.", channel="recovery")
        except Exception as exc:
            self.log(f"Recovery sequence failed: {exc}")
            self._record_event(f"Recovery failed: {exc}")
            self._send_webhook(f"{APP_NAME} Recovery Error", f"Recovery sequence failed: {exc}", channel="recovery")

    def _recovery_tier_from_streak(self, streak: int) -> int:
        if streak >= self.instance_recovery_tier3_threshold:
            return 3
        if streak >= self.instance_recovery_tier2_threshold:
            return 2
        if streak >= self.instance_recovery_tier1_threshold:
            return 1
        return 0

    def _on_instance_send_success(self, hwnd: int) -> None:
        with self.state_lock:
            previous_streak = self.instance_send_fail_streak.get(hwnd, 0)
            previous_tier = self.instance_recovery_tier_by_hwnd.get(hwnd, 0)
            self.instance_send_fail_streak[hwnd] = 0
            self.instance_recovery_tier_by_hwnd[hwnd] = 0
            self.instance_recovery_last_log_at.pop(hwnd, None)
            self.instance_fail_count[hwnd] = 0
            self.instance_quarantine_until.pop(hwnd, None)
        if previous_streak > 0 or previous_tier > 0:
            self.log(f"Instance HWND {hwnd} recovered (streak reset).")
            self._record_event(f"Instance recovered HWND {hwnd}")

    def _on_instance_send_failure(self, hwnd: int, pid: int, exc: Exception) -> None:
        now = time.time()
        with self.state_lock:
            streak = self.instance_send_fail_streak.get(hwnd, 0) + 1
            tier_before = self.instance_recovery_tier_by_hwnd.get(hwnd, 0)
            tier_now = self._recovery_tier_from_streak(streak)
            self.instance_send_fail_streak[hwnd] = streak
            self.instance_recovery_tier_by_hwnd[hwnd] = tier_now
            self.instance_fail_count[hwnd] = self.instance_fail_count.get(hwnd, 0) + 1
            self.instance_recovery_last_log_at.setdefault(hwnd, 0.0)

            backoff_seconds = 0
            if tier_now == 1:
                backoff_seconds = self.instance_recovery_tier1_backoff_seconds
            elif tier_now == 2:
                backoff_seconds = self.instance_recovery_tier2_backoff_seconds
            elif tier_now >= 3:
                backoff_seconds = max(self.instance_recovery_tier3_backoff_seconds, self.instance_quarantine_seconds)
            if backoff_seconds > 0:
                until = now + backoff_seconds
                current_until = self.instance_quarantine_until.get(hwnd, 0.0)
                if until > current_until:
                    self.instance_quarantine_until[hwnd] = until
            pause_left = max(0, int(self.instance_quarantine_until.get(hwnd, 0.0) - now))
            last_log_at = self.instance_recovery_last_log_at.get(hwnd, 0.0)
            username = self.pid_username.get(pid, "unknown")

        if tier_now == 2:
            try:
                self.spoof_focus(hwnd, True)
                self.spoof_focus(hwnd, False)
            except Exception:
                pass
        elif tier_now >= 3:
            self._release_virtual_inputs()

        should_log = False
        if tier_now != tier_before:
            should_log = True
        elif (now - last_log_at) >= 20:
            should_log = True
        if should_log:
            self.log(
                f"Per-window recovery tier {tier_now} for HWND {hwnd} (PID {pid}, {username}) "
                f"after send failure streak={streak}. Backoff={pause_left}s. Last error: {exc}"
            )
            self._record_event(f"Recovery tier {tier_now} HWND {hwnd}")
            with self.state_lock:
                self.instance_recovery_last_log_at[hwnd] = now

    def jump_once(self, base_interval: float) -> tuple[bool, str]:
        if self._is_in_pause_window():
            with self.metrics_lock:
                self.session_cycles += 1
            return False, "paused"
        if self.runtime_process_limiter_enabled and self.runtime_process_limiter_target_percent <= 0:
            with self.metrics_lock:
                self.session_cycles += 1
            return False, "frozen_0_cpu"
        self._update_roblox_input_pause()

        self.ensure_gamepad()
        vg_module = cast(Any, self._ensure_vgamepad_module())
        gamepad = self.gamepad
        if gamepad is None:
            raise RuntimeError("Virtual gamepad is not initialized.")

        targets, had_windows = self._resolve_target_hwnds(base_interval)
        if not targets:
            with self.metrics_lock:
                self.session_cycles += 1
            if not had_windows:
                return False, "no_windows"
            return False, "not_due"

        sent_count = 0
        had_send_failure = False
        for hwnd, pid in targets:
            self._process_limiter_request_boost(pid)
            self.spoof_focus(hwnd, True)
            pattern = self._effective_pattern(pid)
            stick_x, stick_hold, gap, button_hold = self._profile_from_pattern(pattern)
            try:
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
                with self.state_lock:
                    self.instance_last_jump[hwnd] = time.time()
                    self.instance_attempt_count[hwnd] = self.instance_attempt_count.get(hwnd, 0) + 1
                self._on_instance_send_success(hwnd)
                sent_count += 1
            except Exception as exc:
                had_send_failure = True
                with self.metrics_lock:
                    self.session_errors += 1
                self._on_instance_send_failure(hwnd, pid, exc)
            finally:
                self.spoof_focus(hwnd, False)

        with self.metrics_lock:
            self.session_cycles += 1
            self.session_jumps += sent_count

        now = time.time()
        if (now - self.last_health_ui_update_at) >= self.health_ui_update_interval_seconds:
            self.last_health_ui_update_at = now
            self._enqueue_on_ui_thread(self.update_health_panel)
        if sent_count > 0:
            return True, "sent"
        if had_send_failure:
            return False, "send_failed"
        return False, "not_due"

    def test_jump(self) -> None:
        try:
            sent, _reason = self.jump_once(base_interval=self.parse_interval())
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
        self._send_webhook(APP_NAME, "Anti-AFK loop started.", channel="default")

        while not self.stop_event.is_set():
            try:
                sent, reason = self.jump_once(base_interval=interval)
                if sent:
                    self.failed_cycles = 0
                    self.no_window_cycles = 0
                    self.jump_fail_cycles = 0
                    if self.waiting_for_windows:
                        self.waiting_for_windows = False
                        self.log("Roblox windows found. Anti-AFK jumps resumed.")
                        self._record_event("Window wait ended")
                    self.log("Sent virtual jump (A) to enabled spoofed instances.")
                    self._record_event("Jump cycle success")
                else:
                    self.failed_cycles += 1
                    if reason == "no_windows":
                        self.no_window_cycles += 1
                        if self.runtime_start_when_windows_found:
                            if not self.waiting_for_windows:
                                self.waiting_for_windows = True
                                self.log("Waiting for Roblox windows to appear before resuming jumps.")
                                self._record_event("Waiting for windows")
                        else:
                            self.log("No Roblox windows found.")
                    elif reason == "paused":
                        self.log("Cycle paused by schedule/manual pause.")
                    elif reason == "not_due":
                        now = time.time()
                        if (now - self.last_not_due_log_at) >= 30:
                            self.last_not_due_log_at = now
                            self.log("Cycle skipped (instance interval not due).")
                    elif reason == "send_failed":
                        self.jump_fail_cycles += 1
                        self.log("Cycle had per-window send failures; recovery tiers applied.")
                    else:
                        self.jump_fail_cycles += 1
                        self.log("Cycle skipped (quarantine or per-instance interval not due).")

                if self.runtime_watchdog_enabled and self.no_window_cycles >= self.runtime_no_window_threshold:
                    self.log("Watchdog: no windows threshold reached, refreshing instance scan.")
                    self._record_event("Watchdog no-windows")
                    self.refresh_instance_list(manual=False)
                    self.no_window_cycles = 0

                if self.runtime_watchdog_enabled and self.jump_fail_cycles >= self.runtime_jump_fail_threshold:
                    self.log("Watchdog: jump-fail threshold reached.")
                    self._record_event("Watchdog jump-fail")
                    if self.runtime_recovery_enabled:
                        self._run_recovery_sequence()
                    self._reset_gamepad_session()
                    self.jump_fail_cycles = 0
            except Exception as exc:  # pragma: no cover
                self.failed_cycles += 1
                self.jump_fail_cycles += 1
                with self.metrics_lock:
                    self.session_errors += 1
                self.log(f"Error while sending jump: {exc}")
                details = traceback.format_exc()
                crash_path = self._write_crash_report("worker-loop", details)
                if crash_path:
                    self.log(f"Crash report saved: {crash_path}")
                self._record_event(f"Loop error: {exc}")
                self._send_webhook(f"{APP_NAME} Error", f"Jump loop error: {exc}", channel="recovery")
                self._enqueue_on_ui_thread(self.stop)
                return

            if self.stop_event.wait(interval):
                break

        self.log("Anti-AFK loop stopped.")
        self._record_event("Loop stopped")
        self._send_webhook(APP_NAME, "Anti-AFK loop stopped.", channel="default")

    def start(self) -> None:
        if self.is_running:
            return

        try:
            self._sync_runtime_settings_from_ui()
            self.validate_runtime_settings()
            interval = self.parse_interval()
            self.refresh_instance_list(manual=False)
            self.ensure_gamepad()
        except Exception as exc:
            with self.metrics_lock:
                self.session_errors += 1
            messagebox.showerror("Cannot start", str(exc))
            return
        warnings = self._dangerous_setting_warnings()
        if warnings:
            message = "Potentially risky settings detected:\n\n- " + "\n- ".join(warnings) + "\n\nStart anyway?"
            if not messagebox.askyesno("Safety guardrails", message):
                self.log("Start canceled by user after safety warning.")
                return

        with self.metrics_lock:
            if self.session_started_at is None:
                self.session_started_at = time.time()

        self.no_window_cycles = 0
        self.jump_fail_cycles = 0
        self.waiting_for_windows = False
        self.instance_relaunch_recovered_logged = False
        self.instance_send_fail_streak.clear()
        self.instance_recovery_tier_by_hwnd.clear()
        self.instance_recovery_last_log_at.clear()
        self.roblox_input_pause_until_by_hwnd.clear()
        self.roblox_input_pause_logged_hwnds.clear()
        self.last_system_input_tick = self._current_input_tick()
        self.stop_event.clear()
        self.worker_thread = threading.Thread(
            target=self.worker,
            args=(interval,),
            daemon=True,
        )
        self.worker_thread.start()
        self.set_running_ui(True)
        with self.state_lock:
            baseline = len({hwnd for hwnd, _title, _pid, _pname in self.window_map})
            roster_count = len(self.account_roster_user_ids) if self.runtime_account_roster_enabled else 0
            self.account_roster_missing_since_by_user_id.clear()
        target = roster_count if roster_count > 0 else baseline
        self.instance_relaunch_target_count = target
        if roster_count > 0:
            self._set_instance_relaunch_status(f"Watching locked roster ({roster_count} account(s)).")
        else:
            self._set_instance_relaunch_status(
                f"Watching {baseline} instance(s)." if baseline > 0 else "Waiting for baseline instances."
            )
        self._write_recovery_snapshot(force=True)
        self._write_session_report("start")

    def stop(self) -> None:
        self.stop_event.set()
        if self.worker_thread and self.worker_thread.is_alive():
            self.worker_thread.join(timeout=0.5)
        if self.process_limiter_only_when_running_var.get():
            self._process_limiter_resume_all(log_result=False)
        self.waiting_for_windows = False
        self.instance_send_fail_streak.clear()
        self.instance_recovery_tier_by_hwnd.clear()
        self.instance_recovery_last_log_at.clear()
        self.roblox_input_pause_until_by_hwnd.clear()
        self.roblox_input_pause_logged_hwnds.clear()
        self._reset_instance_relaunch_state(reset_target=True)
        self.set_running_ui(False)
        self._write_recovery_snapshot(force=True)
        self._write_session_report("stop")

    def _schedule_stats_update(self) -> None:
        try:
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
        except Exception as exc:
            now = time.time()
            if (now - self.last_ui_poll_error_at) >= 5.0:
                self.last_ui_poll_error_at = now
                self.log(f"UI stats update recovered: {exc}")
        finally:
            self.root.after(1000, self._schedule_stats_update)

    def _schedule_instance_poll(self) -> None:
        delay_ms = 3500 if self.is_running else 2500
        try:
            self._sync_runtime_settings_from_ui()
            self._ensure_process_limiter_worker()
            try:
                window_state = str(self.root.state())
            except Exception:
                window_state = "normal"
            iconic = window_state == "iconic"
            heavy_allowed = True
            now = time.time()
            if iconic:
                delay_ms = 7000 if self.is_running else 5000
                # Skip heavy scan/render work while minimized to avoid long-run UI hangs.
                heavy_allowed = False
            else:
                self.last_iconic_heavy_poll_at = now

            if heavy_allowed:
                self.refresh_instance_list(manual=False)
                self._refresh_process_limiter_status()
                self._check_dropped_instance_relaunch()
                self._poll_biome_tracker()
                self._maybe_send_biome_alert(self.current_biome_name)
            self._check_profile_scheduler()
            self._check_instance_health_alerts()
            if not iconic:
                self._repair_main_window_if_needed(force=False, reason="poll")
        except Exception as exc:
            now = time.time()
            should_log = (now - self.last_ui_poll_error_at) >= 5.0
            if should_log:
                self.last_ui_poll_error_at = now
                self.log(f"UI poll recovered after error: {exc}")
                self._record_event("UI poll recovered")
            try:
                state = str(self.root.state())
            except Exception:
                state = ""
            if state != "iconic":
                self._repair_main_window_if_needed(force=True, reason="poll-error")
        finally:
            self.root.after(delay_ms, self._schedule_instance_poll)

    def _check_profile_scheduler(self) -> None:
        if not self.scheduler_enabled_var.get():
            self.scheduler_last_applied_key = None
            return
        try:
            slots = self._scheduler_slots()
        except Exception:
            return
        if not slots:
            return
        now = datetime.now()
        now_min = now.hour * 60 + now.minute
        slots = sorted(slots, key=lambda item: item[0])
        selected = slots[-1]
        for entry in slots:
            if now_min >= entry[0]:
                selected = entry
            else:
                break
        key = f"{now.strftime('%Y%m%d-%H%M')}-{selected[1]}"
        if self.scheduler_last_applied_key == key:
            return
        self.scheduler_last_applied_key = key
        preset_name = selected[1]
        path = self._preset_path(preset_name)
        if not os.path.exists(path):
            self.log(f"Scheduler skipped missing preset: {preset_name}")
            return
        self.preset_name_var.set(preset_name)
        self.load_preset()
        self.log(f"Scheduler applied preset: {preset_name}")
        self._record_event(f"Scheduler preset: {preset_name}")

    def _check_instance_health_alerts(self) -> None:
        if not self.is_running or not self.health_alert_enabled_var.get():
            return
        try:
            threshold_seconds = self.parse_health_alert_minutes() * 60
        except ValueError:
            threshold_seconds = 180
        now = time.time()
        alerts: list[tuple[int, str, bool]] = []
        with self.state_lock:
            active_hwnds = {hwnd for hwnd, _title, _pid, _pname in self.window_map}
            self.last_instance_health_alert = {
                hwnd: ts for hwnd, ts in self.last_instance_health_alert.items() if hwnd in active_hwnds
            }
            self.instance_attempt_count = {
                hwnd: count for hwnd, count in self.instance_attempt_count.items() if hwnd in active_hwnds
            }
            self.instance_fail_count = {hwnd: count for hwnd, count in self.instance_fail_count.items() if hwnd in active_hwnds}
            self.instance_send_fail_streak = {
                hwnd: count for hwnd, count in self.instance_send_fail_streak.items() if hwnd in active_hwnds
            }
            self.instance_recovery_tier_by_hwnd = {
                hwnd: tier for hwnd, tier in self.instance_recovery_tier_by_hwnd.items() if hwnd in active_hwnds
            }
            self.instance_recovery_last_log_at = {
                hwnd: ts for hwnd, ts in self.instance_recovery_last_log_at.items() if hwnd in active_hwnds
            }
            self.instance_quarantine_until = {
                hwnd: ts for hwnd, ts in self.instance_quarantine_until.items() if hwnd in active_hwnds and ts > now
            }
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
                self.instance_fail_count[hwnd] = self.instance_fail_count.get(hwnd, 0) + 1
                quarantined = False
                if self.instance_fail_count[hwnd] >= self.instance_quarantine_fail_threshold:
                    self.instance_quarantine_until[hwnd] = now + self.instance_quarantine_seconds
                    self.instance_fail_count[hwnd] = 0
                    quarantined = True
                alerts.append((pid, msg, quarantined))
        for pid, msg, quarantined in alerts:
            if quarantined:
                self.log(f"Instance PID {pid} quarantined for {self.instance_quarantine_seconds}s due to repeated stale jumps.")
                self._record_event(f"Quarantine PID {pid}")
            self.log(f"Instance health alert: {msg}")
            self._record_event(f"Health alert: PID {pid}")
            self._send_webhook(f"{APP_NAME} Instance Health Alert", msg, channel="health")

    def _enabled_by_pid_snapshot(self) -> dict[int, bool]:
        mapping: dict[int, bool] = {}
        with self.state_lock:
            for hwnd, _title, pid, _pname in self.window_map:
                mapping[pid] = self.instance_enabled_by_hwnd.get(hwnd, True)
        return mapping

    def _collect_config_data(self) -> dict[str, Any]:
        with self.state_lock:
            interval_override_snapshot = dict(self.instance_interval_override)
            pattern_override_snapshot = dict(self.instance_pattern_override)
            priority_snapshot = dict(self.instance_priority_by_pid)
            roster_user_ids = sorted(self.account_roster_user_ids)
            roster_names = {
                str(user_id): name
                for user_id, name in self.account_roster_names_by_user_id.items()
                if user_id in self.account_roster_user_ids and name
            }
        return {
            "config_version": APP_CONFIG_VERSION,
            "interval_seconds": self.interval_var.get().strip(),
            "auto_realign": bool(self.auto_realign_var.get()),
            "enabled_by_pid": {str(pid): enabled for pid, enabled in self._enabled_by_pid_snapshot().items()},
            "jump_mode": self.jump_mode_var.get(),
            "pause_enabled": bool(self.pause_enabled_var.get()),
            "pause_start": self.pause_start_var.get().strip(),
            "pause_end": self.pause_end_var.get().strip(),
            "webhook_enabled": bool(self.webhook_enabled_var.get()),
            "webhook_url": self.webhook_url_var.get().strip(),
            "webhook_biome_url": self.webhook_biome_url_var.get().strip(),
            "webhook_recovery_url": self.webhook_recovery_url_var.get().strip(),
            "webhook_health_url": self.webhook_health_url_var.get().strip(),
            "webhook_vendor_url": self.webhook_vendor_url_var.get().strip(),
            "watchdog_enabled": bool(self.watchdog_enabled_var.get()),
            "watchdog_threshold": self.watchdog_threshold_var.get().strip(),
            "watchdog_no_windows_threshold": self.watchdog_no_windows_threshold_var.get().strip(),
            "watchdog_jump_fail_threshold": self.watchdog_jump_fail_threshold_var.get().strip(),
            "theme_name": self.theme_name_var.get().strip(),
            "anti_idle_pattern": self.anti_idle_pattern_var.get().strip(),
            "hotkeys_enabled": bool(self.hotkeys_enabled_var.get()),
            "hotkey_guard": bool(self.hotkey_guard_var.get()),
            "wait_for_windows": bool(self.start_when_windows_found_var.get()),
            "safe_mode": bool(self.safe_mode_var.get()),
            "roblox_input_pause_enabled": bool(self.roblox_input_pause_enabled),
            "roblox_input_pause_seconds": float(self.roblox_input_pause_seconds),
            "quick_pause_minutes": self.manual_pause_minutes_var.get().strip(),
            "profile_hotkey_1": self.profile_hotkey_1_var.get().strip(),
            "profile_hotkey_2": self.profile_hotkey_2_var.get().strip(),
            "profile_hotkey_3": self.profile_hotkey_3_var.get().strip(),
            "startup_restore_enabled": bool(self.startup_restore_enabled_var.get()),
            "startup_preset": self.startup_preset_var.get().strip(),
            "startup_auto_start": bool(self.startup_auto_start_var.get()),
            "startup_auto_align": bool(self.startup_auto_align_var.get()),
            "scheduler_enabled": bool(self.scheduler_enabled_var.get()),
            "scheduler_slot1_time": self.scheduler_slot1_time_var.get().strip(),
            "scheduler_slot1_preset": self.scheduler_slot1_preset_var.get().strip(),
            "scheduler_slot2_time": self.scheduler_slot2_time_var.get().strip(),
            "scheduler_slot2_preset": self.scheduler_slot2_preset_var.get().strip(),
            "process_limiter_enabled": bool(self.process_limiter_enabled_var.get()),
            "process_limiter_auto_mode": bool(self.process_limiter_auto_mode_var.get()),
            "process_limiter_only_when_running": bool(self.process_limiter_only_when_running_var.get()),
            "process_limiter_target_percent": self.process_limiter_target_percent_var.get().strip(),
            "process_limiter_cycle_ms": self.process_limiter_cycle_ms_var.get().strip(),
            "instance_relaunch_enabled": bool(self.instance_relaunch_enabled_var.get()),
            "instance_relaunch_grace_seconds": self.instance_relaunch_grace_seconds_var.get().strip(),
            "instance_relaunch_max_per_hour": self.instance_relaunch_max_per_hour_var.get().strip(),
            "instance_relaunch_launch_target": self.instance_relaunch_launch_target_var.get().strip(),
            "account_roster_enabled": bool(self.account_roster_enabled_var.get()),
            "watchdog_standby_mode": bool(self.watchdog_standby_mode_var.get()),
            "private_server_place_id": self.private_server_place_id_var.get().strip(),
            "private_server_code": self.private_server_code_var.get().strip(),
            "account_roster_user_ids": roster_user_ids,
            "account_roster_names_by_user_id": roster_names,
            "health_alert_enabled": bool(self.health_alert_enabled_var.get()),
            "health_alert_minutes": self.health_alert_minutes_var.get().strip(),
            "autosave_enabled": bool(self.autosave_enabled_var.get()),
            "autosave_minutes": self.autosave_minutes_var.get().strip(),
            "biome_alerts_enabled": bool(self.biome_alerts_enabled_var.get()),
            "rare_biome": self.rare_biome_var.get().strip().upper(),
            "rare_biome_confirm_enabled": bool(self.rare_biome_confirm_enabled_var.get()),
            "rare_biome_confirm_seconds": self.rare_biome_confirm_seconds_var.get().strip(),
            "biome_action": self.biome_action_var.get().strip(),
            "biome_action_preset": self.biome_action_preset_var.get().strip(),
            "vendor_alerts_enabled": bool(self.vendor_alerts_enabled_var.get()),
            "vendor_alert_cooldown": self.vendor_alert_cooldown_var.get().strip(),
            "recovery_enabled": bool(self.recovery_enabled_var.get()),
            "instance_interval_override_by_pid": {str(pid): value for pid, value in interval_override_snapshot.items()},
            "instance_pattern_override_by_pid": {str(pid): value for pid, value in pattern_override_snapshot.items()},
            "instance_priority_by_pid": {str(pid): value for pid, value in priority_snapshot.items()},
        }

    def _normalize_config_payload(self, raw: dict[str, Any]) -> tuple[dict[str, Any], bool]:
        data = dict(raw)
        changed = False
        try:
            version = int(data.get("config_version", 0))
        except (TypeError, ValueError):
            version = 0
            changed = True

        if version != APP_CONFIG_VERSION:
            data["config_version"] = APP_CONFIG_VERSION
            changed = True

        dict_keys = (
            "enabled_by_pid",
            "instance_interval_override_by_pid",
            "instance_pattern_override_by_pid",
            "instance_priority_by_pid",
            "account_roster_names_by_user_id",
        )
        for key in dict_keys:
            value = data.get(key)
            if value is None:
                continue
            if not isinstance(value, dict):
                data.pop(key, None)
                changed = True

        list_keys = ("account_roster_user_ids",)
        for key in list_keys:
            value = data.get(key)
            if value is None:
                continue
            if not isinstance(value, list):
                data.pop(key, None)
                changed = True
        return data, changed

    def _backup_invalid_config(self) -> str | None:
        if not os.path.exists(self.config_path):
            return None
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup_path = f"{self.config_path}.bad-{stamp}.json"
        try:
            shutil.copy2(self.config_path, backup_path)
            return backup_path
        except Exception:
            return None

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
        raw_interval_override = data.get("instance_interval_override_by_pid", {})
        interval_override: dict[int, float] = {}
        if isinstance(raw_interval_override, dict):
            for k, v in raw_interval_override.items():
                try:
                    parsed = float(v)
                    if parsed > 0:
                        interval_override[int(k)] = parsed
                except (TypeError, ValueError):
                    continue
        raw_pattern_override = data.get("instance_pattern_override_by_pid", {})
        pattern_override: dict[int, str] = {}
        if isinstance(raw_pattern_override, dict):
            for k, v in raw_pattern_override.items():
                if not isinstance(v, str):
                    continue
                pattern = v.strip().lower()
                if pattern in {"balanced", "subtle", "aggressive", "randomized"}:
                    try:
                        pattern_override[int(k)] = pattern
                    except (TypeError, ValueError):
                        continue
        raw_priority = data.get("instance_priority_by_pid", {})
        priority_by_pid: dict[int, int] = {}
        if isinstance(raw_priority, dict):
            for k, v in raw_priority.items():
                try:
                    parsed = int(v)
                    if 1 <= parsed <= 9:
                        priority_by_pid[int(k)] = parsed
                except (TypeError, ValueError):
                    continue
        raw_roster_ids = data.get("account_roster_user_ids", [])
        roster_user_ids: set[int] = set()
        if isinstance(raw_roster_ids, list):
            for raw_value in raw_roster_ids:
                try:
                    user_id = int(raw_value)
                except (TypeError, ValueError):
                    continue
                if user_id > 0:
                    roster_user_ids.add(user_id)
        raw_roster_names = data.get("account_roster_names_by_user_id", {})
        roster_names_by_user_id: dict[int, str] = {}
        if isinstance(raw_roster_names, dict):
            for raw_user_id, raw_name in raw_roster_names.items():
                try:
                    user_id = int(raw_user_id)
                except (TypeError, ValueError):
                    continue
                if user_id <= 0:
                    continue
                if user_id not in roster_user_ids:
                    continue
                if not isinstance(raw_name, str):
                    continue
                clean_name = raw_name.strip()
                if clean_name:
                    roster_names_by_user_id[user_id] = clean_name

        self.interval_var.set(interval)
        self.auto_realign_var.set(auto_realign)
        with self.state_lock:
            self.loaded_enabled_by_pid = enabled_by_pid
            self.instance_interval_override = interval_override
            self.instance_pattern_override = pattern_override
            self.instance_priority_by_pid = priority_by_pid
            self.account_roster_user_ids = set(roster_user_ids)
            self.account_roster_names_by_user_id = dict(roster_names_by_user_id)
            self.account_roster_missing_since_by_user_id.clear()
        jump_mode = str(data.get("jump_mode", "all")).strip().lower()
        if jump_mode not in {"all", "round", "weighted"}:
            jump_mode = "all"
        self.jump_mode_var.set(jump_mode)
        self.pause_enabled_var.set(bool(data.get("pause_enabled", False)))
        self.pause_start_var.set(str(data.get("pause_start", "02:00")))
        self.pause_end_var.set(str(data.get("pause_end", "06:00")))
        self.webhook_enabled_var.set(bool(data.get("webhook_enabled", False)))
        self.webhook_url_var.set(str(data.get("webhook_url", "")))
        self.webhook_biome_url_var.set(str(data.get("webhook_biome_url", "")).strip())
        self.webhook_recovery_url_var.set(str(data.get("webhook_recovery_url", "")).strip())
        self.webhook_health_url_var.set(str(data.get("webhook_health_url", "")).strip())
        self.webhook_vendor_url_var.set(str(data.get("webhook_vendor_url", "")).strip())
        self.watchdog_enabled_var.set(bool(data.get("watchdog_enabled", True)))
        self.watchdog_threshold_var.set(str(data.get("watchdog_threshold", "12")))
        self.watchdog_no_windows_threshold_var.set(str(data.get("watchdog_no_windows_threshold", "24")))
        self.watchdog_jump_fail_threshold_var.set(str(data.get("watchdog_jump_fail_threshold", "8")))
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
        self.hotkey_guard_var.set(bool(data.get("hotkey_guard", True)))
        self.start_when_windows_found_var.set(bool(data.get("wait_for_windows", True)))
        self.safe_mode_var.set(bool(data.get("safe_mode", False)))
        self.roblox_input_pause_enabled = bool(data.get("roblox_input_pause_enabled", True))
        try:
            pause_seconds = float(data.get("roblox_input_pause_seconds", 2.0))
        except (TypeError, ValueError):
            pause_seconds = 2.0
        self.roblox_input_pause_seconds = max(0.2, min(pause_seconds, 10.0))
        self.manual_pause_minutes_var.set(str(data.get("quick_pause_minutes", "10")))
        self.profile_hotkey_1_var.set(str(data.get("profile_hotkey_1", "default")).strip() or "default")
        self.profile_hotkey_2_var.set(str(data.get("profile_hotkey_2", "farming")).strip() or "farming")
        self.profile_hotkey_3_var.set(str(data.get("profile_hotkey_3", "overnight")).strip() or "overnight")
        self.startup_restore_enabled_var.set(bool(data.get("startup_restore_enabled", False)))
        self.startup_preset_var.set(str(data.get("startup_preset", "default")).strip() or "default")
        self.startup_auto_start_var.set(bool(data.get("startup_auto_start", False)))
        self.startup_auto_align_var.set(bool(data.get("startup_auto_align", False)))
        self.scheduler_enabled_var.set(bool(data.get("scheduler_enabled", False)))
        self.scheduler_slot1_time_var.set(str(data.get("scheduler_slot1_time", "08:00")))
        self.scheduler_slot1_preset_var.set(str(data.get("scheduler_slot1_preset", "day")))
        self.scheduler_slot2_time_var.set(str(data.get("scheduler_slot2_time", "23:30")))
        self.scheduler_slot2_preset_var.set(str(data.get("scheduler_slot2_preset", "overnight")))
        self.process_limiter_enabled_var.set(bool(data.get("process_limiter_enabled", False)))
        self.process_limiter_auto_mode_var.set(bool(data.get("process_limiter_auto_mode", False)))
        self.process_limiter_only_when_running_var.set(bool(data.get("process_limiter_only_when_running", True)))
        self.process_limiter_target_percent_var.set(str(data.get("process_limiter_target_percent", "40")))
        self.process_limiter_cycle_ms_var.set(str(data.get("process_limiter_cycle_ms", "180")))
        self.instance_relaunch_enabled_var.set(bool(data.get("instance_relaunch_enabled", False)))
        self.instance_relaunch_grace_seconds_var.set(str(data.get("instance_relaunch_grace_seconds", "45")))
        self.instance_relaunch_max_per_hour_var.set(str(data.get("instance_relaunch_max_per_hour", "8")))
        self.instance_relaunch_launch_target_var.set(str(data.get("instance_relaunch_launch_target", "")).strip())
        self.account_roster_enabled_var.set(bool(data.get("account_roster_enabled", False)))
        self.watchdog_standby_mode_var.set(bool(data.get("watchdog_standby_mode", False)))
        self.private_server_place_id_var.set(str(data.get("private_server_place_id", "")).strip())
        self.private_server_code_var.set(str(data.get("private_server_code", "")).strip())
        if self.process_limiter_enabled_var.get() and not self.process_limiter_supported:
            self.process_limiter_enabled_var.set(False)
            self.process_limiter_auto_mode_var.set(False)
        if self.process_limiter_auto_mode_var.get():
            self.process_limiter_target_percent_var.set("0")
            self.process_limiter_only_when_running_var.set(False)
        self.health_alert_enabled_var.set(bool(data.get("health_alert_enabled", True)))
        self.health_alert_minutes_var.set(str(data.get("health_alert_minutes", "3")))
        self.autosave_enabled_var.set(bool(data.get("autosave_enabled", True)))
        self.autosave_minutes_var.set(str(data.get("autosave_minutes", "2")))
        self.biome_alerts_enabled_var.set(bool(data.get("biome_alerts_enabled", False)))
        self.rare_biome_var.set(str(data.get("rare_biome", "GLITCHED")).strip().upper() or "GLITCHED")
        self.rare_biome_confirm_enabled_var.set(bool(data.get("rare_biome_confirm_enabled", True)))
        self.rare_biome_confirm_seconds_var.set(str(data.get("rare_biome_confirm_seconds", "4")))
        biome_action = str(data.get("biome_action", "webhook")).strip().lower()
        if biome_action not in {"webhook", "pause_5m", "load_preset"}:
            biome_action = "webhook"
        self.biome_action_var.set(biome_action)
        self.biome_action_preset_var.set(str(data.get("biome_action_preset", "default")).strip())
        self.vendor_alerts_enabled_var.set(bool(data.get("vendor_alerts_enabled", False)))
        self.vendor_alert_cooldown_var.set(str(data.get("vendor_alert_cooldown", "180")))
        self.recovery_enabled_var.set(bool(data.get("recovery_enabled", True)))
        self._apply_selected_theme()
        self._sync_runtime_settings_from_ui()
        self._set_global_hotkeys_enabled(self.hotkeys_enabled_var.get(), log_result=False)
        self._refresh_account_roster_status()
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
        if hasattr(self, "startup_preset_combo"):
            self.startup_preset_combo.configure(values=names)
        if self.preset_name_var.get().strip() not in names:
            self.preset_name_var.set(names[0])
        if self.startup_preset_var.get().strip() not in names:
            self.startup_preset_var.set(names[0])

    @staticmethod
    def _atomic_write_bytes(path: str, data: bytes) -> None:
        directory = os.path.dirname(path) or "."
        os.makedirs(directory, exist_ok=True)
        fd, temp_path = tempfile.mkstemp(prefix=".tmp-", suffix=".part", dir=directory)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_path, path)
        except Exception:
            try:
                os.remove(temp_path)
            except OSError:
                pass
            raise

    @classmethod
    def _atomic_write_json(cls, path: str, data: Any) -> None:
        payload = json.dumps(data, indent=2).encode("utf-8") + b"\n"
        cls._atomic_write_bytes(path, payload)

    def save_preset(self) -> None:
        name = self._sanitize_preset_name(self.preset_name_var.get())
        path = self._preset_path(name)
        data = self._collect_config_data()
        try:
            self._atomic_write_json(path, data)
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
        configured_webhook_urls = self._configured_webhook_urls()
        webhook_on = self.webhook_enabled_var.get() and bool(configured_webhook_urls)
        try:
            self._validate_pause_schedule()
            pause_validation = "OK"
        except Exception as exc:
            pause_validation = f"INVALID ({exc})"
        webhook_validation = "OK"
        if self.webhook_enabled_var.get():
            if not configured_webhook_urls:
                webhook_validation = "INVALID (no URL configured)"
            else:
                invalid = [url for url in configured_webhook_urls if not self._is_valid_webhook_url(url)]
                webhook_validation = "OK" if not invalid else "INVALID (must be HTTPS URL)"
        checks = [
            f"{APP_NAME} version: {APP_VERSION}",
            f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"vgamepad import: {self._vgamepad_status()}",
            f"Gamepad session: {'READY' if self.gamepad is not None else 'NOT INITIALIZED'}",
            f"Roblox windows detected: {len(windows)}",
            f"Biome log source: {latest_log}",
            f"Current biome: {self.current_biome_name} ({self.current_biome_source})",
            f"Theme: {self.current_theme_name}",
            f"Anti-idle pattern: {self.anti_idle_pattern_var.get()}",
            f"Jump mode: {self.jump_mode_var.get()}",
            f"Global hotkeys: {'ON' if self.hotkeys_enabled_var.get() else 'OFF'} (Ctrl+Alt+S/J/R/T/1/2/3)",
            f"Hotkey safety lock: {'ON' if self.hotkey_guard_var.get() else 'OFF'} (blocks Start/Stop + Tray while Roblox focused)",
            f"Wait for windows mode: {'ON' if self.start_when_windows_found_var.get() else 'OFF'}",
            f"Safe mode: {'ON' if self.safe_mode_var.get() else 'OFF'}",
            f"Scheduler: {'ON' if self.scheduler_enabled_var.get() else 'OFF'} ({self.scheduler_slot1_time_var.get()}->{self.scheduler_slot1_preset_var.get()}, {self.scheduler_slot2_time_var.get()}->{self.scheduler_slot2_preset_var.get()})",
            f"Process limiter: {'ON' if self.process_limiter_enabled_var.get() else 'OFF'} ({'AUTO 0% freeze' if self.process_limiter_auto_mode_var.get() else (self.process_limiter_target_percent_var.get().strip() or '40') + '%'} / {self.process_limiter_cycle_ms_var.get().strip() or '180'}ms, {'run-only' if self.process_limiter_only_when_running_var.get() else 'always'})",
            f"Process limiter runtime support: {'YES' if self.process_limiter_supported else 'NO'}",
            f"Process limiter status: {self.process_limiter_status_var.get()}",
            f"Auto-relaunch dropped instances: {'ON' if self.instance_relaunch_enabled_var.get() else 'OFF'} (grace={self.instance_relaunch_grace_seconds_var.get().strip() or '45'}s, max/hr={self.instance_relaunch_max_per_hour_var.get().strip() or '8'})",
            f"Auto-relaunch target: {self.instance_relaunch_launch_target_var.get().strip() or 'auto-detect launcher'}",
            f"Auto-relaunch status: {self.instance_relaunch_status_var.get()}",
            f"Watchdog standby mode: {'ON' if self.watchdog_standby_mode_var.get() else 'OFF'}",
            f"Account roster mode: {'ON' if self.account_roster_enabled_var.get() else 'OFF'}",
            f"Account roster locked: {len(self.account_roster_user_ids)} account(s)",
            f"Instance health alerts: {'ON' if self.health_alert_enabled_var.get() else 'OFF'} ({self.health_alert_minutes_var.get().strip() or '3'} min)",
            f"Recovery auto-save: {'ON' if self.autosave_enabled_var.get() else 'OFF'} ({self.autosave_minutes_var.get().strip() or '2'} min)",
            f"Recovery sequence: {'ON' if self.recovery_enabled_var.get() else 'OFF'}",
            f"Watchdog thresholds: no-windows={self.watchdog_no_windows_threshold_var.get().strip() or '24'} jump-fail={self.watchdog_jump_fail_threshold_var.get().strip() or '8'}",
            f"Webhook configured: {'YES' if webhook_on else 'NO'}",
            f"Webhook routes configured: {len(configured_webhook_urls)}",
            f"Webhook URL validation: {webhook_validation}",
            f"Pause schedule validation: {pause_validation}",
            f"Rare biome alerts: {'ON' if self.biome_alerts_enabled_var.get() else 'OFF'} ({self.rare_biome_var.get().strip().upper() or 'GLITCHED'})",
            f"Rare biome confirm gate: {'ON' if self.rare_biome_confirm_enabled_var.get() else 'OFF'} ({self.rare_biome_confirm_seconds_var.get().strip() or '4'}s)",
            f"Rare biome action: {self.biome_action_var.get()} ({self.biome_action_preset_var.get().strip() or 'default'})",
            f"Vendor alerts: {'ON' if self.vendor_alerts_enabled_var.get() else 'OFF'} (cooldown={self.vendor_alert_cooldown_var.get().strip() or '180'}s)",
            f"Private server helper: place={self.private_server_place_id_var.get().strip() or '-'} code={'set' if self.private_server_code_var.get().strip() else 'empty'}",
            f"Latest release URL: {self.latest_release_url}",
            f"Singleton cleanup interval: {self.singleton_cleanup_attempt_interval_seconds:.0f}s, max attempts per PID: {self.singleton_cleanup_max_attempts_per_pid}",
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
        default_name = f"stayactive-debug-{stamp}.zip"
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
        recovery_history = self.recovery_timeline[-180:]

        try:
            with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                zf.writestr("diagnostics.txt", diagnostics_body + "\n")
                zf.writestr("stayactive-log-tail.txt", "\n".join(app_log_tail) + "\n")
                zf.writestr("biome-history.txt", "\n".join(biome_history) + "\n")
                zf.writestr("recovery-timeline.txt", "\n".join(recovery_history) + "\n")
                if os.path.exists(self.config_path):
                    zf.write(self.config_path, arcname="stayactive_config.json")
                if os.path.exists(self.theme_config_path):
                    zf.write(self.theme_config_path, arcname="stayactive_themes.json")
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
            self._atomic_write_json(self.config_path, data)
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
            normalized, changed = self._normalize_config_payload(data)
            self._apply_config_data(normalized)
            if changed:
                try:
                    self._atomic_write_json(self.config_path, normalized)
                except Exception:
                    pass
            self.log(f"Config loaded: {self.config_path}")
        except Exception as exc:
            backup_path = self._backup_invalid_config()
            self.log(f"Config load failed, using in-memory defaults: {exc}")
            if backup_path:
                self.log(f"Invalid config backup saved: {backup_path}")
            if not silent:
                msg = f"{exc}\n\nUsing current defaults."
                if backup_path:
                    msg += f"\nBackup: {backup_path}"
                messagebox.showerror("Load config failed", msg)

    def export_instances(self, mode: str) -> None:
        rows: list[dict[str, Any]] = []
        with self.state_lock:
            for hwnd, title, pid, pname in self.window_map:
                attempts = self.instance_attempt_count.get(hwnd, 0)
                fails = self.instance_fail_count.get(hwnd, 0)
                reliability = None if attempts == 0 else max(0.0, (attempts - fails) * 100 / attempts)
                rows.append(
                    {
                        "enabled": self.instance_enabled_by_hwnd.get(hwnd, True),
                        "pid": pid,
                        "hwnd": hwnd,
                        "process": pname,
                        "username": self.pid_username.get(pid, ""),
                        "identity": self.pid_identity_confidence.get(pid, "unknown"),
                        "equipped_aura": self.pid_equipped_aura.get(pid, ""),
                        "last_jump": self.instance_last_jump.get(hwnd),
                        "priority": self.instance_priority_by_pid.get(pid, 1),
                        "interval_override": self.instance_interval_override.get(pid),
                        "pattern_override": self.instance_pattern_override.get(pid, ""),
                        "reliability_percent": reliability,
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
            writer = csv.DictWriter(
                f,
                fieldnames=[
                    "enabled",
                    "pid",
                    "hwnd",
                    "process",
                    "username",
                    "identity",
                    "equipped_aura",
                    "last_jump",
                    "priority",
                    "interval_override",
                    "pattern_override",
                    "reliability_percent",
                    "title",
                ],
            )
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
        target = self.latest_release_url or "https://github.com/0bl1terate3/StayActive/releases/latest"
        opened = webbrowser.open(target)
        if opened:
            self._record_event("Opened release page")
        else:
            messagebox.showinfo("Release page", target)

    def _start_background_update_check(self) -> None:
        threading.Thread(target=self._background_update_worker, daemon=True).start()

    def _background_update_worker(self) -> None:
        release = self._fetch_json("https://api.github.com/repos/0bl1terate3/StayActive/releases/latest")
        try:
            self._enqueue_on_ui_thread(self._apply_update_info, release, True)
        except Exception:
            pass

    def _apply_update_info(self, release: dict[str, Any] | None, silent: bool) -> None:
        if not release:
            self.update_banner_var.set("Update check failed")
            if not silent:
                messagebox.showinfo("Updates", "Could not check for updates right now.")
            return
        tag = str(release.get("tag_name", "")).strip()
        url = str(release.get("html_url", "")).strip()
        body = str(release.get("body", "") or "").strip()
        asset_url = ""
        asset_name = ""
        assets = release.get("assets")
        if isinstance(assets, list):
            for asset in assets:
                if not isinstance(asset, dict):
                    continue
                candidate_name = str(asset.get("name", "")).strip()
                candidate_url = str(asset.get("browser_download_url", "")).strip()
                if candidate_name.lower().endswith(".exe") and candidate_url:
                    asset_name = candidate_name
                    asset_url = candidate_url
                    break
        if url:
            self.latest_release_url = url
        self.latest_release_asset_url = asset_url
        self.latest_release_asset_name = asset_name
        self.latest_release_tag_var.set(f"Latest: {tag or '-'}")
        if not tag:
            self.update_banner_var.set("Latest release tag unavailable")
            if not silent:
                messagebox.showinfo("Updates", "Latest release tag was not found.")
            return
        latest = self._parse_version_parts(tag)
        current = self._parse_version_parts(APP_VERSION)
        if latest > current:
            self.update_banner_var.set(f"Update available: {tag}")
            if not silent:
                snippet = ""
                if body:
                    for line in body.splitlines():
                        s = line.strip()
                        if s:
                            snippet = s[:180]
                            break
                notes = f"\n\nNotes: {snippet}" if snippet else ""
                prompt = f"Latest: {tag}\nCurrent: v{APP_VERSION}\n\nOpen download now?{notes}"
                if messagebox.askyesno("Update Available", prompt):
                    self.download_latest_release_asset()
            return
        if latest == current:
            self.update_banner_var.set("You are up to date")
            if not silent:
                messagebox.showinfo("Updates", f"You're up to date ({APP_VERSION}).")
            return
        self.update_banner_var.set("Local build is newer than latest release")
        if not silent:
            messagebox.showinfo("Updates", f"You're on a newer local build (v{APP_VERSION}) than latest release ({tag}).")

    def check_for_updates(self) -> None:
        release = self._fetch_json("https://api.github.com/repos/0bl1terate3/StayActive/releases/latest")
        self._apply_update_info(release, silent=False)
        if release and isinstance(release.get("tag_name"), str):
            self._record_event(f"Update check: {release.get('tag_name')}")

    def download_latest_release_asset(self) -> None:
        if self.latest_release_asset_url:
            opened = webbrowser.open(self.latest_release_asset_url)
            if opened:
                self._record_event(f"Opened asset: {self.latest_release_asset_name or 'release exe'}")
                return
        self.open_latest_release_page()

    def test_webhook_health(self) -> None:
        if not self.webhook_enabled_var.get():
            messagebox.showinfo("Webhook test", "Enable webhook first.")
            return
        preferred = self.webhook_url_var.get().strip()
        urls = self._configured_webhook_urls()
        if not urls:
            messagebox.showerror("Webhook test", "Configure at least one webhook URL first.")
            return
        if preferred and self._is_valid_webhook_url(preferred):
            url = preferred
        else:
            valid_urls = [candidate for candidate in urls if self._is_valid_webhook_url(candidate)]
            if not valid_urls:
                messagebox.showerror("Webhook test", "All configured webhook URLs are invalid (must be HTTPS).")
                return
            url = valid_urls[0]

        def _worker() -> None:
            payload = {"content": f"{APP_NAME} webhook test at {datetime.now().strftime('%H:%M:%S')}"}
            data = json.dumps(payload).encode("utf-8")
            req = urlrequest.Request(
                url,
                data=data,
                headers={"Content-Type": "application/json", "User-Agent": APP_USER_AGENT},
                method="POST",
            )
            started = time.perf_counter()
            try:
                with urlrequest.urlopen(req, timeout=10) as resp:
                    code = getattr(resp, "status", 204)
                elapsed_ms = int((time.perf_counter() - started) * 1000)
                self._enqueue_on_ui_thread(
                    messagebox.showinfo,
                    "Webhook test",
                    f"Success (HTTP {code})\nLatency: {elapsed_ms} ms\nTarget: {url}",
                )
                self.log(f"Webhook test success ({elapsed_ms} ms).")
            except Exception as exc:
                self._enqueue_on_ui_thread(messagebox.showerror, "Webhook test", f"Failed: {exc}")
                self.log(f"Webhook test failed: {exc}")

        threading.Thread(target=_worker, daemon=True).start()

    def export_portable_bundle(self) -> None:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        default_name = f"stayactive-portable-{stamp}.zip"
        path = filedialog.asksaveasfilename(
            defaultextension=".zip",
            initialfile=default_name,
            filetypes=[("Zip archive", "*.zip")],
        )
        if not path:
            return
        self.save_config()
        try:
            checksums: dict[str, str] = {}
            with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                if os.path.exists(self.config_path):
                    zf.write(self.config_path, arcname="stayactive_config.json")
                    with open(self.config_path, "rb") as handle:
                        checksums["stayactive_config.json"] = hashlib.sha256(handle.read()).hexdigest()
                if os.path.exists(self.theme_config_path):
                    zf.write(self.theme_config_path, arcname="stayactive_themes.json")
                    with open(self.theme_config_path, "rb") as handle:
                        checksums["stayactive_themes.json"] = hashlib.sha256(handle.read()).hexdigest()
                if os.path.isdir(self.presets_dir):
                    for name in os.listdir(self.presets_dir):
                        full = os.path.join(self.presets_dir, name)
                        if os.path.isfile(full) and name.lower().endswith(".json"):
                            arc = os.path.join("presets", name).replace("\\", "/")
                            zf.write(full, arcname=arc)
                            with open(full, "rb") as handle:
                                checksums[arc] = hashlib.sha256(handle.read()).hexdigest()
                metadata = {
                    "app": APP_NAME,
                    "version": APP_VERSION,
                    "exported_at": datetime.now().isoformat(timespec="seconds"),
                    "checksums_sha256": checksums,
                }
                zf.writestr("portable-metadata.json", json.dumps(metadata, indent=2))
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
                expected_checksums: dict[str, str] = {}
                if "portable-metadata.json" in members:
                    try:
                        meta = json.loads(zf.read("portable-metadata.json").decode("utf-8", errors="ignore"))
                        if isinstance(meta, dict):
                            src_version = str(meta.get("version", "")).strip()
                            if src_version:
                                self.log(f"Portable import metadata version: {src_version}")
                            raw_checksums = meta.get("checksums_sha256")
                            if isinstance(raw_checksums, dict):
                                for name, digest in raw_checksums.items():
                                    if isinstance(name, str) and isinstance(digest, str) and digest.strip():
                                        expected_checksums[name.replace("\\", "/")] = digest.strip().lower()
                    except Exception as exc:
                        self.log(f"Portable metadata parse warning: {exc}")

                staged_files: list[tuple[str, bytes]] = []

                def _stage_member(member_name: str, target_path: str) -> None:
                    content = zf.read(member_name)
                    normalized = member_name.replace("\\", "/")
                    if expected_checksums:
                        expected = expected_checksums.get(normalized)
                        if not expected:
                            raise ValueError(f"Missing checksum for '{normalized}' in portable metadata.")
                        actual = hashlib.sha256(content).hexdigest().lower()
                        if actual != expected:
                            raise ValueError(f"Checksum mismatch for '{normalized}'.")
                    staged_files.append((target_path, content))

                if "stayactive_config.json" in members:
                    _stage_member("stayactive_config.json", self.config_path)
                if "stayactive_themes.json" in members:
                    _stage_member("stayactive_themes.json", self.theme_config_path)

                os.makedirs(self.presets_dir, exist_ok=True)
                for name in members:
                    normalized = name.replace("\\", "/")
                    if normalized.startswith("presets/") and normalized.lower().endswith(".json"):
                        target = os.path.join(self.presets_dir, os.path.basename(normalized))
                        _stage_member(name, target)

                for target, content in staged_files:
                    self._atomic_write_bytes(target, content)
            self._refresh_preset_list()
            self._load_custom_themes()
            self.load_config(silent=True)
            self.log(f"Portable bundle imported: {path}")
            self._record_event("Portable import completed")
        except Exception as exc:
            messagebox.showerror("Import portable bundle failed", str(exc))

    def build_exe(self) -> None:
        exe_name = APP_NAME.replace(" ", "")
        icon_asset = self._resource_path(APP_ICON_ICO)
        icon_png_asset = self._resource_path(APP_ICON_PNG)
        cmd = [
            sys.executable,
            "-m",
            "PyInstaller",
            "--noconfirm",
            "--clean",
            "--onefile",
            "--windowed",
            "--uac-admin",
            "--name",
            exe_name,
        ]
        if os.path.exists(icon_asset):
            cmd.extend(["--icon", icon_asset, "--add-data", f"{icon_asset};."])
        else:
            self.log(f"Build EXE warning: icon not found ({APP_ICON_ICO}), continuing without --icon.")
        if os.path.exists(icon_png_asset):
            cmd.extend(["--add-data", f"{icon_png_asset};."])
        else:
            self.log(f"Build EXE warning: PNG icon not found ({APP_ICON_PNG}).")
        cmd.extend(
            [
            "--collect-binaries",
            "vgamepad",
            "--collect-data",
            "vgamepad",
            "--collect-submodules",
            "vgamepad",
            "main.py",
            ]
        )

        def _worker() -> None:
            self.log("Build EXE started...")
            try:
                source_dir = os.path.dirname(os.path.abspath(__file__))
                result = subprocess.run(cmd, cwd=source_dir, capture_output=True, text=True, timeout=600)
                if result.returncode == 0:
                    self.log(f"Build EXE complete: dist/{exe_name}.exe")
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
            self._enqueue_on_ui_thread(self.restore_from_tray)

        def _quit() -> None:
            self._enqueue_on_ui_thread(self.on_close)

        menu = pystray.Menu(
            pystray.MenuItem("Show", lambda _icon, _item: _show()),
            pystray.MenuItem("Start", lambda _icon, _item: self._enqueue_on_ui_thread(self.start)),
            pystray.MenuItem("Stop", lambda _icon, _item: self._enqueue_on_ui_thread(self.stop)),
            pystray.MenuItem("Quit", lambda _icon, _item: _quit()),
        )
        self.tray_icon = pystray.Icon(APP_NAME, self._make_tray_image(), APP_NAME, menu)
        threading.Thread(target=self.tray_icon.run, daemon=True).start()
        self.log("Minimized to tray.")

    def restore_from_tray(self) -> None:
        self._repair_main_window_if_needed(force=True, reason="tray-restore")
        if self.tray_icon is not None:
            self.tray_icon.stop()
            self.tray_icon = None
        self.tray_enabled = False
        self.log("Restored from tray.")

    def on_close(self) -> None:
        self.stop()
        self._stop_process_limiter_worker()
        self._write_recovery_snapshot(force=True)
        self.save_config()
        self._write_session_report("shutdown")
        self._unregister_global_hotkeys()
        self._clear_recovery_state_marker()
        if self.hotkey_help_window is not None and self.hotkey_help_window.winfo_exists():
            self.hotkey_help_window.destroy()
            self.hotkey_help_window = None
        if self.tray_icon is not None:
            self.tray_icon.stop()
            self.tray_icon = None
        self.root.destroy()


def main() -> None:
    root = tk.Tk()
    app = AntiAfkApp(root)
    app.log("Ready. Configure instances and press Start.")
    try:
        root.mainloop()
    except Exception:
        details = traceback.format_exc()
        path = app._write_crash_report("main-loop", details)
        if path:
            try:
                messagebox.showerror("Crash", f"Unexpected error. Crash report saved:\n{path}")
            except Exception:
                pass
        raise


if __name__ == "__main__":
    main()


