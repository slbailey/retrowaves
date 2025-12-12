# EncoderManager Contract

## M. Purpose

**EncoderManager** is the single, authoritative decision-maker for which audio source is used each tick:

- **Program** (upstream PCM)
- **Grace-period silence**
- **Fallback** (via fallback provider: file, tone, or silence)

EncoderManager encapsulates the grace period and fallback state machine and guarantees that every tick produces a valid PCM frame for FFmpeg.

---

## S7.0 — PCM Availability Invariants

**PCM Flow Architecture:**
- **EncoderManager** defines PCM (format, size, rate, channel count)
- **FallbackProvider** supplies PCM (conforms to EncoderManager's format)
- **Supervisor** delivers PCM (passes through to FFmpeg)
- **FFmpeg** consumes PCM (encodes to MP3)

These invariants define **WHAT** must always be true, not **HOW** to do it.

### S7.0A — Continuous PCM Guarantee
EncoderManager **MUST** always return a valid PCM frame (correct size, rate, channel count) whenever `next_frame()` is called.

There are no exceptions.

### S7.0B — Startup PCM Availability
Before FFmpeg Supervisor is started, EncoderManager **MUST** already be capable of supplying valid PCM via fallback.

This ensures:
- Supervisor startup cannot race ahead of PCM readiness
- FFmpeg never starts without input available
- No silent or empty stdin states
- No premature FFmpeg exits during BOOTING

### S7.0C — Fallback PCM Obligations
If upstream PCM is not yet available, EncoderManager **MUST** return fallback PCM, provided by FallbackProvider.

Fallback PCM **MUST** fully conform to EncoderManager's PCM format contract, including:
- Sample rate (48,000 Hz)
- Channel count (2 channels, stereo)
- Bytes per frame (4096 bytes)
- Frame cadence expectations: one frame per tick, where tick duration is defined by `NEW_CORE_TIMING_AND_FORMATS_CONTRACT.md` (currently ≈21.333ms)

EncoderManager defines the PCM shape. FallbackProvider only supplies it.

### S7.0D — Never Return None
`next_frame()` **MUST** never return:
- `None`
- An empty byte string
- An incorrectly sized frame

Any violation is a system-level failure per S7.0.

### S7.0E — Silence vs Tone is an Internal Policy
EncoderManager **MAY** choose fallback silence or fallback tone, but consumers (Supervisor) **MUST NOT** depend on which.

### S7.0F — Fallback Must Be Immediate with Tone Preference
FallbackProvider **MUST**:
- Never block (non-blocking operation)
- Never compute slowly (avoid slow operations like file I/O during frame generation)
- Always return a full frame immediately (zero latency concept: very fast, non-blocking)
- **Prefer 440Hz tone** over silence whenever possible
- Use silence only if tone generation is not possible for any reason

"Zero latency" is a conceptual requirement meaning the operation must be very fast, non-blocking, and deterministic. The actual timing may vary based on system load, but the operation must never block and must complete quickly enough to support real-time playout at 21.333ms tick intervals (PCM cadence).

This supports real-time playout and ensures continuous, audible fallback audio (tone) rather than silence whenever feasible.

---

## N. Inputs and Outputs per Tick

### M1
On each `AudioPump` tick, EncoderManager receives:

- `pcm_from_upstream` — an optional PCM frame (or `None`)
- Access to a canonical `silence_frame` (precomputed, for grace period)
- Access to a fallback provider (for post-grace fallback frames)
- Access to a clock function `now()` (wall clock or tick time)

### M2
On each tick, EncoderManager **MUST** return:

- Exactly one PCM frame of the format defined in the core timing contract
- That frame **MUST** be one of:
  - The upstream PCM frame (program)
  - The canonical silence frame (grace period)
  - A frame from the fallback provider (file, tone, or silence as determined by provider)

### M3
EncoderManager **MUST NOT** return `None` or a partially-filled frame.

---

## O. State and Grace Logic

### M4
EncoderManager **MUST** maintain the notion of:

- `last_pcm_seen_at` — timestamp of the last tick where a valid upstream PCM frame was received

### M5
On construction, EncoderManager **MUST** set `last_pcm_seen_at` to the current time so that initial behaviour is interpreted as being "within grace".

### Source Selection Rules

On each tick:

#### M6
If `pcm_from_upstream` is present and valid:

- **M6.1** — EncoderManager **MUST** update `last_pcm_seen_at` to `now()`
- **M6.2** — EncoderManager **MUST** return `pcm_from_upstream` as the output frame (**PROGRAM**)

#### M7
If `pcm_from_upstream` is absent on this tick:

Let `since = now() - last_pcm_seen_at`.

- **M7.1** — If `since <= GRACE_SEC`:
  - EncoderManager **MUST** return the canonical `silence_frame` (**GRACE_SILENCE**)
- **M7.2** — If `since > GRACE_SEC`:
  - EncoderManager **MUST** call `fallback_provider.next_frame()` to request a frame
  - EncoderManager **MUST** return the frame provided by the fallback provider (**FALLBACK**)
  - The fallback provider may return file PCM, tone PCM, or silence PCM according to its internal selection logic

### M8
`GRACE_SEC` **MUST** be configurable via configuration or environment (default **5 seconds**) and **MUST** be the only grace period parameter used in the system.

---

### M-GRACE — Grace Period Requirements

#### M-GRACE1
Grace timers **MUST** use a monotonic clock.

#### M-GRACE2
Silence frame **MUST** be precomputed and reused.

#### M-GRACE3
At exactly `t == GRACE_SEC`, silence still applies; tone applies only at `t > GRACE_SEC`.

#### M-GRACE4
Grace resets immediately when program PCM returns.

---

## P. Startup Behaviour

### M9
On startup, with no upstream PCM yet available:

Because `last_pcm_seen_at` is initialized to `now()`, `since` will be 0 on the first tick.

EncoderManager **MUST** therefore output silence for at least the first `GRACE_SEC` seconds if no PCM arrives.

### M10
This startup behaviour ensures that:

- FFmpeg receives valid silence frames from the very beginning
- Tower does not emit fallback audio immediately at startup; fallback is reserved for longer outages

---

## Q. Ownership of Routing and Fallback

### M11
EncoderManager is the only component responsible for:

- Implementing grace-period logic
- Deciding when to output program vs grace-period silence vs fallback
- Transitioning from grace-period silence to fallback after prolonged absence of PCM
- Transitioning from fallback back to program when PCM returns

### M12
`FFmpegSupervisor`, `AudioPump`, `TowerRuntime`, and HTTP components **MUST** treat EncoderManager as the single source of truth for audio routing decisions and **MUST NOT**:

- Re-implement grace logic
- Inspect PCM content to infer silence or tone
- Make independent decisions about fallback vs program

---

## R. Interaction with Fallback Provider

### M13
EncoderManager **MUST NOT**:

- Generate silence or tone waveforms itself
- Implement fallback source selection logic (file vs tone vs silence)

### M14
The responsibility for producing fallback PCM frames lies with a fallback provider (e.g., `FallbackGenerator`).

### M15
EncoderManager **MUST** only select between:

- Upstream PCM (program)
- Grace-period silence (precomputed silence frame)
- Fallback provider output (file, tone, or silence as determined by provider)

### M16 — Fallback Provider Interaction

#### M16.1
When `pcm_from_upstream` is absent and grace period has expired (`since > GRACE_SEC`):

- EncoderManager **MUST** call `fallback_provider.next_frame()`
- EncoderManager **MUST** use whatever frame the provider returns

#### M16.2
EncoderManager **MUST NOT**:

- Inspect the content of the fallback frame to determine source type
- Make decisions about which fallback source (file/tone/silence) should be used
- Request a specific type of fallback (e.g., "give me tone, not file")

#### M16.3
The fallback provider **MUST** handle source selection according to the priority order defined in the core timing contract (file → tone → silence).

#### M16.4
The fallback provider **MUST** always return a valid frame per its contract (FP2.4, FP5.3). EncoderManager **MAY** treat any unexpected exception from the provider as a critical error and log appropriately, but the provider contract guarantees this should never occur.

---

## S. Error Handling and Robustness

### M18
If upstream PCM frames are malformed or wrong-sized, EncoderManager **MAY**:

- Treat them as "absent" for the purpose of **M7**
- Log an error for observability

### M17
EncoderManager **MUST** behave correctly even if upstream is permanently absent:

- It **MUST** output fallback frames (via fallback provider) forever after `GRACE_SEC` elapses
- It **MUST** remain responsive to new PCM frames if upstream resumes

---

## LOG — Logging and Observability

### LOG1 — Log File Location
EncoderManager **MUST** write all log output to `/var/log/retrowaves/tower.log`.

- Log file path **MUST** be deterministic and fixed
- Log file **MUST** be readable by the retrowaves user/group
- EncoderManager **MUST NOT** require elevated privileges at runtime to write logs

### LOG2 — Non-Blocking Logging
Logging operations **MUST** be non-blocking and **MUST NOT** interfere with frame routing decisions.

- Logging **MUST NOT** block calls to `next_frame()`
- Logging **MUST NOT** delay PCM frame selection or routing
- Logging **MUST NOT** delay fallback provider calls
- Logging **MUST NOT** affect grace period timing
- Logging failures **MUST** degrade silently (stderr fallback allowed)

### LOG3 — Rotation Tolerance
EncoderManager **MUST** tolerate external log rotation without crashing or stalling.

- EncoderManager **MUST** assume logs may be rotated externally (e.g., via logrotate)
- EncoderManager **MUST** handle log file truncation or rename gracefully
- EncoderManager **MUST NOT** implement rotation logic in application code
- EncoderManager **MUST** reopen log files if they are rotated (implementation-defined mechanism)
- Rotation **MUST NOT** cause frame routing interruption

### LOG4 — Failure Behavior
If log file write operations fail, EncoderManager **MUST** continue routing frames normally.

- Logging failures **MUST NOT** crash the process
- Logging failures **MUST NOT** interrupt frame routing
- Logging failures **MUST NOT** interrupt fallback provider calls
- EncoderManager **MAY** fall back to stderr for critical errors, but **MUST NOT** block on stderr writes

---

## Required Tests

This contract requires the following logging compliance tests:

- LOG1 — Log File Location
- LOG2 — Non-Blocking Logging
- LOG3 — Rotation Tolerance
- LOG4 — Failure Behavior

See `tests/contracts/LOGGING_TEST_REQUIREMENTS.md` for test specifications.
