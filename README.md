<p align="center">
  <img src="AFKSCOPE%20ICON.png" alt="AFKScope Icon" width="96" />
</p>

<h1 align="center">AFKScope</h1>

<p align="center">
  Multi-instance Sol's RNG anti-AFK macro for Windows using ViGEmBus + vgamepad.
</p>

<p align="center">
  <a href="https://github.com/0bl1terate3/AFKScope/releases/latest"><img src="https://img.shields.io/github/v/release/0bl1terate3/AFKScope?style=for-the-badge&label=release" alt="release"></a>
  <a href="https://github.com/0bl1terate3/AFKScope/releases"><img src="https://img.shields.io/github/downloads/0bl1terate3/AFKScope/total?style=for-the-badge&label=downloads" alt="downloads"></a>
  <a href="https://github.com/0bl1terate3/AFKScope/releases/latest"><img src="https://img.shields.io/github/downloads/0bl1terate3/AFKScope/latest/total?style=for-the-badge&label=latest%20downloads" alt="latest downloads"></a>
  <a href="https://github.com/0bl1terate3/AFKScope/stargazers"><img src="https://img.shields.io/github/stars/0bl1terate3/AFKScope?style=for-the-badge" alt="stars"></a>
  <a href="https://github.com/0bl1terate3/AFKScope/issues"><img src="https://img.shields.io/github/issues/0bl1terate3/AFKScope?style=for-the-badge" alt="issues"></a>
</p>

<p align="center">
  <a href="https://github.com/0bl1terate3/AFKScope/releases/latest"><b>Download Latest EXE</b></a>
</p>

![AFKScope UI](assets/afkscope-ui-v2.png)

## Features

- Multi-instance Roblox detection with per-instance enable/disable.
- Focus spoofed jump dispatch on timer (`All-at-once` and `Round-robin`).
- Window align grid + one-click restore.
- Username identity detection, confidence state, and avatar headshots.
- Biome tracking with colored badge + health panel reporting.
- Session stats, watchdog reset, safe pause schedule, and webhook alerts.
- Config save/load and JSON/CSV export.
- Light/dark mode with smooth animated transition.
- Optional tray controls (`pystray` + `pillow`).

## Requirements

- Windows
- Python 3.10+
- ViGEmBus driver: https://vigembus.com/

## Install

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

