# Fix Log

Tracks targeted post-release fixes and stability updates.

## v0.1.5 Hotfixes (2026-02-19)

- Fixed identity resolution conflicts for multi-instance Roblox sessions.
  - Candidate logs are now ranked using process creation time vs log start timestamp.
  - Log hints are no longer shared across active PIDs.
  - Stale PID log hints are cleared on conflict before retry.
  - Identity lookups are serialized per refresh pass to reduce race conditions.
- Improved identity conflict behavior between active instances.
  - Duplicate username/user ID mappings are marked as `conflict` and retried.
  - Conflict logs are throttled to reduce spam.
- Fixed thread-safety risk in crash reporting.
  - Crash report generation uses buffered log lines from background threads instead of direct Tk widget reads.
- Hardened identity worker error handling.
  - Identity lookup worker is guarded so failures report cleanly instead of destabilizing UI flow.
- Added hotkey safety lock behavior.
  - `Start/Stop` and `To Tray` hotkeys are blocked while Roblox is focused (when enabled).
- Stabilized process/singleton cleanup behavior.
  - Singleton event cleanup attempts are now bounded per PID to avoid excessive repeated handle operations.
- Added watchdog auto-relaunch utility controls.
  - Optional relaunch for dropped instances with grace window and hourly cap.
