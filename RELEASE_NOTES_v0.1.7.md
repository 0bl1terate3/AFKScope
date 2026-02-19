# StayActive v0.1.7

`v0.1.7` ships the roadmap implementation wave after `v0.1.6`, focused on automation foundations, identity reliability tooling, and relaunch decision transparency.

## Highlights

- Added **Rules MVP (Phase 1)** with normalized in-app events and a lightweight in-process automation engine.
- Added **Identity Reliability Center (Phase 2 MVP)** with per-instance confidence reasons, conflict/retry telemetry, and operator quick actions.
- Added **Relaunch Playbooks + Decision Tracing (Phase 3 MVP)** for explainable recovery behavior and faster triage.

## Automation Rules MVP (Phase 1)

- Added normalized event envelopes for internal automation:
  - `type`, `category`, `severity`, `timestamp`, `source`, `payload`
- Added rules evaluation primitives:
  - trigger matching
  - optional condition checks
  - safe action dispatch
  - cooldown/debounce protections
- Added compact Rules UI controls:
  - Rules mode enable/disable
  - Verbose rule logs toggle
  - execution status and recent rule activity visibility
- Added persisted rules configuration with validation/normalization on load.

## Identity Reliability Center (Phase 2 MVP)

- Added compact identity reliability panel for selected instances:
  - confidence label + reason
  - conflict counters and latest conflict reason
  - retry counters and last retry timing
  - session pin state visibility
- Added quick actions:
  - Retry Identity
  - Clear Identity Cache
  - Pin Session / Unpin Session
- Added **session-only identity pinning** safeguards:
  - PID-scoped
  - auto-invalidated when PID exits
  - intentionally not persisted across restarts
- Expanded diagnostics/support exports with identity telemetry snapshots.

## Relaunch Playbooks + Decision Tracing (Phase 3 MVP)

- Added relaunch strategy presets:
  - `conservative`
  - `balanced`
  - `aggressive`
- Added explicit relaunch cooldown pacing control.
- Added structured relaunch decision trace states:
  - `no-op`
  - `cooldown`
  - `launch`
  - `cap`
- Surfaced latest relaunch reason in UI and included relaunch traces in diagnostics/support artifacts.

## Additional updates

- Updated webhook test popup behavior on the requested path to use an error-style dialog.
- Continued stability-first behavior: new features are designed to remain non-disruptive when disabled.

## Bundled asset

- `StayActive.exe` (Windows, one-file PyInstaller build)

