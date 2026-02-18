# AFKScope

AFKScope is a Windows desktop macro for Sol's RNG that sends timed virtual controller jumps through `vgamepad` + ViGEmBus.

![AFKScope UI](assets/afkscope-ui-v2.png)

## Features

- Multi-instance Roblox detection and per-instance enable/disable.
- Focus spoofed jump dispatch (no hard window switching workflow).
- `All-at-once` and `Round-robin` jump modes.
- Window grid align + restore original layouts.
- Username identity mapping + avatar headshots per PID.
- Biome tracking with colored status chip and health panel reporting.
- Session stats, watchdog reset, safe pause schedule, webhook alerts.
- Config save/load and JSON/CSV instance export.
- Light/dark mode with smooth animated transition.
- Optional tray support (`pystray`, `pillow`).

## Requirements

- Windows
- Python 3.10+
- ViGEmBus installed: https://vigembus.com/

## Setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Optional tray support:

```powershell
pip install pystray pillow
```

## Run

```powershell
python main.py
```

## Build EXE

```powershell
python -m PyInstaller --noconfirm --clean --onefile --windowed --name AFKScope --icon "AFKSCOPE ICON.ico" --add-data "AFKSCOPE ICON.ico;." --collect-binaries vgamepad --collect-data vgamepad --collect-submodules vgamepad main.py
```

## Release

Current release target: `v0.1` with `dist/AFKScope.exe`.

