# Station Startup State Machine Contract

## Purpose

Defines the explicit state machine that governs how Station transitions from process start to normal DJ-driven operation. Startup is a distinct operational mode with stricter rules than normal operation, designed to prevent queue contamination, intent violations, and ensure proper initialization before DJ THINK/DO scheduling begins.

This contract ensures that:
- No AudioEvents are enqueued outside the DJ THINK/DO lifecycle
- No cross-intent queue contamination can occur at startup
- Startup announcements do not violate queue or intent invariants

The startup state machine transitions into normal THINK/DO scheduling only after the startup announcement completes and the first DJ DO phase executes.

**Cross-Contract References:**
- **DJ Intent:** See `DJ_INTENT_CONTRACT.md` for intent structure and validity rules
- **Master System:** See `MASTER_SYSTEM_CONTRACT.md` for THINK/DO event model
- **Station Lifecycle:** See `STATION_LIFECYCLE_CONTRACT.md` for startup/shutdown semantics
- **Station Tower Bridge:** See `STATION_TOWER_PCM_BRIDGE_CONTRACT.md` for audio pipeline contracts

---

## SS1 — Defined Startup States

### SS1.1 — BOOTSTRAP

**Entry Conditions:**
- Process has started and Station constructor has completed
- Components are created but not yet initialized

**Invariants:**
- Playout queue **MUST** be empty
- No AudioEvents **MAY** be enqueued
- DJ THINK **MUST NOT** have executed
- DJ DO **MUST NOT** have executed
- No segment **MAY** be active or playing

**Allowed Actions:**
- Component initialization (MediaLibrary, AssetDiscoveryManager, DJStateStore)
- Component reference assignment
- State loading and restoration
- Preparation for startup announcement selection

**Forbidden Actions:**
- Enqueueing AudioEvents to playout queue
- Executing DJ THINK or DJ DO
- Starting audio playback
- Modifying playout queue state

---

### SS1.2 — STARTUP_ANNOUNCEMENT_PLAYING

**Entry Conditions:**
- BOOTSTRAP state has completed
- Startup announcement has been selected (if available)
- Startup announcement has been enqueued directly (not via DJ DO)
- Startup announcement playback has begun

**Invariants:**
- Startup announcement **MUST NOT** have an `intent_id` (no DJIntent association)
- Playout queue **MUST** contain only the startup announcement AudioEvent
- Startup announcement **MUST** be the only active segment
- DJ THINK **MAY** run during this state (to prepare first music segment)
- DJ DO **MUST NOT** run during this state
- No other AudioEvents **MAY** be enqueued

**Allowed Actions:**
- Playing startup announcement segment
- Executing DJ THINK (to select first song and prepare first DJIntent)
- DJ THINK **MAY** observe lifecycle state (is_startup=True)

**Forbidden Actions:**
- Enqueueing AudioEvents via DJ DO
- Executing DJ DO phase
- Enqueueing AudioEvents outside DJ DO
- Starting pre-fill operations while segment is active
- Assigning `intent_id` to startup announcement

---

### SS1.3 — STARTUP_THINK_COMPLETE

**Entry Conditions:**
- STARTUP_ANNOUNCEMENT_PLAYING state is active
- Startup announcement segment is still playing
- DJ THINK has completed and prepared the first DJIntent
- First DJIntent is ready for execution

**Invariants:**
- First DJIntent **MUST** be complete and valid (per DJIntent Contract)
- DJIntent **MUST** contain a valid `intent_id`
- Playout queue **MUST** contain only the startup announcement
- DJ DO **MUST NOT** have executed yet
- No AudioEvents from DJIntent **MAY** be enqueued yet

**Allowed Actions:**
- Holding first DJIntent ready for DO phase
- Continuing startup announcement playback
- Waiting for startup announcement to finish

**Forbidden Actions:**
- Executing DJ DO phase
- Enqueueing AudioEvents from DJIntent
- Modifying prepared DJIntent
- Starting pre-fill operations

---

### SS1.4 — STARTUP_DO_ENQUEUE

**Entry Conditions:**
- STARTUP_THINK_COMPLETE state is active
- Startup announcement segment has finished playing
- `on_segment_finished` has been emitted for startup announcement
- System is ready to execute first DJ DO phase

**Invariants:**
- Playout queue **MUST** be empty (startup announcement has finished)
- First DJIntent **MUST** be ready for execution
- All AudioEvents enqueued during this state **MUST** share the same `intent_id`
- This **MUST** be the first and only DJ DO execution during startup
- Pre-fill **MUST NOT** run during this state if any segment becomes active

**Allowed Actions:**
- Executing DJ DO phase for first time
- Enqueueing AudioEvents from first DJIntent
- All enqueued AudioEvents **MUST** have the same `intent_id` (from first DJIntent)

**Forbidden Actions:**
- Enqueueing AudioEvents without `intent_id`
- Enqueueing AudioEvents with different `intent_id` values
- Starting pre-fill operations while segments are active
- Skipping DJ DO execution

---

### SS1.5 — NORMAL_OPERATION

**Entry Conditions:**
- STARTUP_DO_ENQUEUE state has completed
- First DJ DO phase has executed
- First music segment AudioEvents have been enqueued
- First music segment begins playback

**Invariants:**
- System **MUST** follow normal THINK/DO lifecycle (per Master System Contract)
- AudioEvents **MUST** be enqueued only via DJ DO phase
- Each DJIntent **MUST** be consumed exactly once (per DJIntent Contract)
- Normal pre-fill operations **MAY** run according to pre-fill contract rules

**Allowed Actions:**
- Normal THINK/DO cycle execution
- Pre-fill operations (per pre-fill contract)
- All normal Station operations

**Forbidden Actions:**
- Startup-specific behaviors
- Enqueueing AudioEvents outside DJ DO
- Skipping intent_id assignment for AudioEvents enqueued via DJ DO

---

## SS2 — State Transition Rules

### SS2.1 — Valid Transitions

The startup state machine **MUST** follow these exact transition sequences:

**BOOTSTRAP → STARTUP_ANNOUNCEMENT_PLAYING**
- Transition occurs when startup announcement is injected as the active segment and playback begins
- If no startup announcement is available, transition to STARTUP_DO_ENQUEUE may occur instead (skipping announcement states)

**STARTUP_ANNOUNCEMENT_PLAYING → STARTUP_THINK_COMPLETE**
- Transition occurs when DJ THINK completes during announcement playback
- DJ THINK prepares first DJIntent for first music segment

**STARTUP_THINK_COMPLETE → STARTUP_DO_ENQUEUE**
- Transition occurs when startup announcement finishes playing
- `on_segment_finished` event triggers transition to DO phase

**STARTUP_DO_ENQUEUE → NORMAL_OPERATION**
- Transition occurs when first DJ DO phase completes
- First music segment AudioEvents are enqueued
- First music segment begins playback

### SS2.2 — Transition Constraints

**No transitions MAY be skipped**, except as explicitly allowed:

- If no startup announcement is available, STARTUP_ANNOUNCEMENT_PLAYING and STARTUP_THINK_COMPLETE states **MAY** be skipped
- BOOTSTRAP **MUST** always be the initial state
- NORMAL_OPERATION **MUST** always be the final startup state
- All other states **MUST** be visited in order if applicable

**State machine MUST be deterministic:**
- Each state has exactly one valid next state (or zero if terminal)
- No branching or conditional transitions are permitted
- State transitions **MUST** be triggered by explicit events (segment start, segment finish, THINK complete, DO complete)

---

## SS3 — Queue Invariants

### SS3.1 — Queue Empty Requirement

**The playout queue MUST be empty in all startup states prior to STARTUP_DO_ENQUEUE.**

- In BOOTSTRAP: queue **MUST** be empty
- In STARTUP_ANNOUNCEMENT_PLAYING: queue **MAY** contain only the startup announcement
- In STARTUP_THINK_COMPLETE: queue **MAY** contain only the startup announcement
- Before first DJ DO execution: queue **MUST** be empty (startup announcement finished)

### SS3.2 — AudioEvent Enqueue Restrictions

**No AudioEvent MAY be enqueued before STARTUP_DO_ENQUEUE state**, except:
- Startup announcement **MAY** be injected as the active segment (not via DJ DO queue) during transition to STARTUP_ANNOUNCEMENT_PLAYING
- All other AudioEvents **MUST** be enqueued only during STARTUP_DO_ENQUEUE or NORMAL_OPERATION states

### SS3.3 — Startup Announcement Intent Rules

**Startup announcements MAY be enqueued, but MUST NOT be enqueued via DJ DO, and MUST NOT carry an intent_id.**

- Startup announcement is not part of any DJIntent
- Startup announcement is not associated with any intent_id
- Startup announcement **MAY** be enqueued directly (not via DJ DO phase)
- Startup announcement **MUST NOT** have an `intent_id` attribute (must be `None`)
- Startup announcement **MUST** be distinguishable from DJ-driven AudioEvents (lack of intent_id)

### SS3.4 — Startup DO Intent Unification

**All AudioEvents enqueued in STARTUP_DO_ENQUEUE MUST share the same intent_id.**

- First DJ DO phase enqueues AudioEvents from a single DJIntent
- All AudioEvents enqueued during STARTUP_DO_ENQUEUE **MUST** have `intent_id` matching the first DJIntent
- No AudioEvents with different `intent_id` values **MAY** be enqueued during STARTUP_DO_ENQUEUE
- This ensures the first music segment is atomic and intent-integrity compliant

---

## SS4 — DJ THINK / DO Interaction

### SS4.1 — THINK During Startup

**DJ THINK MAY run during STARTUP_ANNOUNCEMENT_PLAYING.**

- THINK prepares the first DJIntent for the first music segment
- THINK executes while startup announcement is playing (non-blocking)
- THINK **MAY** observe lifecycle state (`is_startup=True`) to select startup-appropriate content
- THINK completes and stores first DJIntent before startup announcement finishes

### SS4.2 — THINK Enqueue Prohibition

**DJ THINK MUST NOT enqueue AudioEvents during startup.**

- THINK **MUST** only prepare DJIntent, not execute it
- THINK **MUST NOT** call playout engine enqueue methods during startup
- THINK **MUST NOT** modify playout queue during startup
- THINK behavior during startup is identical to normal operation: prepare intent only

### SS4.3 — DO Execution Restriction

**DJ DO MUST NOT run until STARTUP_DO_ENQUEUE state.**

- DO phase **MUST NOT** execute during BOOTSTRAP
- DO phase **MUST NOT** execute during STARTUP_ANNOUNCEMENT_PLAYING
- DO phase **MUST NOT** execute during STARTUP_THINK_COMPLETE
- DO phase **MAY** execute only after transitioning to STARTUP_DO_ENQUEUE

### SS4.4 — First DO Transition

**The first DJ DO execution transitions the system into normal operation.**

- First DJ DO execution occurs in STARTUP_DO_ENQUEUE state
- After first DJ DO completes, system **MUST** transition to NORMAL_OPERATION
- First DO execution enqueues first music segment AudioEvents
- After transition, system follows normal THINK/DO lifecycle (per Master System Contract)

---

## SS5 — Pre-Fill Interaction

### SS5.1 — Pre-Fill During Active Segments

**Pre-fill MUST NOT run during any startup state where a segment is active.**

- Pre-fill **MUST NOT** run during STARTUP_ANNOUNCEMENT_PLAYING (announcement is active)
- Pre-fill **MUST NOT** run during STARTUP_DO_ENQUEUE if segments become active
- Pre-fill **MUST NOT** inject silence during startup announcement playback
- Pre-fill may interfere with startup announcement timing and **MUST** be suppressed

### SS5.2 — Pre-Fill Before Announcement

**Pre-fill MAY run before startup announcement begins.**

- Pre-fill **MAY** run during BOOTSTRAP state (no segment active)
- Pre-fill **MAY** run between BOOTSTRAP and STARTUP_ANNOUNCEMENT_PLAYING
- Pre-fill **MUST** stop before startup announcement playback begins
- Pre-fill **MUST NOT** conflict with startup announcement enqueueing

### SS5.3 — Pre-Fill During Normal Operation

**Pre-fill operations in NORMAL_OPERATION state follow normal pre-fill contract rules.**

- Pre-fill restrictions are startup-specific
- Once in NORMAL_OPERATION, pre-fill behaves according to its own contract
- Startup pre-fill restrictions do not apply after transition to NORMAL_OPERATION

---

## SS6 — Assertion Requirements

### SS6.1 — Mandatory Runtime Assertions

**The following assertions MUST be enforced at runtime:**

#### SS6.1.1 — Queue Empty Before First DO

**Assertion:** Playout queue **MUST** be empty immediately before first DJ DO enqueues AudioEvents.

- Check queue size before executing first DJ DO phase
- Assertion failure indicates queue contamination or premature enqueueing
- This assertion **MUST** be checked at entry to STARTUP_DO_ENQUEUE state

#### SS6.1.2 — Startup Announcement Intent Check

**Assertion:** Startup announcement AudioEvent **MUST NOT** have an `intent_id` attribute or **MUST** have `intent_id=None`.

- Verify startup announcement is not associated with any DJIntent
- Assertion failure indicates intent contamination or incorrect injection
- This assertion **MUST** be checked when startup announcement is injected as the active segment

#### SS6.1.3 — Startup DO Intent Unification

**Assertion:** All AudioEvents enqueued during STARTUP_DO_ENQUEUE **MUST** share the same `intent_id` value.

- Verify all AudioEvents from first DJ DO have matching `intent_id`
- Assertion failure indicates cross-intent queue contamination
- This assertion **MUST** be checked after first DJ DO execution completes
- All AudioEvents enqueued in single DO execution **MUST** share one `intent_id`

### SS6.2 — Assertion Failure Handling

**Assertion failures indicate contract violations, not recoverable errors.**

- Assertion failures **MUST** be logged as critical errors
- Assertion failures **MUST** indicate system integrity violation
- Assertion failures **SHOULD** trigger shutdown or safe fallback behavior
- Assertion failures **MUST NOT** be silently ignored or recovered from
- Assertion failures indicate fundamental design violation requiring code fix

### SS6.3 — Assertion Placement

**Assertions MUST be placed at state transition boundaries and critical operations:**

- Before transitioning to STARTUP_DO_ENQUEUE: verify queue empty
- When enqueueing startup announcement: verify no intent_id
- After first DJ DO execution: verify all AudioEvents share same intent_id
- At entry to each state: verify state invariants hold
- At exit from each state: verify transition conditions are met

---

## SS7 — Non-Goals

**This contract does NOT define:**

- **Audio decoding behavior:** Decoding is specified by FFmpegDecoder Contract
- **PID timing:** Timing and pacing are specified by PlayoutEngine Contract and Station Tower PCM Bridge Contract
- **Asset selection logic:** Song and asset selection are specified by DJEngine Contract and RotationManager Contract
- **UI or observability concerns:** UI contracts and event emission are specified by Master System Contract
- **Component initialization order:** Detailed initialization is specified by StationLifecycle Contract
- **Pre-fill implementation details:** Pre-fill behavior is specified by its own contract
- **Shutdown behavior:** Shutdown is specified by StationLifecycle Contract

**This contract focuses exclusively on:**
- Startup state machine definition and transitions
- Queue and intent integrity during startup
- DJ THINK/DO interaction during startup phases
- Preventing startup-time violations of queue and intent invariants

---

## SS8 — Related Contracts

This contract references and depends on:

- **`DJ_INTENT_CONTRACT.md`** — Defines DJIntent structure, intent_id semantics, and intent validity rules
- **`MASTER_SYSTEM_CONTRACT.md`** — Defines THINK/DO event model and normal operation lifecycle
- **`STATION_LIFECYCLE_CONTRACT.md`** — Defines startup/shutdown semantics and component initialization order
- **`STATION_TOWER_PCM_BRIDGE_CONTRACT.md`** — Defines audio pipeline and timing contracts

**This contract complements these contracts by:**
- Adding explicit startup state machine to StationLifecycle Contract's startup semantics
- Ensuring DJIntent Contract rules are enforced during startup transitions
- Guaranteeing Master System Contract's THINK/DO model is properly initialized
- Preventing violations that could affect audio pipeline contracts

---

## Implementation Notes

- Startup state machine **MUST** be tracked explicitly in Station implementation
- State transitions **MUST** be logged for observability and debugging
- Assertions **MUST** be implemented as runtime checks, not just documentation
- State machine **SHOULD** be testable in isolation from audio pipeline
- State tracking **MAY** be implemented as enum or explicit state variable
- State transitions **SHOULD** be triggered by explicit events (segment lifecycle, THINK complete, DO complete)

