# StationLifecycle Contract

## Purpose

Defines what "startup" and "shutdown" mean for Station, ensuring proper initialization order and clean teardown.

---

## SL1 — Startup

### SL1.1 — Component Loading Order

**MediaLibrary**, **AssetDiscoveryManager**, and **DJStateStore** **MUST** be loaded before playout begins.

- MediaLibrary must be initialized and ready
- AssetDiscoveryManager must complete initial scan
- DJStateStore must load persisted state (rotation history, cooldowns, etc.)

### SL1.2 — First Song Selection

System **MUST** select exactly one first song (via **RotationManager**) before audio begins.

- First song selection occurs during startup, not during first THINK phase
- Selection must follow all rotation rules (cooldowns, weights, etc.)
- First song must be a valid, playable MP3 file

### SL1.3 — THINK Event Timing

No **THINK** event **MAY** occur before the first segment begins.

- THINK events are triggered by `on_segment_started()` callbacks
- First segment starts only after startup is complete
- No DJ decisions are made during startup (except first song selection)

### SL1.4 — Non-Blocking Startup

Startup **MUST** not block playout once initiated.

- Initialization may occur in background threads
- Playout may begin as soon as first song is selected
- Asset discovery and state loading must not delay audio start

---

## SL2 — Shutdown

### SL2.1 — State Persistence

All DJ/rotation state **MUST** be saved.

- Rotation history must be persisted
- Cooldown timestamps must be saved
- Legal ID timestamps must be preserved
- Tickler queue state must be saved (if applicable)

### SL2.2 — Event Prohibition

No **THINK** or **DO** events **MAY** fire after shutdown begins.

- Shutdown signal must prevent new THINK/DO cycles
- Current segment may complete, but no new segments may start
- Callbacks must be disabled or ignored during shutdown

### SL2.3 — Clean Audio Exit

All audio components (decoders, sinks) **MUST** exit cleanly.

- Decoders must finish current segment and close
- Output sinks must flush buffers and close connections
- No audio artifacts or incomplete frames may remain
- All threads must join within timeout

---

## Implementation Notes

- Startup sequence: Load state → Discover assets → Select first song → Start playout
- Shutdown sequence: Stop accepting new segments → Complete current segment → Save state → Close audio components
- State persistence must be atomic (write to temp file, then rename)





