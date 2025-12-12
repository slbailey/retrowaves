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

### SL1.3 — Startup Announcement

Station **MAY** play exactly one startup announcement before the first music segment.

- Startup announcement is selected during initial THINK phase
- Announcement plays before first music segment
- If a startup announcement exists, the first music segment **MUST NOT** begin until the startup announcement finishes
- First song selection **MAY** occur during the same initial THINK phase that selects the startup announcement
- Playback ordering is strictly enforced: startup announcement (if present) → first music segment
- If `station_starting_up/` directory is empty or no announcement is selected, startup proceeds silently
- Startup announcement is a standard AudioEvent (per AudioEvent Contract)
- Selection occurs during THINK only (per DJEngine Contract)

### SL1.4 — THINK Event Timing

No **THINK** event **MAY** occur before the first segment begins, except for initial THINK that may select startup announcement.

- THINK events are triggered by `on_segment_started()` callbacks
- First segment (startup announcement or first song) starts only after startup is complete
- Initial THINK may select startup announcement and first song
- If startup announcement exists, first song THINK occurs after startup announcement starts (triggered by `on_segment_started()` for the startup announcement)

### SL1.5 — Non-Blocking Startup

Startup **MUST** not block playout once initiated.

- Initialization may occur in background threads
- Playout may begin as soon as first segment (startup announcement or first song) is selected
- Asset discovery and state loading must not delay audio start

---

## SL2 — Shutdown

Shutdown **MUST** follow a two-phase protocol to ensure graceful termination with proper state persistence and clean audio exit.

### SL2.1 — Shutdown Triggers

Shutdown **MAY** be triggered by:

- **SIGTERM** signal
- **SIGINT** (Ctrl+C) signal
- Explicit **stop()** method call

All shutdown triggers **MUST** be treated identically and initiate the same two-phase process.

### SL2.2 — PHASE 1: Soft Shutdown (Draining)

When shutdown is triggered, Station **MUST** enter **DRAINING** state.

#### SL2.2.1 — DRAINING State Behavior

- Station **MUST** transition to DRAINING state immediately upon shutdown trigger
- No new THINK/DO cycles **MAY** begin once DRAINING state is active, **EXCEPT** exactly one terminal THINK/DO cycle is permitted
- The terminal THINK/DO cycle exists solely to prepare and execute a terminal DJIntent
- After the terminal THINK/DO cycle completes, no further THINK or DO events **MAY** fire
- Current segment **MUST** be allowed to finish completely
- DJ THINK **MAY** run one final time to prepare a terminal intent (offline announcement)
- State **MUST NOT** yet be persisted during DRAINING phase

#### SL2.2.2 — Terminal Intent Preparation

- If DJ THINK runs during DRAINING state, it **MAY** produce a terminal DJIntent
- Terminal intent **MUST** be marked as TERMINAL (per DJIntent Contract)
- Terminal intent **MAY** include one shutdown announcement AudioEvent
- If `station_shutting_down/` directory is empty or no announcement is selected, terminal intent may contain no AudioEvents
- Terminal intent **MUST** be executed exactly once during DO phase
- After terminal DO completes, no further THINK or DO events **MAY** fire

#### SL2.2.3 — State Transitions

Allowed state transitions during shutdown:

- **RUNNING** → **DRAINING** (upon shutdown trigger)
- **DRAINING** → **DRAINING** (idempotent — multiple shutdown requests are safe)
- **DRAINING** → **SHUTTING_DOWN** (after terminal segment finishes or timeout)

#### SL2.2.4 — Idempotency

Multiple shutdown requests **MUST** be safe and idempotent.

- Subsequent shutdown triggers while in DRAINING state **MUST** be ignored
- System **MUST** remain in DRAINING state until transition to SHUTTING_DOWN
- No duplicate shutdown processing **MAY** occur

#### SL2.2.5 — Max-Wait Timeout

System **MUST** support a configurable max-wait timeout for long segments.

- Timeout **MUST** be configurable (implementation-defined default)
- If current segment exceeds timeout duration:
  - System **MUST** transition to SHUTTING_DOWN (PHASE 2)
  - Current segment **MAY** be terminated (force hard shutdown)
  - Timeout behavior **MUST** be documented and logged

#### SL2.2.6 — Behavior When No Shutdown Announcement Exists

If no shutdown announcement is available or selected:

- Terminal intent **MAY** contain no AudioEvents
- System **MUST** transition to SHUTTING_DOWN (PHASE 2) immediately after current segment finishes
- No terminal segment plays
- Shutdown proceeds normally to PHASE 2

### SL2.3 — PHASE 2: Hard Shutdown

After terminal segment finishes (or timeout), Station **MUST** enter **SHUTTING_DOWN** state and perform final cleanup.

#### SL2.3.1 — State Persistence

All DJ/rotation state **MUST** be saved atomically.

- Rotation history must be persisted
- Cooldown timestamps must be saved
- Legal ID timestamps must be preserved
- Tickler queue state must be saved (if applicable)
- State persistence **MUST** be atomic (write to temp file, then rename)
- State persistence **MUST** occur during SHUTTING_DOWN phase only

#### SL2.3.2 — Event Prohibition

No **THINK** or **DO** events **MAY** fire after SHUTTING_DOWN phase begins.

- Shutdown signal must prevent new THINK/DO cycles
- Terminal segment must have completed
- Callbacks must be disabled or ignored during SHUTTING_DOWN

#### SL2.3.3 — Clean Audio Exit

All audio components (decoders, sinks) **MUST** exit cleanly.

- Decoders must finish current segment and close
- Output sinks must flush buffers and close connections
- No audio artifacts or incomplete frames may remain
- All threads must join within timeout

#### SL2.3.4 — Process Exit

After all cleanup completes, process **MAY** exit.

- All resources must be released
- All threads must be joined
- Process exit code must indicate success or failure

---

## LOG — Logging and Observability

### LOG1 — Log File Location
Station lifecycle components **MUST** write all log output to `/var/log/retrowaves/station.log`.

- Log file path **MUST** be deterministic and fixed
- Log file **MUST** be readable by the retrowaves user/group
- Lifecycle components **MUST NOT** require elevated privileges at runtime to write logs

### LOG2 — Non-Blocking Logging
Logging operations **MUST** be non-blocking and **MUST NOT** interfere with startup or shutdown sequences.

- Logging **MUST NOT** block component loading during startup
- Logging **MUST NOT** block state persistence during shutdown
- Logging **MUST NOT** delay state transitions (RUNNING → DRAINING → SHUTTING_DOWN)
- Logging **MUST NOT** delay audio component cleanup
- Logging failures **MUST** degrade silently (stderr fallback allowed)

### LOG3 — Rotation Tolerance
Station lifecycle components **MUST** tolerate external log rotation without crashing or stalling.

- Lifecycle components **MUST** assume logs may be rotated externally (e.g., via logrotate)
- Lifecycle components **MUST** handle log file truncation or rename gracefully
- Lifecycle components **MUST NOT** implement rotation logic in application code
- Lifecycle components **MUST** reopen log files if they are rotated (implementation-defined mechanism)
- Rotation **MUST NOT** cause startup or shutdown interruption

### LOG4 — Failure Behavior
If log file write operations fail, Station lifecycle **MUST** continue startup and shutdown sequences normally.

- Logging failures **MUST NOT** crash the process
- Logging failures **MUST NOT** interrupt component loading
- Logging failures **MUST NOT** interrupt state persistence
- Lifecycle components **MAY** fall back to stderr for critical errors, but **MUST NOT** block on stderr writes

---

## Required Tests

This contract requires the following logging compliance tests:

- LOG1 — Log File Location
- LOG2 — Non-Blocking Logging
- LOG3 — Rotation Tolerance
- LOG4 — Failure Behavior

See `tests/contracts/LOGGING_TEST_REQUIREMENTS.md` for test specifications.

---

## Implementation Notes

- Startup sequence: Load state → Discover assets → Select first song → Start playout
- Shutdown sequence (PHASE 1): Enter DRAINING → Complete current segment → Allow terminal THINK/DO → Transition to SHUTTING_DOWN
- Shutdown sequence (PHASE 2): Persist state atomically → Close audio components → Exit process
- State persistence must be atomic (write to temp file, then rename)
- State persistence occurs only during PHASE 2 (SHUTTING_DOWN), not during PHASE 1 (DRAINING)






