# 📘 Retrowaves — Future Enhancements & Expansion Wishlist

## Introduction

This document is a **wishlist of ideas** for potential future enhancements to the Retrowaves radio automation system. It serves as a design sandbox for features worth exploring after the core THINK/DO system and real-time audio streaming are stable.

**What This Document Is:**
- A prioritized list of potential features and enhancements
- Ideas organized by importance (stability/performance first, then features, then nice-to-haves)
- A reference for future development phases
- Non-binding suggestions that can be implemented when ready

**What This Document Is NOT:**
- Implementation guidance or requirements
- Part of the core Architecture specification
- Binding commitments or deadlines

**Note:** Retrowaves is the software platform. Appalachia Radio is the first station instance that uses this software.

---

## Priority Overview

This wishlist is organized by priority, starting with features that affect **overall stability, performance, and broadcast-grade implementation**, then moving down to less critical enhancements:

1. **🎯 Next Priority** - Features ready for immediate implementation
2. **🔧 Stability & Performance** - Core system improvements
3. **📡 Broadcast-Grade Features** - Professional radio capabilities
4. **⚙️ Operational Enhancements** - Tools and workflows
5. **🎨 User Experience** - Monitoring and interfaces
6. **🤖 AI & Advanced Features** - Experimental capabilities
7. **🌟 Stretch Goals** - Fun/experimental ideas
8. **✅ Completed Work** - Features that have been implemented

---

## 🎯 Next Priority

### Graceful Shutdown with Offline Announcement

**Status:** 🎯 **NEXT PRIORITY** - Ready for implementation

**Current Status:**
- Station shutdown is immediate when stop() is called
- No graceful completion of current playback
- No offline announcement

**Desired Future Behavior:**
- On shutdown request (SIGTERM, Ctrl+C, or stop() call):
  - Current segment (song/intro/outro/ID) finishes playing completely
  - Playout engine stops accepting new segments from queue
  - DJ optionally generates/selects an offline announcement
  - Offline announcement plays (e.g., station-specific message like "Appalachia Radio is going offline for maintenance. We'll be back soon!")
  - After announcement completes, gracefully close all connections and stop
- Listeners hear a clean end to the stream, not an abrupt cut
- State is saved after current segment finishes (warm restart possible)

**Benefits:**
- Professional shutdown experience for listeners
- Clean state persistence for warm restarts
- Configurable offline announcements
- Respects THINK/DO separation

**Implementation Notes:**
- Shutdown should be a two-phase process:
  1. **Soft shutdown**: Stop accepting new segments, finish current playback
  2. **Hard shutdown**: Close connections, save state, exit
- Offline announcement could be:
  - Pre-recorded MP3 file (simple)
  - Dynamically generated via TTS during THINK window (if TTS is available)
  - Selected from a pool of offline messages
- Should respect THINK/DO separation:
  - Shutdown request detected during THINK or DO
  - Announcement queued during next THINK window
  - Plays during DO phase
- Timeout safety: If current segment is very long, allow configurable max wait time
- HTTP stream connections should remain open until announcement completes

---

## 🔧 Stability & Performance


### Centralized Logging with Rotation

**Future Goal:** All Retrowaves components should write logs to standardized locations with automatic log rotation.

**Desired Behavior:**
- Each component writes to `/var/log/retrowaves-<component>.log`
  - `retrowaves-tower.log` for Tower service
  - `retrowaves-station.log` for Station service
  - `retrowaves-dj.log` for DJ engine (if separated)
  - etc.
- Use system log rotation mechanisms (e.g., `logrotate` on Linux)
- Rotate logs based on size and/or time (e.g., daily rotation, 10MB max size)
- Retain a configurable number of rotated log files (e.g., keep last 7 days or last 10 files)
- Compress old log files to save disk space
- Ensure log files have appropriate permissions (readable by `retrowaves` user/group)

**Benefits:**
- Easier debugging and troubleshooting
- Prevents log files from growing unbounded
- Standardized log locations across all components
- Better integration with system monitoring tools

---

## 📡 Broadcast-Grade Features

### Song Crossfading Logic

Fade-out current → fade-in next. DJ intros duck music automatically.

### ReplayGain / LUFS Normalization

Normalize loudness across:
- songs
- intros/outros
- DJ talk segments

### "Now Playing" Metadata

Add:
- Artist
- Title
- Album
- Year
- Artwork (if drives a UI)

Push via:
- Icecast metadata
- Websocket
- REST endpoint

### Emergency Alert / Override Mode

Trigger an emergency mode that:
- stops normal rotation
- plays emergency audio sequence
- sends alerts to clients

### Icecast/Shoutcast Compatibility

**Why:** If a Retrowaves station instance should broadcast publicly and support infinite listeners.

**Features:**
- Multiple mountpoints
- Listener stats
- Artist/song metadata
- ReplayGain or normalization per Icecast spec
- DJ metadata updates ("Now playing…")

### HLS Output (Apple HTTP Live Streaming)

**Why:** If browser playback or mobile app playback is needed.

**Benefits:**
- Rewind
- Seek
- Buffering
- Adaptive bitrate
- CDN-friendly

This is enterprise-grade streaming, optional.

### Redundant Output Formats

Simultaneously produce:
- MP3 stream
- AAC stream
- HLS segments

Core engine remains unchanged; outputs become modular.

### Local Recording / "Aircheck Mode"

Record a rolling 24-hour version of the station:
- For audits
- DJ coaching
- Troubleshooting
- Fun playback

---

## ⚙️ Operational Enhancements

### Web-Based Control Panel

For:
- reviewing logs
- playlist history
- skipping songs
- forcing a legal ID
- DJ persona configuration

### "Debug Stream" Mode

Mirror the main stream to:
- local WAV
- GUI visualizer
- waveform display
- detailed timing logs

For testing timing drift and DJ behavior.

### Persistent Analytics Tracking

Track:
- songs played per hour
- talk time per day
- legal ID compliance
- song recurrence windows

Useful for tuning the DJ engine.

### Radio Station API (HTTP/JSON)

Provide:
- `/now_playing`
- `/next_up`
- `/history`
- `/listeners`
- `/skip`
- `/trigger_id`

Could allow remote control via phone app.

### Intelligent Media Library Self-Organization

**Future Goal:** Allow Retrowaves to gradually self-organize all intros/outros/IDs/talk files into a clean directory structure without requiring manual work.

**Current Status:**
- We continue using Phase A filename-driven intros/outros exactly as they are.

**Desired Future Behavior:**
- DJEngine automatically extracts base song name from intros/outros
- Detects generic vs per-song assets
- Creates ticklers for safe migration
- Moves files into structured directories during THINK windows
- Maintains backward compatibility
- Zero downtime, zero manual labor

**Implementation Notes:**
- This will be captured in the wishlist, and we will revisit after the core playout (audio + HTTP streaming + THINK/DO) is proven stable.
- Migration should happen incrementally during THINK windows (non-blocking)
- Files should be moved atomically with fallback to original location if needed
- DJ should maintain a mapping of old paths to new paths during transition

**Outro Spelling Normalization:**
- **Canonical name:** `_outro` (one "t")
- **Historical compatibility:** Files on disk may have `_outtro` (two "t"s) due to historical typos
- **Phase 9 Asset Discovery:** Accepts both patterns:
  - `*_outro*.mp3` (canonical)
  - `*_outtro*.mp3` (historical typo)
- **Internal normalization:** All `AudioEvent.type="outro"` normalize to the 1-T spelling regardless of filename
- **Future Cleanup:** When the media library self-organization feature runs, the system will:
  - Detect any `*_outtro*.mp3` files
  - Rename them to the canonical form `*_outro*.mp3`
  - Move them into the standardized directory structure
  - Log: `Renamed Boogie_Woogie_Santa_Claus_outtro.mp3 → Boogie_Woogie_Santa_Claus_outro.mp3`

### Multi-Station Platform Architecture

**Future Goal:** Enable running multiple radio stations simultaneously from a single Retrowaves codebase, where "Appalachia Radio" becomes one output stream instance among many.

**Current Status:**
- Retrowaves runs as a single station instance
- All configuration, state, and media libraries are tied to one station

**Desired Future Behavior:**
- Station instances are independently configurable
- Each station has its own:
  - Media library (songs, intros, outros, IDs)
  - DJ engine with independent state
  - Rotation manager with separate history
  - Output streams (HTTP endpoints on different ports)
  - Configuration files and state persistence
- Ability to start/stop individual stations without affecting others
- Shared codebase, isolated station data
- Station-specific environment variables or config files

**Implementation Notes:**
- This is a major architectural refactoring that would come after core stability
- Would require:
  - Station abstraction layer (StationManager or StationFactory)
  - Isolated state directories per station
  - Port/endpoint management for multiple HTTP streams
  - Configuration management for multi-station scenarios
  - Resource isolation (memory, CPU per station)
- Backward compatibility: single-station mode should still work
- Could enable scenarios like:
  - Running multiple genre stations (Country, Jazz, Rock) simultaneously
  - Test/production station instances
  - Regional variations of the same station

---

## 🎨 User Experience & Monitoring

### Web Player for LAN Browsing

Simple web interface:
- Play button
- Now playing
- History
- DJ avatar

No need for Icecast or HLS unless you want to reach phones.

### Real-Time Logs Dashboard

Display:
- THINK/DO transitions
- Intent details
- Rotation weights
- audio timing
- stream throughput

### Discord or Slack Integration

Send alerts:
- "Station restarted"
- "Silence detected"
- "Rotation error"
- "Song repeated too soon"

---

## 🤖 AI & Advanced Features

### ElevenLabs Integration (Full TTS)

**Future Goal:** Enable the DJ to generate intros/outros/talk/break content using ElevenLabs voices.

**Possible Features:**
- Generate dynamic talk segments ("That was Fleetwood Mac… here's the weather")
- Personalized intros/outros for specific songs
- Time-based greetings ("Good morning Appalachia")
- Emergency or breaking-news announcements
- On-demand filler content via ticklers

**Constraints:**
- NEVER generated during DO
- Only generated during THINK via ticklers
- Must be cached MP3 before use

### Emotion/Mood Adaptive Voice

*(Not required for core operation)*

DJ voice tone adapts to:
- time of day
- schedule blocks
- music genre changes
- audience vibe (if analytics are added)

### Local Voice Model / Offline TTS

Eliminate dependency on ElevenLabs entirely.

Use:
- Coqui TTS
- Piper
- VITS

Offline operation, zero API cost.

### More Advanced Cadence Logic

Future DJ behaviors:
- Mood arcs (morning energy vs late night calm)
- Genre pairing and thematic blocks
- "Story mode" breaks
- Concert previews
- "Remember this band?" trivia inserts

### Smart Legal ID System

Legal ID rules:
- must play top of hour
- must play exactly N times per hour
- must delay if song pushes into the top-of-hour slot
- can merge with outros or intros

### Scheduled & Scripted Segments

Examples:
- Daily weather
- Hourly headline
- Artist spotlight
- "This day in history"
- Local events
- Pre-scripted monologues

Tickler-based generation.

### Ad Engine (Optional)

Internal ad scheduler for:
- promos
- show liners
- repeating ad carts
- live reads (AI)
- local sponsorships

---

## 🌟 Stretch Goals (Fun / Experimental)

### AI "Call-In" Show

Simulated callers and DJ responses.

### AI Song Facts Generator

Pulls facts and band trivia automatically.

### Multi-DJ Personalities

- Morning DJ
- Afternoon DJ
- Overnight DJ

Each with different intros/outros.

### "Retro Mode" (1980s Radio Filter)

Vinyl crackle, tape hiss, jingles, station power-up sequence.

Just for fun.

---

## ✅ Completed Work

### Pre-Fill Stage for Tower Buffer

**Status:** ✅ **COMPLETED** - Production-ready implementation

**Implementation Date:** 2024-12-11

#### Purpose

Implement a pre-fill stage that builds up Tower's PCM buffer before starting normal adaptive pacing to prevent dropped frames and stuttering when Tower comes online or buffer is empty.

#### What Was Implemented

✅ **Pre-Fill Stage in PlayoutEngine** (`station/broadcast_core/playout_engine.py`):
- `_get_tower_buffer_status()`: Queries `/tower/buffer` endpoint via TowerControlClient or HTTP client
- `_get_buffer_ratio()`: Calculates buffer fill ratio (0.0-1.0) from buffer status
- `_run_prefill_if_needed()`: Implements pre-fill per Contract C8:
  - Checks buffer ratio via `/tower/buffer` endpoint
  - Enters pre-fill if ratio < target (default 0.5)
  - Decodes and sends frames as fast as possible (no Clock A sleep)
  - Monitors buffer fill level periodically (default every 100ms)
  - Exits when buffer reaches target or timeout (default 5s)
  - Frame limit safety (~470 frames ≈ 10 seconds) to prevent consuming entire segment
  - Does NOT modify Clock A timeline or segment timing
  - Respects shutdown flags and error handling

✅ **Pre-Fill Integration**:
- Called in `_play_audio_segment()` before normal decode loop
- If pre-fill consumes decoder, it is recreated for normal loop
- Smooth transition to PID controller pacing after pre-fill
- Configurable via environment variables:
  - `PREFILL_ENABLED` (default: `true`)
  - `PREFILL_TARGET_RATIO` (default: `0.5`, clamped to 0.1-0.9)
  - `PREFILL_TIMEOUT_SEC` (default: `5.0`, clamped to 1-30s)
  - `PREFILL_POLL_INTERVAL_SEC` (default: `0.1`, clamped to 50ms-1s)

✅ **Safety Features**:
- Frame limit prevents consuming entire segment in pre-fill
- Timeout prevents infinite pre-fill
- Error logging with spam prevention (10% sampling)
- Config parameter validation with bounds checking

✅ **Contract Compliance**:
- C8 Pre-Fill Stage: All contract requirements met
- All 6 Pre-Fill contract tests passing
- All 5 Two-Clock Model enforcement tests passing
- All 4 PID + Pre-Fill transition tests passing
- Architectural invariants preserved:
  - Clock A timeline uninterrupted
  - Segment timing wall-clock based
  - PCM writes remain non-blocking

**Files Modified:**
- `station/broadcast_core/playout_engine.py` - Pre-fill implementation (+172 lines)
- `station/tests/contracts/test_station_tower_pcm_bridge_contract.py` - Pre-fill tests (11 new tests)
- `station/tests/contracts/test_playout_engine_contract.py` - PID + Pre-fill transition tests (4 new tests)

**Documentation:**
- Contract: `station/docs/contracts/STATION_TOWER_PCM_BRIDGE_CONTRACT.md` (C8)
- Contract: `tower/docs/contracts/NEW_TOWER_RUNTIME_CONTRACT.md` (T-BUF6)
- All contract tests passing

---

### Advanced Buffer Management with PID Controller

**Status:** ✅ **COMPLETED** - Production-ready implementation

**Implementation Date:** 2024-12-11

#### Purpose

Implement a full PID (Proportional-Integral-Derivative) controller for adaptive Clock A decode pacing based on Tower buffer status, replacing the simple 3-zone controller with continuous rate adjustment.

#### What Was Implemented

✅ **BufferPIDController Class** (`station/broadcast_core/buffer_pid_controller.py`):
- Full PID algorithm with P, I, and D terms
- Proportional (P) term: Responds to current buffer fill deviation from target
- Integral (I) term: Accumulates error over time to eliminate steady-state offset (with windup prevention)
- Derivative (D) term: Predicts future error based on rate of change (with dt edge case handling)
- Thread-safe state management with RLock
- Non-blocking `/tower/buffer` polling with timeout support
- Last-known buffer status fallback
- Integral reset on Tower unavailability
- Startup defaults (integral_sum=0, previous_error=0, base_frame_duration sleep)
- Configurable PID coefficients (Kp, Ki, Kd), target ratio, safety limits
- Observability: `get_state()` and `get_metrics()` methods

✅ **PID Integration with PlayoutEngine**:
- PID controller adjusts Clock A pacing (does not replace it)
- Clock A base pacing (`next_frame_time - now`) is preserved
- PID adjustment is added to Clock A sleep: `sleep = clock_a_sleep + pid_adjustment`
- Periodic buffer status polling during decode loop (non-blocking)
- Maintains all architectural invariants:
  - Clock A timeline advances for segment timing
  - Socket writes remain non-blocking and immediate
  - Segment timing remains wall-clock based

✅ **Control Direction (Correct Sign)**:
- When buffer is LOW (positive error): Positive adjustment → More sleep → Slower decode → Tower catches up
- When buffer is HIGH (negative error): Negative adjustment → Less sleep → Faster decode → Tower drains
- Matches PE6 contract specification

✅ **Edge Case Handling**:
- Small dt (< 1ms): D-term disabled to prevent explosion
- Large dt: D-term calculated but clamped
- dt = 0: D-term disabled, no division by zero
- Buffer ratio extremes (0.0, 1.0): Handled without oscillations
- Startup transients: No derivative noise on first cycle
- Tower unavailability: Falls back to Clock A base pacing, resets integral

✅ **Configuration**:
- `PID_ENABLED` environment variable (default: `true`)
- `TOWER_HOST` and `TOWER_PORT` for Tower connection
- PID coefficients configurable via constructor (defaults per PE6.3)

✅ **Contract Compliance**:
- PE6.1 through PE6.8: All contract requirements met
- All 41 PE6 contract tests passing
- Two-clock architecture preserved
- Non-interference with segment timing, DJ THINK/DO, PCM writes

**Files Created/Modified:**
- `station/broadcast_core/buffer_pid_controller.py` - Full PID controller implementation (383 lines)
- `station/broadcast_core/playout_engine.py` - PID integration with Clock A pacing
- `station/tests/contracts/test_playout_engine_contract_pe6.py` - Comprehensive contract tests (41 tests)

**Documentation:**
- Contract: `station/docs/contracts/PLAYOUT_ENGINE_CONTRACT.md` (PE6)
- All contract tests passing

---

### MP3 Fallback Support (Looping Standby Audio)

**Status:** ✅ **COMPLETED** - Production-ready implementation

**Implementation Date:** 2024-12-11

#### Purpose

Enable Tower to play a looping MP3/WAV file (e.g., "Please Stand By") as fallback audio when Station is offline, providing a professional standby experience instead of a test tone.

#### What Was Implemented

✅ **FileSource Class** (`tower/fallback/file_source.py`):
- Pre-decodes entire MP3/WAV file to PCM at startup (contract-compliant)
- Zero-latency `next_frame()` - pure array indexing, no I/O, no locks
- Seamless looping with startup crossfade to eliminate pops/clicks
- Supports files up to 10 minutes (configurable via `max_duration_sec`)
- Automatic format detection (MP3, WAV, etc.) via FFmpeg
- Memory-efficient: pre-decoded frames stored in memory

✅ **Fallback Priority Sequence:**
1. **Program PCM** (live audio from Station)
2. **Grace Period Silence** (1.5 seconds default)
3. **MP3 File Fallback** (if `TOWER_SILENCE_MP3_PATH` is configured)
4. **440Hz Tone** (synthetic sine wave)
5. **Silence** (last resort)

✅ **Environment Variable Support:**
- `TOWER_SILENCE_MP3_PATH` - Path to MP3/WAV file for fallback
- Automatically loaded from `tower/tower.env` or `.env` file
- Falls back to tone if path is unset or file is invalid

✅ **Seamless Looping:**
- Startup crossfade (default 2048 samples ≈ 42.6ms) blends end with beginning
- Eliminates audible pops/clicks at loop boundaries
- Zero-latency looping via simple array index wrapping

✅ **Contract Compliance:**
- FP2.2: Zero-latency `next_frame()` (no I/O, no locks, no subprocess calls)
- FP3.1: File-based fallback with seamless looping
- FP6.2: Continuous looping without audible seams
- All tests passing

✅ **Integration:**
- `FallbackGenerator` automatically uses FileSource when `TOWER_SILENCE_MP3_PATH` is set
- Graceful fallback to tone if file decoding fails
- No mixing of sources - clean priority-based selection

**Files Created/Modified:**
- `tower/fallback/file_source.py` - FileSource implementation
- `tower/fallback/generator.py` - Integration with FallbackGenerator
- `tower/tests/contracts/test_new_fallback_provider_contract.py` - Comprehensive tests
- `run_tower_dev.py` - Added environment variable loading
- `tower/tower.env.example` - Added `TOWER_SILENCE_MP3_PATH` example

**Documentation:**
- Contract: `tower/docs/contracts/NEW_FALLBACK_PROVIDER_CONTRACT.md` (FP3.1, FP6.2)
- All contract tests passing

---

### Control Channel & Event Side-Channel

**Status:** ✅ **COMPLETED** - Production-ready implementation

**Implementation Date:** 2024-12-08

#### Purpose

Create a second output stream (parallel to audio) delivering real-time events and metadata about what the station is doing.

This channel allows **ANY intelligent client** — OBS, a web UI, a Discord bot, a mobile app, a dashboard, etc. — to react to the station without Retrowaves being tied to any one platform.

**No assumptions. No coupling. Pure abstraction.**

#### What This Side-Channel Emits

The event stream delivers messages like:

**Playback Lifecycle:**
- `segment_started`: `{ type: "song", path: "...", title: "...", artist: "..." }`
- `segment_progress`: `{ segment_id: "...", elapsed_time: 123.45, expected_duration: 180.0, progress_percent: 68.6 }` (emitted at least once per second)
- `segment_finished`: `{ type: "intro", duration: 2.5 }`

**DJ Behavior Events:**
- `dj_think_started`: `{ timestamp: 1234567890.0 }`
- `dj_think_completed`: `{ timestamp: 1234567891.5, think_duration_ms: 1500.0, dj_intent: {...} }`

**Buffer Health Events:**
- `station_underflow`: `{ timestamp: 1234567890.0, buffer_depth: 0 }`
- `station_overflow`: `{ timestamp: 1234567890.0, frames_dropped: 42 }`

**Clock Drift Events:**
- `decode_clock_skew`: `{ timestamp: 1234567890.0, drift_ms: 45.2 }` (if drift compensation enabled)

#### How Clients Subscribe

**Current Implementation:**
- **WebSocket feed** - Primary transport for real-time event streaming
  - `/tower/events` - Continuous WebSocket stream of events as they occur
  - Continuous JSON events
  - Perfect for OBS, web UIs, dashboards
  - Tower sends only; clients may send ping frames
  - Each message contains exactly one event as a complete JSON object
  - Messages are text-format JSON (not binary)
  - **Note:** `/tower/events/recent` endpoint was removed per contract - events are not stored, so recent event catch-up is not available

#### What This Enables for OBS Without Hard Dependencies

OBS would simply:

1. Connect to WebSocket endpoint `ws://tower:8005/tower/events`
2. When it sees:
   - `{ "event_type": "station_stopping" }` → Switch to "Please Stand By"
   - `{ "event_type": "segment_started", "type": "song" }` → Switch to your main scene

This keeps Retrowaves:
- **pure**
- **platform-independent**
- **deterministic**
- **not tied to OBS's web socket API**
- **safe from breaking changes in OBS**

#### Technical Benefits

- **Zero client assumptions:** Station doesn't need to know anything about OBS.
- **Non-blocking:** THINK/DO logic remains untouched.
- **Scalable:** Many clients can listen — OBS, web dashboards, scripts, plugins.
- **Future-proof:** Works with:
  - OBS
  - Streamlabs
  - Mobile apps
  - Smart home dashboards
  - Web UIs
  - Discord bots
- **Extremely easy to test:** You can connect to the event stream with:
  ```bash
  # Connect to WebSocket endpoint
  wscat -c ws://localhost:8005/tower/events
  ```

#### Event Ingestion (Station → Tower)

Station sends heartbeat events to Tower via HTTP POST to `/tower/events/ingest`:

- Events are one-way (Station→Tower)
- Tower validates and stores events in a bounded buffer
- Events are immediately broadcast to all connected WebSocket clients
- Tower never sends timing information back to Station
- Events are purely observational

**Accepted Event Types:**
- `segment_started`
- `segment_progress`
- `segment_finished`
- `dj_think_started`
- `dj_think_completed`
- `decode_clock_skew` (if drift compensation enabled)
- `station_underflow`
- `station_overflow`

#### Implementation Summary

**What Was Implemented:**
- Tower event ingestion endpoint (`/tower/events/ingest`) via HTTP POST
- Tower event buffer with bounded, thread-safe storage (1000 event capacity)
- WebSocket event streaming endpoint (`/tower/events`) for real-time event delivery
- Station event emission: All required event types from contracts (PE4, DJ4, OS3)
- Non-blocking, purely observational event system
- Full contract compliance with all tests passing
- **Note:** Events are not stored for historical retrieval; they are delivered immediately to connected clients or dropped

**Event Types Implemented:**
- Segment lifecycle: `segment_started`, `segment_progress`, `segment_finished`
- DJ lifecycle: `dj_think_started`, `dj_think_completed`
- Buffer health: `station_underflow`, `station_overflow`
- Optional: `decode_clock_skew` (only if drift compensation enabled)

**Contract Compliance:**
- ✅ Tower: T-EVENTS (reception, storage, validation)
- ✅ Tower: T-EXPOSE (WebSocket endpoints, fanout, immediate flush)
- ✅ Station: PE4 (PlayoutEngine heartbeat events)
- ✅ Station: DJ4 (DJEngine THINK lifecycle events)
- ✅ Station: OS3 (OutputSink buffer health events)

**Documentation:**
- Contract: `tower/docs/contracts/NEW_TOWER_RUNTIME_CONTRACT.md` (Sections Y & Z)
- Implementation: `tower/http/server.py`, `tower/http/websocket.py`, `tower/http/event_buffer.py`
- Station Integration: `station/outputs/tower_control.py`, `station/broadcast_core/playout_engine.py`, `station/dj_logic/dj_engine.py`, `station/outputs/tower_pcm_sink.py`

**Architectural Note:**

This is the correct architectural direction.

You maintain:
- **pure audio stream** → radio's core
- **stateless metadata/event feed** → everything else

This is **EXACTLY** how professional broadcast systems (Zetta, ENCO, WideOrbit) operate when interfacing with companion systems.

---

## Document Notes

This document is a sandbox of ideas — future enhancements that can extend Retrowaves beyond its core architecture.

Nothing here changes the THINK/DO design or the canonical architecture.

This wishlist is:
- **optional**
- **unbounded**
- **creativity-focused**
- **non-binding**

It exists so the architecture doc stays clean while your system continues evolving naturally.
