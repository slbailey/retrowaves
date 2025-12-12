# Logging Contract Test Requirements

This document defines the required contract tests for logging behavior across all components. Tests must verify that logging clauses in contracts are satisfied without implementing the actual logging code.

## Test Organization

Tests should be added to existing contract test files under:
- `tower/tests/contracts/` for Tower component tests
- `station/tests/contracts/` for Station component tests

Each test class should map directly to contract logging clauses (LOG1, LOG2, LOG3, LOG4).

---

## Tower Component Tests

### TowerRuntime Contract Tests

**File:** `tower/tests/contracts/test_new_tower_runtime_contract.py`

#### TestLOG1_LogFileLocation
- **Purpose:** Verify logs are written to `/var/log/retrowaves/tower.log`
- **Requirements:**
  - Component writes logs to correct path
  - Path is deterministic and fixed
  - Log file is readable by retrowaves user/group
  - No elevated privileges required at runtime

#### TestLOG2_NonBlockingLogging
- **Purpose:** Verify logging does not block audio processing
- **Requirements:**
  - Logging does not block HTTP stream endpoint
  - Logging does not block MP3 broadcast loop
  - Logging does not block event ingestion/delivery
  - Logging does not block buffer status endpoint
  - Logging failures degrade silently

#### TestLOG3_RotationTolerance
- **Purpose:** Verify component tolerates external log rotation
- **Requirements:**
  - Component handles log file truncation gracefully
  - Component handles log file rename gracefully
  - Component does not crash when log is rotated
  - Component does not stall when log is rotated
  - Rotation does not interrupt audio pipeline

#### TestLOG4_FailureBehavior
- **Purpose:** Verify logging failures do not crash component
- **Requirements:**
  - Logging failures do not crash process
  - Logging failures do not interrupt HTTP streaming
  - Logging failures do not interrupt audio processing
  - Component continues operating normally when logging fails

---

### AudioPump Contract Tests

**File:** `tower/tests/contracts/test_new_audiopump_contract.py`

#### TestLOG1_LogFileLocation
- **Purpose:** Verify logs are written to `/var/log/retrowaves/tower.log`
- **Requirements:** Same as TowerRuntime LOG1

#### TestLOG2_NonBlockingLogging
- **Purpose:** Verify logging does not block tick loop
- **Requirements:**
  - Logging does not block tick loop
  - Logging does not introduce timing drift or jitter
  - Logging does not delay calls to EncoderManager
  - Logging does not delay PCM frame emission
  - Logging failures degrade silently

#### TestLOG3_RotationTolerance
- **Purpose:** Verify component tolerates external log rotation
- **Requirements:**
  - Component handles log rotation gracefully
  - Rotation does not interrupt tick loop
  - Component continues ticking during rotation

#### TestLOG4_FailureBehavior
- **Purpose:** Verify logging failures do not crash component
- **Requirements:**
  - Logging failures do not crash process
  - Logging failures do not interrupt tick loop
  - Logging failures do not interrupt PCM frame production

---

### EncoderManager Contract Tests

**File:** `tower/tests/contracts/test_new_encoder_manager_contract.py`

#### TestLOG1_LogFileLocation
- **Purpose:** Verify logs are written to `/var/log/retrowaves/tower.log`
- **Requirements:** Same as TowerRuntime LOG1

#### TestLOG2_NonBlockingLogging
- **Purpose:** Verify logging does not block frame routing
- **Requirements:**
  - Logging does not block `next_frame()` calls
  - Logging does not delay PCM frame selection
  - Logging does not delay fallback provider calls
  - Logging does not affect grace period timing
  - Logging failures degrade silently

#### TestLOG3_RotationTolerance
- **Purpose:** Verify component tolerates external log rotation
- **Requirements:**
  - Component handles log rotation gracefully
  - Rotation does not interrupt frame routing
  - Component continues routing frames during rotation

#### TestLOG4_FailureBehavior
- **Purpose:** Verify logging failures do not crash component
- **Requirements:**
  - Logging failures do not crash process
  - Logging failures do not interrupt frame routing
  - Logging failures do not interrupt fallback provider calls

---

### FFmpegSupervisor Contract Tests

**File:** `tower/tests/contracts/test_new_ffmpeg_supervisor_contract.py`

#### TestLOG1_LogFileLocation
- **Purpose:** Verify logs are written to `/var/log/retrowaves/ffmpeg.log`
- **Requirements:**
  - Component writes logs to correct path (ffmpeg-specific log file)
  - Path is deterministic and fixed
  - Log file is readable by retrowaves user/group
  - No elevated privileges required at runtime

#### TestLOG2_NonBlockingLogging
- **Purpose:** Verify logging does not block PCM frame processing
- **Requirements:**
  - Logging does not block `push_pcm_frame()` calls
  - Logging does not delay PCM writes to ffmpeg stdin
  - Logging does not block process monitoring
  - Logging does not affect MP3 output availability
  - Logging failures degrade silently

#### TestLOG3_RotationTolerance
- **Purpose:** Verify component tolerates external log rotation
- **Requirements:**
  - Component handles log rotation gracefully
  - Rotation does not interrupt PCM processing
  - Rotation does not cause ffmpeg process restart
  - Component continues processing during rotation

#### TestLOG4_FailureBehavior
- **Purpose:** Verify logging failures do not crash component
- **Requirements:**
  - Logging failures do not crash process
  - Logging failures do not interrupt PCM frame processing
  - Logging failures do not interrupt ffmpeg process management

---

### PCM Ingestion Contract Tests

**File:** `tower/tests/contracts/test_new_pcm_ingest_contract.py`

#### TestLOG1_LogFileLocation
- **Purpose:** Verify logs are written to `/var/log/retrowaves/tower.log`
- **Requirements:** Same as TowerRuntime LOG1

#### TestLOG2_NonBlockingLogging
- **Purpose:** Verify logging does not block frame ingestion
- **Requirements:**
  - Logging does not block frame acceptance
  - Logging does not delay frame validation
  - Logging does not delay frame delivery to buffer
  - Logging does not affect transport connection handling
  - Logging failures degrade silently

#### TestLOG3_RotationTolerance
- **Purpose:** Verify component tolerates external log rotation
- **Requirements:**
  - Component handles log rotation gracefully
  - Rotation does not interrupt frame ingestion
  - Component continues accepting frames during rotation

#### TestLOG4_FailureBehavior
- **Purpose:** Verify logging failures do not crash component
- **Requirements:**
  - Logging failures do not crash process
  - Logging failures do not interrupt frame acceptance
  - Logging failures do not interrupt frame delivery to buffer

---

### Fallback Provider Contract Tests

**File:** `tower/tests/contracts/test_new_fallback_provider_contract.py`

#### TestLOG1_LogFileLocation
- **Purpose:** Verify logs are written to `/var/log/retrowaves/tower.log`
- **Requirements:** Same as TowerRuntime LOG1

#### TestLOG2_NonBlockingLogging
- **Purpose:** Verify logging does not block frame generation
- **Requirements:**
  - Logging does not block `next_frame()` calls
  - Logging does not delay frame generation
  - Logging does not affect zero-latency requirement (FP2.2)
  - Logging does not delay fallback source selection
  - Logging failures degrade silently

#### TestLOG3_RotationTolerance
- **Purpose:** Verify component tolerates external log rotation
- **Requirements:**
  - Component handles log rotation gracefully
  - Rotation does not interrupt frame generation
  - Component continues generating frames during rotation

#### TestLOG4_FailureBehavior
- **Purpose:** Verify logging failures do not crash component
- **Requirements:**
  - Logging failures do not crash process
  - Logging failures do not interrupt frame generation
  - Logging failures do not interrupt fallback source selection

---

## Station Component Tests

### PlayoutEngine Contract Tests

**File:** `station/tests/contracts/test_playout_engine_contract.py`

#### TestLOG1_LogFileLocation
- **Purpose:** Verify logs are written to `/var/log/retrowaves/station.log`
- **Requirements:**
  - Component writes logs to correct path
  - Path is deterministic and fixed
  - Log file is readable by retrowaves user/group
  - No elevated privileges required at runtime

#### TestLOG2_NonBlockingLogging
- **Purpose:** Verify logging does not block audio playout
- **Requirements:**
  - Logging does not block segment decoding
  - Logging does not block PCM frame output
  - Logging does not block Clock A decode pacing (if used)
  - Logging does not delay segment start/finish events
  - Logging does not block heartbeat event emission
  - Logging failures degrade silently

#### TestLOG3_RotationTolerance
- **Purpose:** Verify component tolerates external log rotation
- **Requirements:**
  - Component handles log rotation gracefully
  - Rotation does not interrupt audio playout
  - Component continues playing during rotation

#### TestLOG4_FailureBehavior
- **Purpose:** Verify logging failures do not crash component
- **Requirements:**
  - Logging failures do not crash process
  - Logging failures do not interrupt segment playback
  - Logging failures do not interrupt PCM frame output

---

### DJEngine Contract Tests

**File:** `station/tests/contracts/test_dj_engine_contract.py`

#### TestLOG1_LogFileLocation
- **Purpose:** Verify logs are written to `/var/log/retrowaves/station.log`
- **Requirements:** Same as PlayoutEngine LOG1

#### TestLOG2_NonBlockingLogging
- **Purpose:** Verify logging does not block THINK phase
- **Requirements:**
  - Logging does not block THINK operations
  - Logging does not delay song selection
  - Logging does not delay intent creation
  - Logging does not delay THINK lifecycle events
  - Logging does not affect time-bounded requirement (DJ2.3)
  - Logging failures degrade silently

#### TestLOG3_RotationTolerance
- **Purpose:** Verify component tolerates external log rotation
- **Requirements:**
  - Component handles log rotation gracefully
  - Rotation does not interrupt THINK phase
  - Component continues THINK operations during rotation

#### TestLOG4_FailureBehavior
- **Purpose:** Verify logging failures do not crash component
- **Requirements:**
  - Logging failures do not crash process
  - Logging failures do not interrupt song selection
  - Logging failures do not interrupt intent creation

---

### OutputSink Contract Tests

**File:** `station/tests/contracts/test_output_sink_contract.py`

#### TestLOG1_LogFileLocation
- **Purpose:** Verify logs are written to `/var/log/retrowaves/station.log`
- **Requirements:** Same as PlayoutEngine LOG1

#### TestLOG2_NonBlockingLogging
- **Purpose:** Verify logging does not block PCM frame output
- **Requirements:**
  - Logging does not block PCM frame writes
  - Logging does not delay socket writes to Tower
  - Logging does not block buffer health events
  - Logging does not affect non-blocking requirement (OS1.2)
  - Logging failures degrade silently

#### TestLOG3_RotationTolerance
- **Purpose:** Verify component tolerates external log rotation
- **Requirements:**
  - Component handles log rotation gracefully
  - Rotation does not interrupt PCM output
  - Component continues outputting frames during rotation

#### TestLOG4_FailureBehavior
- **Purpose:** Verify logging failures do not crash component
- **Requirements:**
  - Logging failures do not crash process
  - Logging failures do not interrupt PCM frame output
  - Logging failures do not interrupt socket writes

---

### StationLifecycle Contract Tests

**File:** `station/tests/contracts/test_station_lifecycle_contract.py`

#### TestLOG1_LogFileLocation
- **Purpose:** Verify logs are written to `/var/log/retrowaves/station.log`
- **Requirements:** Same as PlayoutEngine LOG1

#### TestLOG2_NonBlockingLogging
- **Purpose:** Verify logging does not block startup/shutdown
- **Requirements:**
  - Logging does not block component loading during startup
  - Logging does not block state persistence during shutdown
  - Logging does not delay state transitions
  - Logging does not delay audio component cleanup
  - Logging failures degrade silently

#### TestLOG3_RotationTolerance
- **Purpose:** Verify component tolerates external log rotation
- **Requirements:**
  - Component handles log rotation gracefully
  - Rotation does not interrupt startup
  - Rotation does not interrupt shutdown
  - Component continues lifecycle operations during rotation

#### TestLOG4_FailureBehavior
- **Purpose:** Verify logging failures do not crash component
- **Requirements:**
  - Logging failures do not crash process
  - Logging failures do not interrupt component loading
  - Logging failures do not interrupt state persistence

---

### MasterSystem Contract Tests

**File:** `station/tests/contracts/test_master_system_contract.py`

#### TestLOG1_LogFileLocation
- **Purpose:** Verify logs are written to `/var/log/retrowaves/station.log`
- **Requirements:** Same as PlayoutEngine LOG1

#### TestLOG2_NonBlockingLogging
- **Purpose:** Verify logging does not block THINK/DO cycles
- **Requirements:**
  - Logging does not block THINK phase execution
  - Logging does not block DO phase execution
  - Logging does not delay lifecycle event callbacks
  - Logging does not delay heartbeat event emission
  - Logging failures degrade silently

#### TestLOG3_RotationTolerance
- **Purpose:** Verify component tolerates external log rotation
- **Requirements:**
  - Component handles log rotation gracefully
  - Rotation does not interrupt THINK/DO cycles
  - Component continues THINK/DO operations during rotation

#### TestLOG4_FailureBehavior
- **Purpose:** Verify logging failures do not crash component
- **Requirements:**
  - Logging failures do not crash process
  - Logging failures do not interrupt THINK/DO cycles
  - Logging failures do not interrupt event callbacks

---

### FFmpegDecoder Contract Tests

**File:** `station/tests/contracts/test_ffmpeg_decoder_contract.py`

#### TestLOG1_LogFileLocation
- **Purpose:** Verify logs are written to `/var/log/retrowaves/station.log`
- **Requirements:** Same as PlayoutEngine LOG1

#### TestLOG2_NonBlockingLogging
- **Purpose:** Verify logging does not block decoding
- **Requirements:**
  - Logging does not block frame decoding
  - Logging does not delay PCM frame delivery
  - Logging does not affect consumption rate (FD2.2)
  - Logging does not block file I/O
  - Logging failures degrade silently

#### TestLOG3_RotationTolerance
- **Purpose:** Verify component tolerates external log rotation
- **Requirements:**
  - Component handles log rotation gracefully
  - Rotation does not interrupt decoding
  - Component continues decoding during rotation

#### TestLOG4_FailureBehavior
- **Purpose:** Verify logging failures do not crash component
- **Requirements:**
  - Logging failures do not crash process
  - Logging failures do not interrupt frame decoding
  - Logging failures do not interrupt PCM frame delivery

---

### Mixer Contract Tests

**File:** `station/tests/contracts/test_mixer_contract.py`

#### TestLOG1_LogFileLocation
- **Purpose:** Verify logs are written to `/var/log/retrowaves/station.log`
- **Requirements:** Same as PlayoutEngine LOG1

#### TestLOG2_NonBlockingLogging
- **Purpose:** Verify logging does not block frame processing
- **Requirements:**
  - Logging does not block gain application
  - Logging does not delay frame output
  - Logging does not affect latency requirement (MX1.3)
  - Logging does not affect timing preservation (MX1.2)
  - Logging failures degrade silently

#### TestLOG3_RotationTolerance
- **Purpose:** Verify component tolerates external log rotation
- **Requirements:**
  - Component handles log rotation gracefully
  - Rotation does not interrupt frame processing
  - Component continues processing during rotation

#### TestLOG4_FailureBehavior
- **Purpose:** Verify logging failures do not crash component
- **Requirements:**
  - Logging failures do not crash process
  - Logging failures do not interrupt gain application
  - Logging failures do not interrupt frame output

---

## Test Implementation Guidelines

### Test Doubles
- Use test doubles (mocks, stubs, fakes) to simulate logging behavior
- Mock log file operations to test rotation and failure scenarios
- Use in-memory log handlers for testing log file location requirements
- Simulate log rotation by truncating or renaming log files during test execution

### Test Structure
- Each test class should map to contract logging clauses (LOG1, LOG2, LOG3, LOG4)
- Tests should verify behavioral requirements, not implementation details
- Tests should be deterministic and repeatable
- Tests should not require actual log file system access (use test doubles)

### Key Test Scenarios

#### Log File Location Tests (LOG1)
- Verify component attempts to write to correct log file path
- Verify path is deterministic (not randomly generated)
- Verify no elevated privileges are required
- Use file system mocks to verify path usage

#### Non-Blocking Tests (LOG2)
- Verify logging operations complete quickly (< 1ms typical)
- Verify logging does not block critical paths (tick loops, frame processing, etc.)
- Verify logging failures do not propagate to audio pipeline
- Use timing measurements to verify non-blocking behavior

#### Rotation Tolerance Tests (LOG3)
- Simulate log file truncation during component operation
- Simulate log file rename during component operation
- Verify component continues operating normally during rotation
- Verify component reopens log files after rotation
- Use file system mocks to simulate rotation scenarios

#### Failure Behavior Tests (LOG4)
- Simulate log file write failures (permission denied, disk full, etc.)
- Verify component continues operating normally when logging fails
- Verify component does not crash on logging failures
- Verify component may fall back to stderr (but does not block on stderr)
- Use file system mocks to simulate failure scenarios

---

## Test Execution

Tests should be run as part of the standard contract test suite:

```bash
python3 run_contract_tests.py
```

All logging contract tests **MUST** pass before logging implementation code is written.

---

## Notes

- **No Implementation Code:** These tests define requirements only. Implementation code will be written separately.
- **Contract Compliance:** Tests verify contract clauses are satisfied, not implementation details.
- **Test Doubles:** All tests use test doubles to avoid real file system dependencies.
- **Behavioral Focus:** Tests verify behavioral requirements (non-blocking, rotation tolerance, failure handling), not logging library choices.

