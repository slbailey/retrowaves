# Station Shutdown Terminal Intent Contract

## Purpose

Defines the invariants governing station shutdown while content is playing, ensuring that:

- Only one terminal shutdown announcement may ever be queued
- DJ THINK/DO does not re-enter terminal logic after the shutdown announcement completes
- Shutdown behavior is deterministic and idempotent

This contract prevents a failure mode observed during shutdown where the system attempts to enqueue multiple terminal shutdown announcements after the first has already played, violating lifecycle integrity and raising fatal errors.

**Cross-Contract References:**
- **DJ Intent:** See `DJ_INTENT_CONTRACT.md` for intent structure and validity rules
- **Master System:** See `MASTER_SYSTEM_CONTRACT.md` for THINK/DO event model
- **Station Lifecycle:** See `STATION_LIFECYCLE_CONTRACT.md` for shutdown semantics
- **Station Startup:** See `STATION_STARTUP_STATE_MACHINE_CONTRACT.md` for startup behavior

---

## SD1 — Single Terminal Intent

### SD1.1 — Terminal Intent Uniqueness

**Exactly one terminal DJIntent MAY be created per station lifecycle.**

- A terminal DJIntent is a DJIntent that contains a shutdown announcement as its content
- Once a terminal intent has been queued, no further terminal intents may be created
- The system **MUST** track whether a terminal intent has already been created for the current lifecycle

### SD1.2 — Terminal Intent Creation Restriction

**Once a terminal intent has been queued, no further terminal intents may be created.**

- After the first terminal DJIntent is enqueued, all subsequent attempts to create terminal intents **MUST** be rejected
- The system **MUST** enforce this restriction regardless of whether the terminal intent has completed playback
- This restriction applies for the entire remaining duration of the station lifecycle

### SD1.3 — Terminal Intent Identification

**A terminal DJIntent MUST be identifiable as terminal.**

- Terminal intents **MUST** be marked or identified in a way that distinguishes them from normal DJIntents
- The identification mechanism **MUST** allow the system to detect and prevent duplicate terminal intent creation
- Terminal intent identification **MAY** be based on content type, intent metadata, or explicit terminal flag

---

## SD2 — Terminal Intent Latching

### SD2.1 — Lifecycle-Scoped Latch

**A lifecycle-scoped latch MUST record that terminal intent has already been queued.**

- The latch **MUST** be initialized to `False` at station startup
- The latch **MUST** be set to `True` immediately when a terminal DJIntent is created or enqueued
- The latch **MUST** persist for the entire station lifecycle (until process termination)
- The latch **MUST NOT** be reset or cleared during normal operation or shutdown

### SD2.2 — Latch Enforcement

**Clearing a terminal DJIntent object MUST NOT allow another terminal intent to be created.**

- The lifecycle latch **MUST** remain set even if the terminal DJIntent object is garbage collected or cleared from memory
- The latch **MUST** be independent of the terminal DJIntent object's lifetime
- The latch **MUST** prevent terminal intent creation even if the terminal intent has completed execution

### SD2.3 — Latch Check Requirements

**All code paths that could create a terminal DJIntent MUST check the lifecycle latch first.**

- Before creating any terminal DJIntent, the system **MUST** verify that the latch is `False`
- If the latch is `True`, terminal intent creation **MUST** be rejected immediately
- Latch checks **MUST** occur before any terminal intent object creation or enqueueing

---

## SD3 — DO Execution Rules During DRAINING

### SD3.1 — Single DO Execution

**During DRAINING, DJ DO MAY execute exactly once to enqueue the terminal shutdown announcement.**

- DJ DO **MAY** execute during DRAINING state to enqueue the terminal shutdown announcement
- This execution **MUST** be the only DJ DO execution that enqueues terminal content
- After this single execution, DJ DO **MUST NOT** execute terminal logic again

### SD3.2 — Terminal Logic Re-entry Prohibition

**DJ DO MUST NOT execute terminal logic again after that enqueue.**

- Once the terminal shutdown announcement has been enqueued, DJ DO **MUST NOT** attempt to enqueue additional terminal content
- DJ DO **MUST NOT** create or process additional terminal DJIntents
- DJ DO **MUST** respect the lifecycle latch and terminal intent uniqueness rules

### SD3.3 — DRAINING State Definition

**DRAINING state is the period during which the station is shutting down but content is still playing.**

- DRAINING begins when shutdown is initiated while content is playing
- DRAINING continues until the terminal shutdown announcement completes playback
- During DRAINING, normal THINK/DO cycles **MUST** be suppressed or modified to prevent re-entry

---

## SD4 — Shutdown Announcement Completion

### SD4.1 — Completion Event Handling

**Completion of the shutdown announcement MUST NOT trigger DJ THINK.**

- When the terminal shutdown announcement finishes playing, the `on_segment_finished` event **MUST NOT** trigger DJ THINK execution
- DJ THINK **MUST** be suppressed or disabled after terminal intent enqueueing
- The system **MUST** prevent any THINK execution after terminal intent has been queued

### SD4.2 — DO Suppression After Completion

**Completion of the shutdown announcement MUST NOT trigger DJ DO.**

- When the terminal shutdown announcement finishes playing, the system **MUST NOT** trigger DJ DO execution
- DJ DO **MUST** be suppressed or disabled after terminal intent enqueueing
- The system **MUST** prevent any DO execution after terminal intent has been queued

### SD4.3 — AudioEvent Creation Prohibition

**Completion of the shutdown announcement MUST NOT create or enqueue additional AudioEvents.**

- After terminal shutdown announcement completion, no new AudioEvents **MAY** be created
- No AudioEvents **MAY** be enqueued to the playout queue after terminal announcement completion
- The playout queue **MUST** remain empty or contain only the completed terminal announcement

### SD4.4 — Shutdown Progression

**After terminal announcement completion, the system MUST proceed to final shutdown without further audio operations.**

- The system **MUST** transition to final shutdown state after terminal announcement completes
- No further audio processing or enqueueing **MAY** occur
- The system **MUST** clean up resources and terminate gracefully

---

## SD5 — Prefill Suppression During Terminal Announcement

### SD5.1 — Pre-fill Suppression Requirement

**Pre-fill silence injection MUST NOT occur while the shutdown announcement is playing.**

- Pre-fill operations **MUST** be disabled or suppressed during terminal announcement playback
- No silence injection **MAY** occur while the terminal shutdown announcement is active
- Pre-fill **MUST** respect the terminal intent lifecycle and not interfere with shutdown announcement timing

### SD5.2 — Pre-fill State During DRAINING

**Pre-fill MUST be suppressed throughout the DRAINING state.**

- Pre-fill **MUST** be disabled when DRAINING state begins
- Pre-fill **MUST** remain disabled until station process termination
- Pre-fill suppression **MUST** be independent of whether terminal announcement has been enqueued yet

### SD5.3 — Pre-fill Re-enable Prohibition

**Pre-fill MUST NOT be re-enabled after terminal intent has been queued.**

- Once a terminal intent has been queued, pre-fill **MUST NOT** be re-enabled for any reason
- Pre-fill suppression **MUST** persist even if terminal announcement playback completes
- Pre-fill **MUST** remain suppressed until process termination

---

## SD6 — Assertion Requirements

### SD6.1 — Mandatory Runtime Assertions

**The following assertions MUST be enforced at runtime:**

#### SD6.1.1 — Terminal Intent Uniqueness

**Assertion:** Exactly one terminal DJIntent **MAY** be created per station lifecycle.

- Check lifecycle latch before creating any terminal DJIntent
- Assertion failure indicates duplicate terminal intent creation attempt
- This assertion **MUST** be checked before terminal intent object creation

#### SD6.1.2 — Latch Persistence

**Assertion:** Lifecycle latch **MUST** remain set after terminal intent is queued.

- Verify latch is `True` after terminal intent enqueueing
- Verify latch remains `True` even if terminal intent object is cleared
- Assertion failure indicates latch management error

#### SD6.1.3 — DO Re-entry Prevention

**Assertion:** DJ DO **MUST NOT** execute terminal logic after terminal intent has been enqueued.

- Verify DJ DO does not attempt to create or enqueue terminal content after first terminal intent
- Check lifecycle latch within DJ DO before terminal logic execution
- Assertion failure indicates DO re-entry violation

#### SD6.1.4 — THINK/DO Suppression After Completion

**Assertion:** DJ THINK and DJ DO **MUST NOT** execute after terminal announcement completion.

- Verify THINK/DO are suppressed after terminal announcement finishes
- Check that no THINK/DO execution occurs in response to terminal announcement completion
- Assertion failure indicates improper event handling after shutdown

### SD6.2 — Assertion Failure Handling

**Assertion failures indicate contract violations, not recoverable errors.**

- Assertion failures **MUST** be logged as critical errors
- Assertion failures **MUST** indicate system integrity violation
- Assertion failures **SHOULD** trigger immediate shutdown or safe fallback behavior
- Assertion failures **MUST NOT** be silently ignored or recovered from
- Assertion failures indicate fundamental design violation requiring code fix

### SD6.3 — Assertion Placement

**Assertions MUST be placed at critical operations and state transitions:**

- Before creating terminal DJIntent: verify lifecycle latch is `False`
- After enqueueing terminal DJIntent: verify latch is set to `True`
- In DJ DO before terminal logic: verify latch is `False` (or reject if `True`)
- After terminal announcement completion: verify THINK/DO are suppressed
- During DRAINING state: verify pre-fill is suppressed

---

## SD7 — Non-Goals

**This contract does NOT define:**

- **Startup behavior:** Startup is specified by `STATION_STARTUP_STATE_MACHINE_CONTRACT.md`
- **Normal operation THINK/DO:** Normal THINK/DO behavior is specified by `MASTER_SYSTEM_CONTRACT.md`
- **Playout timing or encoder behavior:** Timing and encoding are specified by `PLAYOUT_ENGINE_CONTRACT.md` and `STATION_TOWER_PCM_BRIDGE_CONTRACT.md`
- **Shutdown initiation triggers:** What causes shutdown to begin is specified by `STATION_LIFECYCLE_CONTRACT.md`
- **Resource cleanup details:** Detailed cleanup procedures are specified by `STATION_LIFECYCLE_CONTRACT.md`
- **Audio decoding behavior:** Decoding is specified by `FFMPEG_DECODER_CONTRACT.md`

**This contract focuses exclusively on:**

- Terminal intent uniqueness and lifecycle management
- Preventing duplicate terminal shutdown announcements
- Ensuring deterministic shutdown behavior
- Suppressing THINK/DO re-entry after terminal intent completion
- Pre-fill suppression during shutdown

---

## SD8 — Related Contracts

This contract references and depends on:

- **`DJ_INTENT_CONTRACT.md`** — Defines DJIntent structure, intent_id semantics, and intent validity rules
- **`MASTER_SYSTEM_CONTRACT.md`** — Defines THINK/DO event model and normal operation lifecycle
- **`STATION_LIFECYCLE_CONTRACT.md`** — Defines shutdown semantics and DRAINING state behavior
- **`STATION_STARTUP_STATE_MACHINE_CONTRACT.md`** — Defines startup behavior (complementary to shutdown)

**This contract complements these contracts by:**

- Adding explicit terminal intent management to StationLifecycle Contract's shutdown semantics
- Ensuring DJIntent Contract rules are enforced during shutdown transitions
- Guaranteeing Master System Contract's THINK/DO model is properly terminated
- Preventing shutdown-time violations that could affect system integrity

---

## Implementation Notes

- Lifecycle latch **MUST** be implemented as a boolean flag scoped to the Station instance
- Latch **MUST** be initialized to `False` in Station constructor
- Latch **MUST** be set to `True` immediately when terminal DJIntent is created or enqueued
- Latch checks **MUST** be performed before any terminal intent creation logic
- THINK/DO suppression **MUST** be implemented via explicit checks or state flags
- Pre-fill suppression **MUST** check lifecycle state or terminal intent latch
- Assertions **MUST** be implemented as runtime checks, not just documentation
- Terminal intent identification **MAY** use explicit metadata, content type checks, or intent flags
- DRAINING state **MUST** be explicitly tracked and communicated to THINK/DO and pre-fill systems

---

## Rationale

This contract prevents a failure mode observed during shutdown where the system attempts to enqueue multiple terminal shutdown announcements after the first has already played, violating lifecycle integrity and raising fatal errors.

The key insight is that shutdown is a terminal state: once a terminal shutdown announcement has been queued, the system must not attempt to create or enqueue additional terminal content. The lifecycle latch ensures this by providing a persistent, lifecycle-scoped record that terminal intent has already been used.

By enforcing that THINK/DO do not re-enter terminal logic after the shutdown announcement completes, and by suppressing pre-fill during terminal announcement playback, this contract ensures shutdown behavior is deterministic and idempotent, preventing race conditions and duplicate enqueueing attempts.


