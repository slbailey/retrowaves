# 📘 Retrowaves — Future Enhancements & Expansion Wishlist

This document is a non-binding, forward-looking companion to the canonical Unified Architecture. It defines potential future enhancements, integrations, and features that may be added to Retrowaves after the core THINK/DO system and real-time audio streaming are complete.

**Note:** Retrowaves is the software platform. Appalachia Radio is the first station instance that uses this software.

**This is NOT implementation guidance.** It is a design sandbox for ideas worth exploring later.

---

## 1. Purpose of This Document

- Capture future ideas without polluting the core Architecture spec
- Collect expansion concepts, integrations, and potential capabilities
- Serve as a reference for future phases
- Keep the Architecture document clean, stable, and focused

---

## 2. Category Index (Organized by Priority)

This wishlist is organized by priority and category:

**✅ Completed:**
- **Control Channel & Event Side-Channel** (Section 3) - ✅ FULLY IMPLEMENTED

**Medium Priority:**
- **Streaming & Broadcasting Enhancements** (Section 4)
- **DJ Intelligence & Content Logic** (Section 5)
- **Broadcast Features & Radio Polish** (Section 6)
- **Continuous HTTP Streaming Server** (Section 11)

**Lower Priority / Nice to Have:**
- **Operational Features & Tooling** (Section 7)
- **User Experience & Monitoring** (Section 8)
- **Audio Generation & AI Integration** (Section 9)
- **Stretch Goals** (Section 10)

Each category contains optional enhancements.

---

## 3. Control Channel & Event Side-Channel

**Status:** ✅ **COMPLETED** - See Section 12: Completed Enhancements

This enhancement has been fully implemented and is production-ready. All contract requirements are met, all tests pass, and the system is operational.

For complete documentation and implementation details, see **Section 12: Completed Enhancements** → **Control Channel & Event Side-Channel**.

---

## 4. Streaming & Broadcasting Enhancements

### 4.1 Icecast/Shoutcast Compatibility

**Why:** If a Retrowaves station instance should broadcast publicly and support infinite listeners.

**Features:**
- Multiple mountpoints
- Listener stats
- Artist/song metadata
- ReplayGain or normalization per Icecast spec
- DJ metadata updates ("Now playing…")

### 4.2 HLS Output (Apple HTTP Live Streaming)

**Why:** If browser playback or mobile app playback is needed.

**Benefits:**
- Rewind
- Seek
- Buffering
- Adaptive bitrate
- CDN-friendly

This is enterprise-grade streaming, optional.

### 4.3 Redundant Output Formats

Simultaneously produce:
- MP3 stream
- AAC stream
- HLS segments

Core engine remains unchanged; outputs become modular.

### 4.4 Local Recording / "Aircheck Mode"

Record a rolling 24-hour version of the station:
- For audits
- DJ coaching
- Troubleshooting
- Fun playback

### 4.5 Advanced Buffer Management with PID Controller

**Future Goal:** Replace the current simple 3-zone buffer controller with a proper PID (Proportional-Integral-Derivative) feedback loop for smoother, more precise rate control.

**Current Status:**
- Station uses a simple 3-zone controller (low/normal/high) with fixed sleep times
- Buffer polling happens every 500ms
- Works but can be improved for better stability

**Desired Future Behavior:**
- Implement a full PID controller for continuous rate adjustment
- **Proportional (P) term:** Responds to current buffer fill deviation from target
- **Integral (I) term:** Accumulates error over time to eliminate steady-state offset
- **Derivative (D) term:** Predicts future error based on rate of change
- Smooth, continuous rate adjustment without discrete zone transitions
- Better handling of varying network conditions and Tower consumption rates
- Tunable PID coefficients for different buffer sizes and network conditions

**Benefits:**
- Eliminates stuttering from discrete zone transitions
- More responsive to rapid buffer changes
- Better long-term stability (I term prevents drift)
- Industry-standard approach used in streaming media encoders

**Implementation Notes:**
- PID controller would replace the current zone-based logic in `PlayoutEngine._play_audio_segment()`
- Coefficients (Kp, Ki, Kd) should be configurable
- May need different tuning for different buffer capacities
- Should maintain safety limits (min/max sleep times)

### 4.6 Pre-Fill Stage for Tower Buffer

**Future Goal:** Implement a pre-fill stage that builds up the Tower ring buffer before starting normal playback to prevent dropped frames when Tower comes online.

**Current Status:**
- Station starts sending frames immediately when playback begins
- If Tower buffer is empty (0/50), frames are sent at normal rate
- This can cause stuttering and dropped frames (e.g., 7940 dropped frames observed)
- No pre-fill phase exists

**Desired Future Behavior:**
- Before starting normal playback, check Tower buffer fill level
- If buffer is below target (e.g., < 50% capacity), enter pre-fill mode
- During pre-fill:
  - Decode and send frames as fast as possible (no sleep)
  - Monitor buffer fill level periodically
  - Continue until buffer reaches target fill (e.g., 50% = 25/50 frames)
- Once target is reached, transition to normal adaptive pacing
- Pre-fill should happen automatically when:
  - Station starts up
  - Tower restarts/reconnects
  - Buffer drops below threshold during playback

**Benefits:**
- Prevents initial stuttering when Tower comes online
- Eliminates dropped frames during startup
- Ensures smooth playback from the first frame
- Better user experience with no audio gaps

**Implementation Notes:**
- Pre-fill should be integrated into `PlayoutEngine._play_audio_segment()`
- Should work seamlessly with the adaptive pacing system
- May need to coordinate with Tower's buffer status endpoint
- Should have a timeout/safety limit to prevent infinite pre-fill
- Could be combined with PID controller for smooth transition

---

## 5. DJ Intelligence & Content Logic

### 5.1 More Advanced Cadence Logic

Future DJ behaviors:
- Mood arcs (morning energy vs late night calm)
- Genre pairing and thematic blocks
- "Story mode" breaks
- Concert previews
- "Remember this band?" trivia inserts

### 5.2 Smart Legal ID System

Legal ID rules:
- must play top of hour
- must play exactly N times per hour
- must delay if song pushes into the top-of-hour slot
- can merge with outros or intros

### 5.3 Scheduled & Scripted Segments

Examples:
- Daily weather
- Hourly headline
- Artist spotlight
- "This day in history"
- Local events
- Pre-scripted monologues

Tickler-based generation.

### 5.4 Ad Engine (Optional)

Internal ad scheduler for:
- promos
- show liners
- repeating ad carts
- live reads (AI)
- local sponsorships

---

## 6. Broadcast Features & Radio Polish

### 6.1 Song Crossfading Logic

Fade-out current → fade-in next. DJ intros duck music automatically.

### 6.2 ReplayGain / LUFS Normalization

Normalize loudness across:
- songs
- intros/outros
- DJ talk segments

### 6.3 "Now Playing" Metadata

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

### 6.4 Emergency Alert / Override Mode

Trigger an emergency mode that:
- stops normal rotation
- plays emergency audio sequence
- sends alerts to clients

---

## 7. Operational Features & Tooling

### 7.1 Web-Based Control Panel

For:
- reviewing logs
- playlist history
- skipping songs
- forcing a legal ID
- DJ persona configuration

### 7.2 "Debug Stream" Mode

Mirror the main stream to:
- local WAV
- GUI visualizer
- waveform display
- detailed timing logs

For testing timing drift and DJ behavior.

### 7.3 Persistent Analytics Tracking

Track:
- songs played per hour
- talk time per day
- legal ID compliance
- song recurrence windows

Useful for tuning the DJ engine.

### 7.4 Radio Station API (HTTP/JSON)

Provide:
- `/now_playing`
- `/next_up`
- `/history`
- `/listeners`
- `/skip`
- `/trigger_id`

Could allow remote control via phone app.

### 7.5 Intelligent Media Library Self-Organization

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

### 7.6 Centralized Logging with Rotation

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

### 7.7 Multi-Station Platform Architecture

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

### 7.8 Graceful Shutdown with Offline Announcement

**Future Goal:** When shutting down the station, allow the current song to finish playing before stopping. Optionally have the DJ announce that the station is going offline.

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

## 8. User Experience & Monitoring

### 8.1 Web Player for LAN Browsing

Simple web interface:
- Play button
- Now playing
- History
- DJ avatar

No need for Icecast or HLS unless you want to reach phones.

### 8.2 Real-Time Logs Dashboard

Display:
- THINK/DO transitions
- Intent details
- Rotation weights
- audio timing
- stream throughput

### 8.3 Discord or Slack Integration

Send alerts:
- "Station restarted"
- "Silence detected"
- "Rotation error"
- "Song repeated too soon"

---

## 9. Audio Generation & AI Integration

### 9.1 ElevenLabs Integration (Full TTS)

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

### 9.2 Emotion/Mood Adaptive Voice

*(Not required for core operation)*

DJ voice tone adapts to:
- time of day
- schedule blocks
- music genre changes
- audience vibe (if analytics are added)

### 9.3 Local Voice Model / Offline TTS

Eliminate dependency on ElevenLabs entirely.

Use:
- Coqui TTS
- Piper
- VITS

Offline operation, zero API cost.

---

## 10. Stretch Goals (Fun / Experimental)

### 10.1 AI "Call-In" Show

Simulated callers and DJ responses.

### 10.2 AI Song Facts Generator

Pulls facts and band trivia automatically.

### 10.3 Multi-DJ Personalities

- Morning DJ
- Afternoon DJ
- Overnight DJ

Each with different intros/outros.

### 10.4 "Retro Mode" (1980s Radio Filter)

Vinyl crackle, tape hiss, jingles, station power-up sequence.

Just for fun.

---

## 11. Continuous HTTP Streaming Server (24×7 Endpoint Availability)

### 11.1 Purpose

Ensure the HTTP audio endpoint is always available, even when:

- The radio station is restarting
- The playout engine is not currently producing audio
- A code reload is happening
- The DJ hasn't queued the first segment
- The system is stopped intentionally

The goal is:

- Clients (like VLC) NEVER see "connection refused" or "stream unavailable."
- Instead, the stream always connects and always outputs something.

### 11.2 Behavior Goals

This subsystem maintains a 24×7 listener port that:

🔸 **Always accepts connections**

Never refuses VLC, even if the engine is down.

🔸 **Always streams valid audio data**

Even if:
- DJEngine is offline
- RotationManager hasn't loaded
- PlayoutEngine is restarting
- Station is rebooting

🔸 **Provides fallback audio when live output is unavailable**

Examples:
- Silent PCM (pure silence frames)
- Test tone (440 Hz sine wave)
- Looping MP3 ("Please stand by while our code updates…")
- Static test pattern file

This mimics real broadcast systems that continue transmitting a carrier signal even during outages.

### 11.3 Why This Matters

Professional radio/TV stations never drop carrier.

If the automation crashes, you still get one of:
- A technical difficulties loop
- A standby slate
- A repeating announcement
- A continuous tone

It keeps the viewer/listener connected and prevents the platform (YouTube, VLC, etc.) from dropping the stream.

This becomes REALLY important when streaming to YouTube:

- If the connection dies for more than 30 seconds
- YouTube kills your live event
- Viewers get dropped
- You have to restart a brand-new stream

A 24/7 endpoint prevents this.

### 11.4 How It Integrates (Clean, Modular, Architecture-Safe)

This feature must NOT contaminate the core playout engine.

Instead, we introduce a new subsystem:

🔧 **ContinuousStreamServer**

Runs independently from the DJ/Playout pipeline.

Its job:
- Accept connections 24×7
- Stream whatever the audio engine currently provides
- If the engine is feeding PCM → encode → output
- If the engine stops → switch to fallback
- If the engine restarts → resume playout seamlessly

### 11.5 Fallback Audio Modes

You choose any of these modes:

**Mode A — Silent PCM**
- Easy
- Zero dependencies
- VLC stays connected
- YouTube stays up
- No artifacts

**Mode B — Looping MP3 file**

E.g.:
- `/mnt/media/appalachia-radio/system/please-stand-by.mp3` (station-specific path)

This gives a professional aesthetic.

**Mode C — Synthetic Test Tone**

440 Hz generated in real-time.

Reliable for debugging.

**Mode D — Custom Standby Playlist**

A short rotation of standby audio:
- promos
- DJ liners
- station IDs
- "We'll be right back"

### 11.6 State Transitions

ContinuousStreamServer reacts to events:

- **When playout is active**
  → Stream the real PCM frames generated by the PlayoutEngine.

- **When playout is inactive**
  → Switch to fallback instantly.

- **When playout starts again**
  → Switch back to live playout.

Seamless. No reconnects.

### 11.7 Technical Requirements

- **Decoupled from DJEngine / PlayoutEngine**
  - It should not block the THINK/DO loop.
  - Runs in its own thread
  - 24×7, independent of playout engine lifecycle.

- **Buffered**
  - So slow clients don't block the station.

- **Hot-swappable**
  - Audio source can change without dropping sockets.

- **HTTP keep-alive**
  - For VLC stability.

### 11.8 Why This Belongs in the Wishlist, Not the Architecture Document

Because:
- It is optional
- It does not modify THINK/DO
- It does not modify PlayoutEngine
- It does not modify DJIntent
- It is a separate Output System Enhancement

Architecture 3.x remains pure:
- DJ THINK/DO → playout → output sink

This Wishlist item adds:
- Continuous output wrapper around output sinks
- It's an extension, not a change.

### 11.9 Future Extensions

- **OBS Integration**
  - OBS listens to metadata events and automatically swaps to "Standby Scene" when:
    - `event: playout_engine_offline`

- **HLS Compatibility**
  - The 24×7 server could generate HLS "standby segments."

- **Icecast Relay**
  - Standby mode becomes a mount-fallback for Icecast.

---

## 12. Completed Enhancements

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
  - `/tower/events/recent` - WebSocket connection that sends recent events then closes
  - Continuous JSON events
  - Perfect for OBS, web UIs, dashboards
  - Tower sends only; clients may send ping frames
  - Each message contains exactly one event as a complete JSON object
  - Messages are text-format JSON (not binary)

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
- WebSocket recent events endpoint (`/tower/events/recent`) for initial event catch-up
- Station event emission: All required event types from contracts (PE4, DJ4, OS3)
- Non-blocking, purely observational event system
- Full contract compliance with all tests passing

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

## 13. Summary

This document is a sandbox of ideas — future enhancements that can extend Retrowaves beyond its core architecture.

Nothing here changes the THINK/DO design or the canonical architecture.

This wishlist is:
- **optional**
- **unbounded**
- **creativity-focused**
- **non-binding**

It exists so the architecture doc stays clean while your system continues evolving naturally.
