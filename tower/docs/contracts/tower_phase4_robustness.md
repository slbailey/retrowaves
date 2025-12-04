# Retrowaves Tower — Phase 4 Robustness Contract

**Phase:** 4 (Robustness: Slow Clients + Encoder Restart)  
**Status:** Contract Definition  
**Date:** 2025-01-XX

This document defines the explicit, testable contract for Phase 4 of Retrowaves Tower. Phase 4 introduces encoder robustness with restart logic and exponential backoff, slow-client detection and handling, and backpressure protections to ensure Tower remains stable and responsive under adverse conditions.

---

## Scope

Phase 4 implements:
- ✅ EncoderManager component that owns FFmpeg process lifecycle
- ✅ Encoder restart logic with exponential backoff (1s, 2s, 4s, 8s, 10s)
- ✅ Maximum 5 consecutive restart attempts before entering FAILED state
- ✅ Tower stability during encoder failures (Tower never crashes)
- ✅ Slow-client detection via `TOWER_CLIENT_TIMEOUT_MS` (default: 250ms)
- ✅ Per-client bounded outbound buffers (64 KB threshold)
- ✅ Non-blocking client writes in HTTPConnectionManager
- ✅ Backpressure protection (encoder reader loop never blocks)
- ✅ Graceful client disconnection when slow or buffer-full
- ✅ Compatibility with all Phase 1–3 behavior

Phase 4 does NOT implement:
- ❌ New source types or source switching changes
- ❌ Changes to Unix socket input semantics
- ❌ New HTTP endpoints
- ❌ Per-client statistics or metrics endpoints
- ❌ Multi-encoder load balancing
- ❌ Sophisticated retry policies beyond exponential backoff
- ❌ Encoder health monitoring beyond EOF/error detection

---

## Contract Requirements

### 1. EncoderManager Component

**1.1 Component Purpose**
- Tower must implement an `EncoderManager` component (or equivalent)
- EncoderManager must own the FFmpeg process lifecycle
- EncoderManager must be responsible for:
  - Starting the encoder process
  - Monitoring encoder stdout/stderr and exit code
  - Detecting EOF or error conditions on encoder stdout
  - Triggering restart attempts with exponential backoff
  - Exposing a clear interface for:
    - Writing PCM to encoder stdin (from AudioPump)
    - Reading encoded MP3 chunks for HTTPConnectionManager.broadcast()

**1.2 EncoderManager Interface**
- EncoderManager must provide a method to write PCM frames to encoder stdin
- EncoderManager must provide a method to read MP3 chunks from encoder stdout
- EncoderManager must expose encoder state (RUNNING, RESTARTING, FAILED, STOPPED)
- EncoderManager must expose encoder process status (running, not running)
- EncoderManager interface must be thread-safe

**1.3 EncoderManager State Model**
- EncoderManager must maintain explicit, testable states:
  - `RUNNING` — encoder process is running and producing MP3 output
  - `RESTARTING` — encoder has failed and restart attempt is in progress (backoff delay)
  - `FAILED` — maximum restart attempts (5) have been exhausted
  - `STOPPED` — encoder is stopped (Tower shutdown or explicit stop)
- State transitions must be atomic and observable
- State must be queryable by other components (HTTPConnectionManager, AudioPump)

**1.4 Encoder Startup**
- EncoderManager must start FFmpeg process at Tower startup
- EncoderManager must use the canonical FFmpeg command (same as Phase 1–3)
- EncoderManager must initialize encoder stdin/stdout pipes
- EncoderManager must transition to RUNNING state after successful startup
- Encoder startup must not block Tower HTTP server initialization
- Encoder startup failures must trigger restart logic (not immediate Tower exit)

**1.5 Encoder Monitoring**
- EncoderManager must monitor encoder stdout for EOF conditions
- EncoderManager must monitor encoder stderr for error messages
- EncoderManager must monitor encoder process exit code
- EncoderManager must detect encoder failures within bounded time (≤100ms)
- EncoderManager must detect encoder stdout EOF immediately (non-blocking reads)
- EncoderManager must handle encoder process crashes gracefully

**1.6 AudioPump Integration**
- EncoderManager must ensure AudioPump can continue to run at real-time pace
- AudioPump must be able to write PCM frames to encoder stdin regardless of encoder state
- When encoder is down (RESTARTING or FAILED):
  - AudioPump MUST discard PCM frames when encoder stdin is unavailable
  - AudioPump MUST NOT buffer PCM frames for later delivery
  - AudioPump must continue generating frames at real-time pace
  - Behavior must be explicitly documented and consistent
- EncoderManager must not block AudioPump thread during restarts

**1.7 MP3 Output Interface**
- EncoderManager must provide a method to read MP3 chunks from encoder stdout
- When encoder is RUNNING, method must return MP3 chunks continuously
- When encoder is RESTARTING or FAILED, method must return empty chunks or None
- Method must be non-blocking (timeout-based or non-blocking I/O)
- Method must not block HTTPConnectionManager broadcast loop

---

### 2. Encoder Restart Policy and Backoff

**2.1 Restart Trigger Conditions**
- EncoderManager must trigger restart attempts when:
  - Encoder stdout EOF is detected
  - Encoder process exits (non-zero exit code)
  - Encoder process crashes (SIGSEGV, SIGABRT, etc.)
  - Encoder stderr indicates fatal error (implementation-defined)
- EncoderManager must NOT trigger restart on:
  - Normal encoder shutdown (Tower shutdown signal)
  - Temporary I/O errors that recover immediately

**2.2 Exponential Backoff Schedule**
- EncoderManager must implement exponential backoff for restart attempts
- Backoff delays must follow this exact schedule:
  - Attempt 1: 1 second delay
  - Attempt 2: 2 seconds delay
  - Attempt 3: 4 seconds delay
  - Attempt 4: 8 seconds delay
  - Attempt 5: 10 seconds delay (capped at 10s)
- Backoff delays must be measured from the moment restart is triggered
- Backoff delays must be accurate within ±100ms tolerance
- Backoff delays must not accumulate (each restart uses its own delay)

**2.3 Maximum Restart Attempts**
- EncoderManager must allow maximum 5 consecutive restart attempts
- Restart attempts must be counted per failure sequence (not global lifetime)
- After 5 failed attempts, EncoderManager must enter FAILED state
- EncoderManager must stop attempting new restarts in FAILED state
- EncoderManager must remain in FAILED state until:
  - Tower is restarted (manual intervention)
  - OR explicit reset mechanism (if implemented in future phase)

**2.4 Restart Attempt Execution**
- During RESTARTING state, EncoderManager must:
  - Wait for backoff delay
  - Start new FFmpeg process
  - Initialize encoder stdin/stdout pipes
  - Transition to RUNNING state if startup succeeds
  - Transition back to RESTARTING state if startup fails (increment attempt count)
- Restart attempts must not block Tower HTTP server
- Restart attempts must not block AudioPump
- Restart attempts must not block HTTPConnectionManager

**2.5 FAILED State Behavior**
- When EncoderManager enters FAILED state:
  - Tower must remain up and connectable
  - `/status` endpoint must return `encoder_running: false`
  - `/control/source` endpoint must remain responsive
  - In FAILED state, `/stream` must continue streaming silent MP3 frames indefinitely. The stream MUST NOT disconnect existing clients and MUST NOT return HTTP errors.
- Tower must NEVER crash or exit due to encoder failure
- Tower must continue accepting new client connections
- Existing clients on `/stream` must remain connected and receive silent MP3 frames

**2.6 Tower Stability Guarantees**
- Tower process must never exit due to encoder failure
- Tower process must never crash due to encoder failure
- Tower HTTP server must remain accessible during encoder restarts
- Tower HTTP server must remain accessible in FAILED state
- Tower must handle encoder failures gracefully (log errors, continue operation)

---

### 3. Slow-Client Policy (HTTPConnectionManager)

**3.1 Configuration**
- Tower must support `TOWER_CLIENT_TIMEOUT_MS` environment variable
- Default value: `250` milliseconds (if not set)
- `TOWER_CLIENT_TIMEOUT_MS` must be configurable at startup
- `TOWER_CLIENT_TIMEOUT_MS` must be validated (must be positive integer)
- Invalid `TOWER_CLIENT_TIMEOUT_MS` must cause Tower to exit with error at startup

**3.2 Non-Blocking Client Writes**
- HTTPConnectionManager must implement non-blocking writes to clients
- HTTPConnectionManager.write() or broadcast() must never block indefinitely
- HTTPConnectionManager must use non-blocking sockets or timeout-based writes
- HTTPConnectionManager must detect slow clients within `TOWER_CLIENT_TIMEOUT_MS`

**3.3 Slow-Client Detection**
- HTTPConnectionManager must track per-client write performance
- If a client cannot accept data within `TOWER_CLIENT_TIMEOUT_MS`:
  - That client MUST be dropped (socket closed, internal state cleaned up)
  - Client must be removed from HTTPConnectionManager registries
  - Client's associated buffers must be freed
- Slow-client detection must be continuous (checked on every write attempt)
- Slow-client detection must not block encoder reader loop
- Slow-client detection must not block broadcast loop

**3.4 Per-Client Bounded Buffers**
- Each client must have a bounded, in-memory outbound buffer
- Buffer size threshold: `64 KB` (65536 bytes) — must be documented
- If a client's pending data exceeds 64 KB:
  - The client must be dropped immediately
  - The encoder reader loop must continue unaffected
  - Other clients must continue receiving data normally
- Buffer size must be configurable or documented as fixed constant
- Buffer size must be enforced consistently across all clients

**3.5 Client Drop Behavior**
- When a slow client is dropped:
  - Socket must be closed immediately
  - Client must be removed from HTTPConnectionManager client registry
  - Client's outbound buffer must be freed
  - Client's internal state must be cleaned up
  - No memory leaks or resource leaks
  - *(Non-testable, informational only)* Dropping a slow client SHOULD log a warning
- Dropping a client must not affect other clients
- Dropping a client must not interrupt encoder reader loop
- Dropping a client must not interrupt broadcast loop

**3.6 Broadcast Loop Protection**
- HTTPConnectionManager.broadcast() must fan out MP3 chunks to clients in a way that:
  - Fast clients get all chunks immediately
  - Slow clients get dropped instead of accumulating unbounded backlog
- Broadcast loop must never block due to slow clients
- Broadcast loop must complete within bounded time (≤100ms per chunk)
- Broadcast loop must not skip fast clients when slow clients are present

---

### 4. Backpressure Guarantees

**4.1 Encoder Reader Loop Protection**
- Encoder reader loop must never block because one or more clients are slow
- Encoder reader loop must continue reading MP3 chunks from encoder stdout
- Encoder reader loop must continue calling broadcast() regardless of client state
- Encoder reader loop must not wait for slow clients to catch up
- Encoder reader loop must not accumulate unbounded global backlog

**4.2 No Global Shared Backlog**
- Tower must NOT maintain a global "shared" backlog that grows unbounded
- Tower must NOT buffer MP3 chunks globally when clients are slow
- Tower must NOT accumulate MP3 data in memory beyond per-client buffers
- Each client's buffer is independent and bounded (64 KB max)
- Slow clients must be dropped, not buffered indefinitely

**4.3 AudioPump Protection**
- AudioPump must continue running at real-time pace during encoder restarts
- AudioPump must continue running at real-time pace when clients are slow
- AudioPump must not block on encoder stdin writes (non-blocking or timeout-based)
- AudioPump must discard PCM frames when encoder is down (RESTARTING or FAILED)
- AudioPump must not accumulate unbounded PCM backlog

**4.4 Thread Isolation**
- Encoder reader thread must be isolated from client write operations
- Encoder reader thread must not wait for client write completion
- Client write operations must not block encoder reader thread
- AudioPump thread must be isolated from encoder restart operations
- AudioPump thread must not wait for encoder restart completion

---

### 5. Compatibility with Prior Phases

**5.1 Phase 1 Compatibility**
- All Phase 1 behavior must remain unchanged:
  - `/stream` endpoint semantics (continuous MP3, same headers)
  - FFmpeg command and encoding format
  - MP3 stream format and structure
  - Client connection handling (except slow-client dropping)
- Phase 1 tests must continue to pass

**5.2 Phase 2 Compatibility**
- All Phase 2 behavior must remain unchanged:
  - `/status` endpoint (may add encoder state fields, but existing fields unchanged)
  - `/control/source` endpoint (source switching continues to work)
  - SourceManager, ToneSource, SilenceSource, FileSource behavior
  - Source switching does not interrupt Tower operation
- Phase 2 tests must continue to pass

**5.3 Phase 3 Compatibility**
- All Phase 3 behavior must remain unchanged:
  - Unix socket input semantics
  - AudioInputRouter queue behavior (bounded queue, drop newest on overflow)
  - AudioPump fallback behavior (live PCM → fallback source)
  - Seamless switching between live PCM and fallback
- Phase 3 tests must continue to pass

**5.4 External API Compatibility**
- HTTP endpoints must remain backward compatible:
  - `/stream` endpoint must accept same requests, return same headers
  - `/status` endpoint must return same JSON structure (may add fields)
  - `/control/source` endpoint must accept same requests, return same responses
- MP3 stream output must remain identical in format and structure
- Client connection behavior must remain identical (except slow-client dropping)

**5.5 Internal Architecture Compatibility**
- SourceManager must continue to function as in Phase 2
- AudioPump must continue to function as in Phase 3
- AudioInputRouter must continue to function as in Phase 3
- HTTPConnectionManager must maintain backward compatibility (existing clients unaffected)

---

## Explicit Invariants

### Encoder Invariants

**I1: Encoder Failure Detection**
- EncoderManager must detect EOF or process exit within a bounded time (≤100ms)
- EncoderManager must not miss encoder failures
- EncoderManager must detect failures immediately (non-blocking reads)

**I2: Restart Backoff Schedule**
- Restart delays must follow exact schedule: 1s, 2s, 4s, 8s, 10s (capped at 10s)
- Backoff delays must be accurate within ±100ms tolerance
- Backoff delays must not accumulate or compound

**I3: Maximum Restart Attempts**
- Maximum of 5 consecutive restart attempts before entering FAILED state
- Restart attempt count must reset on successful encoder startup
- Restart attempt count must not exceed 5 in a single failure sequence

**I4: Tower Process Stability**
- Tower process never exits due to encoder failure
- Tower process never crashes due to encoder failure
- Tower HTTP server remains accessible during encoder failures

**I5: Encoder State Consistency**
- EncoderManager state must be consistent at all times
- State transitions must be atomic (no intermediate states visible)
- State must be queryable by other components without blocking

### Slow-Client Invariants

**I6: Non-Blocking Broadcast**
- HTTPConnectionManager.write/broadcast must never block the encoder reader thread
- HTTPConnectionManager.write/broadcast must complete within bounded time (≤100ms per chunk)
- Slow clients must not cause encoder reader loop to stall

**I7: Slow-Client Drop Policy**
- A client that exceeds time budget (`TOWER_CLIENT_TIMEOUT_MS`) must be dropped
- A client that exceeds buffer budget (64 KB) must be dropped
- Dropped clients must be cleaned up immediately (socket closed, state freed)

**I8: Fast-Client Protection**
- Dropping slow clients must not disconnect or stall fast clients
- Fast clients must continue receiving all MP3 chunks
- Fast clients must not be affected by slow-client presence

**I9: Per-Client Buffer Bounds**
- Each client's outbound buffer must never exceed 64 KB
- Buffer size must be enforced before adding new data
- Buffer overflow must trigger immediate client drop

### Backpressure Invariants

**I10: No Unbounded Global Buffering**
- No unbounded global buffering of MP3 data
- No unbounded global buffering of PCM data
- Memory usage must be bounded by: (number of clients × 64 KB) + fixed overhead

**I11: Encoder Reader Loop Independence**
- Encoder reader loop continues to pull data as long as encoder is running
- Encoder reader loop behavior is independent of client behavior
- Encoder reader loop never blocks on client writes

**I12: AudioPump Independence**
- AudioPump continues to run at real-time pace during encoder restarts
- AudioPump continues to run at real-time pace when clients are slow
- AudioPump timing is independent of encoder state and client state

**I13: Thread Isolation**
- Encoder reader thread is isolated from client write operations
- AudioPump thread is isolated from encoder restart operations
- Client write threads are isolated from encoder reader thread

---

## Test Mapping

Each contract requirement above maps directly to one or more test cases in `tests/contracts/test_phase4_robustness.py`:

- **Section 1 (EncoderManager Component)** → EncoderManager tests, state model tests, interface tests, AudioPump integration tests
- **Section 2 (Encoder Restart Policy)** → Restart trigger tests, backoff schedule tests, maximum attempts tests, FAILED state tests, Tower stability tests
- **Section 3 (Slow-Client Policy)** → Configuration tests, non-blocking write tests, slow-client detection tests, buffer threshold tests, client drop tests, broadcast loop tests
- **Section 4 (Backpressure Guarantees)** → Encoder reader loop protection tests, no global backlog tests, AudioPump protection tests, thread isolation tests
- **Section 5 (Compatibility)** → Phase 1 regression tests, Phase 2 regression tests, Phase 3 regression tests, external API compatibility tests
- **Invariants I1–I5 (Encoder)** → Encoder failure detection tests, backoff accuracy tests, restart attempt limit tests, Tower stability tests, state consistency tests
- **Invariants I6–I9 (Slow-Client)** → Non-blocking broadcast tests, slow-client drop tests, fast-client protection tests, buffer bound tests
- **Invariants I10–I13 (Backpressure)** → Memory bound tests, encoder reader independence tests, AudioPump independence tests, thread isolation tests

---

## Out of Scope (Explicitly Excluded)

The following features are explicitly excluded from Phase 4:

- ❌ New source types (tone, silence, file remain the only sources)
- ❌ Changes to Unix socket input semantics (AudioInputRouter behavior unchanged)
- ❌ New HTTP endpoints (only existing endpoints: `/stream`, `/status`, `/control/source`)
- ❌ Sophisticated per-client statistics or metrics endpoints
- ❌ Multi-encoder load balancing or failover
- ❌ Encoder health monitoring beyond EOF/error detection
- ❌ Advanced retry policies (only exponential backoff with fixed schedule)
- ❌ Per-client quality-of-service (QoS) or priority levels
- ❌ Client reconnection logic or automatic retry
- ❌ Historical encoder failure logging or analytics
- ❌ Dynamic backoff adjustment based on failure patterns
- ❌ Encoder process resource limits or cgroup management

---

## Success Criteria

Phase 4 is complete when:

1. ✅ EncoderManager component exists and owns FFmpeg process lifecycle
2. ✅ EncoderManager implements exponential backoff (1s, 2s, 4s, 8s, 10s)
3. ✅ EncoderManager enforces maximum 5 restart attempts before FAILED state
4. ✅ Tower remains up and connectable during encoder failures (never crashes)
5. ✅ `/status` and `/control/source` remain responsive during encoder restarts
6. ✅ `/stream` behavior in FAILED state is explicitly documented and testable
7. ✅ `TOWER_CLIENT_TIMEOUT_MS` configuration works (default: 250ms)
8. ✅ Slow clients are detected and dropped within timeout
9. ✅ Per-client buffers are bounded at 64 KB threshold
10. ✅ HTTPConnectionManager writes are non-blocking
11. ✅ Encoder reader loop never blocks due to slow clients
12. ✅ No unbounded global buffering of MP3 or PCM data
13. ✅ Fast clients remain stable during encoder restarts and slow-client drops
14. ✅ AudioPump continues at real-time pace during encoder restarts
15. ✅ All Phase 1 contract tests still pass
16. ✅ All Phase 2 contract tests still pass
17. ✅ All Phase 3 contract tests still pass
18. ✅ All Phase 4 contract tests pass
19. ✅ All invariants are verified by tests

---

**Document:** Tower Phase 4 Robustness Contract  
**Version:** 1.0  
**Last Updated:** 2025-01-XX

