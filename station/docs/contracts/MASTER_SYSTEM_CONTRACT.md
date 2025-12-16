# Master System Contract — THINK/DO Event Model

## Purpose

This is the umbrella contract that defines the fundamental event-driven architecture for Station. All other contracts reference and depend on this model.

The THINK/DO model ensures that decision-making (THINK) is completely separated from execution (DO), preventing blocking operations and ensuring predictable, real-time audio playout.

---

## E0 — THINK/DO Event Model

### E0.1 — Lifecycle Events

Every segment **MUST** trigger exactly two lifecycle events:

1. **`on_segment_started(segment)`** → **THINK** phase
2. **`on_segment_finished(segment)`** → **DO** phase

### E0.2 — THINK Before DO

**THINK** **MUST** always complete before **DO** begins.

- THINK phase prepares all decisions and creates DJIntent
- DO phase executes the prepared intent without making decisions

### E0.3 — Non-Blocking DO

**DO** operations **MUST** be non-blocking and **MUST** finish before the next segment starts.

- DO operations may queue work but must not block the playout thread
- All DO work must complete within the current segment's duration

### E0.4 — DO Execution Only

**DO** events **MUST** never perform selection logic — only execute previously prepared intent.

- DO receives a complete DJIntent from THINK
- DO executes the intent: enqueue segments, apply IDs, etc.
- DO does NOT select songs, check cooldowns, or make routing decisions

### E0.5 — THINK Fallback

If **THINK** fails, the system **MUST** fall back to safe, substitution-based intent (all decisions still resolved before DO).

- THINK failures must not prevent DO from executing
- Fallback intent must be complete and valid
- All decisions must be resolved before DO begins, even in failure cases

### E0.6 — Queue Modification

No component **MAY** modify the playout queue except **DO**.

- THINK prepares intent but does not modify the queue
- PlayoutEngine reads from the queue but does not modify it
- Only DO operations may enqueue, dequeue, or reorder segments

### E0.7 — Heartbeat Observability

The system **MUST** emit control-channel heartbeat events for observability. These events are purely observational and **MUST NOT** influence THINK/DO decisions or playout behavior.

**Heartbeat events MUST:**
- Be observable but not influence decisions
- Respect THINK/DO boundaries (events emitted from appropriate lifecycle phases)
- Not modify queue or state
- Be emitted from appropriate components (PlayoutEngine, DJEngine, OutputSink)
- Use Clock A (wall clock) for all timing measurements
- Not rely on Tower timing or state

**Heartbeat events include:**
- Lifecycle events (`station_startup`, `station_shutdown`) — emitted by Station
- Content events (`segment_playing`, `song_playing`) — emitted by PlayoutEngine
- THINK lifecycle events (`dj_think_started`, `dj_think_completed`) — emitted by DJEngine
- Buffer health events (`station_underflow`, `station_overflow`) — emitted by OutputSink
- Clock drift events (`decode_clock_skew`) — emitted by PlayoutEngine (if drift compensation enabled)

**DEPRECATED:** `now_playing` events **MUST NOT** be emitted. This event pattern (start + clear semantics) is completely deprecated. Use stateful querying via Station State Contract and edge-triggered events (`song_playing`, `segment_playing`, `station_startup`, `station_shutdown`) instead.

**Event emission rules:**
- Events **MUST** be emitted at correct lifecycle boundaries
- Events **MUST NOT** block THINK or DO operations
- Events **MUST NOT** modify queue, rotation history, or any system state
- Events **MUST** be purely observational (no control logic)
- Events **MUST** include required metadata (timestamps, segment_id, etc.)
- Events **MUST** be edge-triggered transitions only (fire ONCE per transition)
- Events **MUST NOT** fire "end" or "clear" events

**THINK/DO separation:**
- THINK events (`dj_think_started`, `dj_think_completed`) are emitted during THINK phase
- Content events (`segment_playing`, `song_playing`) are emitted when segments start playing
- Events **MUST NOT** cross THINK/DO boundaries (THINK events don't influence DO, DO events don't influence THINK)

### E0.8 — Events vs State: Non-Overlapping Responsibilities

**Events are EDGE-TRIGGERED transitions only. State is LEVEL-TRIGGERED and queryable.**

Events and state have completely separate, non-overlapping responsibilities:

- **Events** represent edge-triggered transitions that fire ONCE per state change
- **State** represents level-triggered, queryable current truth (see Station State Contract)
- **No overlap**: Events do NOT represent state; state is NOT represented by events
- **No inference**: Absence of events NEVER implies absence of state
- **Explicit querying**: Current state MUST be queried via Station State Contract; it cannot be inferred from events
- **One-way events**: Events are Station → Tower (one-way, observational)
- **Tower statelessness**: Tower does NOT infer state from events; Tower remains stateless and non-influential

**Event Semantics (Edge-Triggered):**
- Events fire exactly ONCE when a state transition occurs (e.g., `song_playing` fires when song segment starts)
- Events **MUST NOT** fire "end", "clear", or empty-metadata events
- Events represent transitions only, not current state
- Events are lost if Tower is disconnected; state queries provide authoritative truth
- Events are idempotent-safe on restart; state queries provide current truth after restart
- Events **MUST NOT** be used to determine what is currently playing

**State Semantics (Level-Triggered):**
- State is always queryable via Station State Contract at any moment
- State reflects current operational truth at the moment of query
- State updates synchronously with segment lifecycle events
- State is consistent across all query mechanisms
- State queries are authoritative; events are observational transitions only

**Content Plane Invariant:**
**There is no such thing as "nothing is playing" in the content plane. Absence is represented ONLY via lifecycle or error states.**

- When Station is operational (RUNNING state), there is ALWAYS content playing or about to play
- Fallback content is a STATE, not an absence
- Empty or cleared state does NOT represent "nothing playing" — it represents a lifecycle transition or error condition
- Consumers **MUST NOT** infer absence of content from state queries; absence is a lifecycle state (startup, shutdown, error)

### E0.9 — System-Wide Event Definitions

**All system-wide events are edge-triggered transitions only. There are NO "clear", "end", or empty-metadata events.**

The following events represent the complete set of edge-triggered transitions in the system:

#### E0.9.1 — `station_startup`

**When it fires:**
- Fires exactly ONCE when `Station.start()` completes and playout begins
- Fires synchronously before the first segment (startup announcement or first song) starts
- Fires before any content events (`song_playing`, `segment_playing`)

**Metadata requirements:**
- Metadata **MUST** be empty object `{}`
- No audio metadata is required or permitted

**Idempotency guarantees:**
- Event is idempotent-safe: may be re-emitted on Station restart
- Multiple startups result in multiple events (each restart is a distinct transition)
- Event represents the transition from non-operational to operational state

#### E0.9.2 — `song_playing`

**When it fires:**
- Fires exactly ONCE when a song segment starts playing
- Fires synchronously when `on_segment_started` is emitted with `segment_type="song"`
- Fires before audio playback begins for the song segment

**Metadata requirements:**
- Metadata **MUST** include full AudioEvent metadata when audio is active
- Required fields: `segment_type: "song"`, `started_at` (wall-clock timestamp)
- Optional fields (populated when available): `title`, `artist`, `album`, `year`, `duration_sec`, `file_path`
- Metadata **MUST NOT** be empty; if metadata is unavailable, fallback metadata **MUST** be provided (e.g., empty strings for optional fields)

**Idempotency guarantees:**
- Event is idempotent-safe: may be re-emitted on Station restart
- Each song segment start is a distinct transition; same song playing twice results in two events
- Event represents the transition to song content state

#### E0.9.3 — `segment_playing`

**DEPRECATED:** The `dj_talking` event is COMPLETELY DEPRECATED and MUST NOT be emitted. Use `segment_playing` with appropriate metadata instead.

**When it fires:**
- Fires exactly ONCE per non-song segment start
- Fires synchronously when `on_segment_started` is emitted with `segment_type` not equal to `"song"`
- Fires before audio playback begins for the segment
- Represents transition to non-song content state (station IDs, DJ talk, promos, radio dramas, album segments, etc.)

**Metadata requirements:**
- **MUST** include required metadata: `segment_class`, `segment_role`, `production_type` (see EVENT_INVENTORY.md for complete metadata schema)
- **MUST** include optional metadata when available: `file_path`, `duration_sec`, `series_id`, `episode_id`, `part_number`, `total_parts`, `legal`

**Idempotency guarantees:**
- Event is idempotent-safe: may be re-emitted on Station restart
- Each segment start is a distinct transition
- Event represents the transition to non-song content state

#### E0.9.4 — `station_shutdown`

**When it fires:**
- Fires exactly ONCE when terminal playout completes (or timeout occurs)
- Fires synchronously after the last segment finishes (or timeout)
- Fires before Station enters SHUTTING_DOWN state and performs final cleanup
- Fires before process exit

**Metadata requirements:**
- Metadata **MUST** be empty object `{}`
- No audio metadata is required or permitted

**Idempotency guarantees:**
- Event is idempotent-safe: may be re-emitted on Station restart
- Each shutdown is a distinct transition; event fires once per shutdown
- Event represents the transition from operational to non-operational state

#### E0.9.5 — Deprecated Events

**`now_playing` event is COMPLETELY DEPRECATED and MUST NOT be emitted.**

- **FORBIDDEN**: Emitting `now_playing` events with any metadata (including empty metadata)
- **FORBIDDEN**: Using `now_playing` events to represent current state
- **FORBIDDEN**: Inferring state from `now_playing` event presence or absence
- **REQUIRED**: Use stateful querying via Station State Contract for current state
- **REQUIRED**: Use edge-triggered events (`song_playing`, `segment_playing`, `station_startup`, `station_shutdown`) for transitions
- Consumers **MUST NOT** rely on `now_playing` events; all consumers MUST migrate to stateful querying

---

## E1 — THINK/DO Behavior During Shutdown

The THINK/DO model **MUST** be preserved during shutdown, with explicit rules governing shutdown detection and terminal intent execution.

### E1.1 — Lifecycle Detection

**Startup and shutdown detection MUST occur OUTSIDE the THINK/DO cycle.**

- Startup and shutdown state is managed by Station lifecycle (per StationLifecycle Contract)
- Lifecycle detection **MUST NOT** occur during THINK or DO execution
- Lifecycle state **MAY** be observed by THINK, but lifecycle logic **MUST NOT** execute within THINK or DO

### E1.2 — THINK During Lifecycle

**Lifecycle state MAY be observed during THINK.**

- During startup, THINK **MAY** observe startup state and select startup announcement
- During shutdown, when Station is in DRAINING state, THINK **MAY** observe the shutdown flag
- THINK **MAY** produce a terminal DJIntent when shutdown is active
- Terminal intent **MUST** be marked as TERMINAL (per DJIntent Contract)
- THINK **MUST NOT** trigger lifecycle state changes itself
- THINK **MUST NOT** perform lifecycle-specific I/O or blocking work beyond normal THINK operations

### E1.3 — DO During Lifecycle

**DO executes intent without branching on lifecycle state.**

- DO **MUST** execute intent (startup announcement, normal intent, or terminal intent) when provided
- Intent execution **MUST** follow all normal DO rules regardless of lifecycle state
- DO **MUST NOT** branch behavior based on lifecycle state
- DO **MUST NOT** perform lifecycle-specific operations beyond intent execution

### E1.4 — THINK/DO Separation Preserved

**THINK/DO separation MUST be preserved during shutdown.**

- Shutdown logic **MUST NOT** execute during DO beyond intent execution
- THINK prepares terminal intent; DO executes it
- No shutdown-specific behavior **MAY** be embedded in DO phase
- All shutdown orchestration occurs outside THINK/DO boundaries

### E1.5 — Event Prohibition After Terminal DO

**After terminal intent execution, no further THINK or DO events MAY fire.**

- System **MUST** prevent new THINK/DO cycles after terminal DO completes
- Callbacks **MUST** be disabled or ignored after terminal DO
- System transitions to SHUTTING_DOWN state (PHASE 2) after terminal segment finishes (or immediately if no terminal segment)
- Purely observational events (per E0.7, E1.6) **MAY** continue after terminal DO completes
- Observational events **MUST NOT** be THINK or DO events
- Observational events **MUST NOT** mutate state, affect timing, or modify queues

### E1.6 — Observability Events During Shutdown

**Non-THINK/DO observability events MAY continue during shutdown.**

- Observability events (per E0.7) **MAY** be emitted during shutdown phases
- Shutdown-related observability events **MAY** include:
  - `station_shutting_down` — emitted when Station enters DRAINING state
  - `shutdown_announcement_started` — emitted when shutdown announcement segment starts (if present)
  - `shutdown_announcement_finished` — emitted when shutdown announcement segment finishes (if present)
- These events **MUST** be purely observational and **MUST NOT** influence shutdown behavior
- These events **MUST NOT** trigger THINK or DO cycles
- Observability events **MAY** continue until process exit

---

## Contract Dependencies

All other Station contracts reference this contract:

- **StationLifecycle Contract**: Defines startup/shutdown within THINK/DO model
- **DJEngine Contract**: Implements THINK phase
- **DJIntent Contract**: Defines the output of THINK phase
- **PlayoutEngine Contract**: Executes DO phase
- **AudioEvent Contract**: Atomic unit passed from THINK to DO

---

## LOG — Logging and Observability

### LOG1 — Log File Location
Master System components **MUST** write all log output to `/var/log/retrowaves/station.log`.

- Log file path **MUST** be deterministic and fixed
- Log file **MUST** be readable by the retrowaves user/group
- Master System components **MUST NOT** require elevated privileges at runtime to write logs

### LOG2 — Non-Blocking Logging
Logging operations **MUST** be non-blocking and **MUST NOT** interfere with THINK/DO event model.

- Logging **MUST NOT** block THINK phase execution
- Logging **MUST NOT** block DO phase execution
- Logging **MUST NOT** delay lifecycle event callbacks
- Logging **MUST NOT** delay heartbeat event emission
- Logging failures **MUST** degrade silently (stderr fallback allowed)

### LOG3 — Rotation Tolerance
Master System components **MUST** tolerate external log rotation without crashing or stalling.

- Master System components **MUST** assume logs may be rotated externally (e.g., via logrotate)
- Master System components **MUST** handle log file truncation or rename gracefully
- Master System components **MUST NOT** implement rotation logic in application code
- Master System components **MUST** reopen log files if they are rotated (implementation-defined mechanism)
- Rotation **MUST NOT** cause THINK/DO cycle interruption

### LOG4 — Failure Behavior
If log file write operations fail, Master System **MUST** continue THINK/DO operations normally.

- Logging failures **MUST NOT** crash the process
- Logging failures **MUST NOT** interrupt THINK/DO cycles
- Logging failures **MUST NOT** interrupt event callbacks
- Master System components **MAY** fall back to stderr for critical errors, but **MUST NOT** block on stderr writes

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

- THINK phase typically occurs during `on_segment_started()` callback
- DO phase typically occurs during `on_segment_finished()` callback
- The separation ensures playout never blocks on decision-making
- All state mutations (queue, rotation history) occur only during DO





