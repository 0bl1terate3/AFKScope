'''AFKScope''' is a multi-instance '''Sol's RNG''' anti-AFK macro for Windows. It is designed for stability, visibility, and control across multiple Roblox clients, with focus spoofing, per-instance toggles, biome tracking, diagnostics, and webhook support.

== Quick Links ==
* [https://github.com/0bl1terate3/AFKScope/releases/latest Latest Release (EXE)]
* [https://github.com/0bl1terate3/AFKScope Source Code]
* [https://github.com/0bl1terate3/AFKScope/issues Issue Tracker]

[[File:AFKScope UI.png|center|thumb|900px|AFKScope main interface (Controls tab)]]

== Feature Summary ==
{| class="wikitable"
! Area
! What AFKScope Provides
|-
| Multi-instance Control
| Detects multiple Roblox windows, per-instance enable/disable, grid align/restore tools
|-
| Anti-AFK Engine
| ViGEm focus spoofing jump dispatch, all-at-once and round-robin modes, anti-idle patterns
|-
| Monitoring
| Biome badge/history, identity lookup with confidence labels, session stats and timeline
|-
| Reliability
| Watchdog recovery, safe pause schedule, diagnostics panel, debug bundle export
|-
| Integrations
| Discord webhook alerts, rare biome alerts, release update checker
|-
| UX
| Theme dropdown, Theme Maker (custom themes), tray mode, preset management
|}

== Installation ==
=== Option 1: Standalone EXE (Recommended) ===
# Download from [https://github.com/0bl1terate3/AFKScope/releases/latest GitHub Releases]
# Extract and run <code>AFKScope.exe</code>

=== Option 2: Run from Source ===
==== Prerequisites ====
* Windows 10/11
* Python 3.10+
* [https://vigembus.com/ ViGEmBus driver]

==== Setup ====
# Clone or download the repository
# Install dependencies: <code>pip install -r requirements.txt</code>
# Run: <code>python main.py</code>

==== Optional Dependencies ====
* <code>pystray</code> + <code>Pillow</code> for tray mode

== Usage ==
=== First-Time Setup ===
# Launch AFKScope
# Click '''Refresh''' to detect Roblox windows
# Toggle instances in the '''Instances''' tab (double-click Enabled column)
# Set jump interval and jump mode (All-at-once or Round-robin)
# (Optional) Configure webhook URL and rare biome alert settings
# Click '''Start'''

=== Main Controls ===
* '''Start / Stop / Jump Now''' - controls the anti-AFK loop
* '''Refresh''' - rescans active Roblox windows
* '''Align / Restore''' - grid layout and restoration for detected windows
* '''Retry Identity''' - reruns username/avatar lookup for selected instance(s)
* '''To Tray''' - minimizes to system tray

=== Automation Options ===
* '''Safe pause schedule''' - pause automation during configured hours
* '''Watchdog + recovery''' - resets anti-AFK session if cycles fail repeatedly
* '''Anti-idle pattern''' - balanced/subtle/aggressive/randomized
* '''Rare biome action''' - webhook or preset-based response options

== Configuration Files ==
* <code>afkscope_config.json</code> - main settings
* <code>afkscope_themes.json</code> - custom themes created in Theme Maker
* <code>presets/*.json</code> - saved profile presets

== Export / Import ==
* Instance export: JSON and CSV
* Debug bundle export (logs + diagnostics)
* Portable bundle export/import for config + presets + themes

== Troubleshooting ==
=== App process starts but no window appears ===
* Use the latest release build
* Ensure Python and dependencies are healthy if running from source
* If building from source, prefer Python 3.10 for best PyInstaller stability

=== vgamepad / ViGEm errors ===
* Install or reinstall ViGEmBus
* Restart the app after driver installation

=== No Roblox windows detected ===
* Ensure Roblox clients are open and visible
* Click '''Refresh''' manually
* Avoid running Roblox in incompatible environments where window titles/process visibility are restricted

=== Webhook alerts not sending ===
* Verify webhook URL is valid
* Confirm webhook alerts are enabled in AFKScope settings
* Check firewall/network restrictions

== Notes ==
* Macros are community tools and may behave differently across systems.
* Use responsibly and follow current platform/game rules.

== Credits ==
* '''Creator''': 0bl1terate3
* '''Project''': [https://github.com/0bl1terate3/AFKScope AFKScope]
