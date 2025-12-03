# 📘 Appalachia Radio — Future Enhancements & Expansion Wishlist

This document is a non-binding, forward-looking companion to the canonical Unified Architecture. It defines potential future enhancements, integrations, and features that may be added to Appalachia Radio after the core THINK/DO system and real-time audio streaming are complete.

**This is NOT implementation guidance.** It is a design sandbox for ideas worth exploring later.

---

## 1. Purpose of This Document

- Capture future ideas without polluting the core Architecture spec
- Collect expansion concepts, integrations, and potential capabilities
- Serve as a reference for future phases
- Keep the Architecture document clean, stable, and focused

---

## 2. Category Index

This wishlist is organized into these broad categories:

- **Audio Generation & AI Integration**
- **Streaming & Broadcasting Enhancements**
- **DJ Intelligence & Content Logic**
- **Broadcast Features & Radio Polish**
- **Operational Features & Tooling** (including media library self-organization)
- **User Experience & Monitoring**
- **Metadata & Event Side-Channel**

Each category contains optional enhancements.

---

## 3. Audio Generation & AI Integration

### 3.1 ElevenLabs Integration (Full TTS)

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

### 3.2 Emotion/Mood Adaptive Voice

*(Not required for core operation)*

DJ voice tone adapts to:
- time of day
- schedule blocks
- music genre changes
- audience vibe (if analytics are added)

### 3.3 Local Voice Model / Offline TTS

Eliminate dependency on ElevenLabs entirely.

Use:
- Coqui TTS
- Piper
- VITS

Offline operation, zero API cost.

---

## 4. Streaming & Broadcasting Enhancements

### 4.1 Icecast/Shoutcast Compatibility

**Why:** If Appalachia Radio should broadcast publicly and support infinite listeners.

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

**Future Goal:** Allow Appalachia Radio to gradually self-organize all intros/outros/IDs/talk files into a clean directory structure without requiring manual work.

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

### 7.6 Multi-Station Platform Architecture

**Future Goal:** Rename the entire system to a platform name, where "Appalachia Radio" becomes one output stream instance. Enable running multiple radio stations simultaneously from a single codebase.

**Current Status:**
- System is named "Appalachia Radio" and runs as a single station instance
- All configuration, state, and media libraries are tied to one station

**Desired Future Behavior:**
- Platform-level naming (e.g., "Radio Automation Platform" or similar)
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

### 7.7 Graceful Shutdown with Offline Announcement

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
  - Offline announcement plays (e.g., "Appalachia Radio is going offline for maintenance. We'll be back soon!")
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

## 9. Stretch Goals (Fun / Experimental)

### 9.1 AI "Call-In" Show

Simulated callers and DJ responses.

### 9.2 AI Song Facts Generator

Pulls facts and band trivia automatically.

### 9.3 Multi-DJ Personalities

- Morning DJ
- Afternoon DJ
- Overnight DJ

Each with different intros/outros.

### 9.4 "Retro Mode" (1980s Radio Filter)

Vinyl crackle, tape hiss, jingles, station power-up sequence.

Just for fun.

---

## 10. Metadata + Event Side-Channel (Client-Agnostic Signaling Layer)

### 10.1 Purpose

Create a second output stream (parallel to audio) delivering real-time events and metadata about what the station is doing.

This channel would allow **ANY intelligent client** — OBS, a web UI, a Discord bot, a mobile app, a dashboard, etc. — to react to the station without Appalachia Radio being tied to any one platform.

**No assumptions. No coupling. Pure abstraction.**

### 10.2 What This Side-Channel Emits

The event stream might deliver messages like:

#### Playback Lifecycle

- `segment_started`: `{ type: "song", path: "...", title: "...", artist: "..." }`
- `segment_finished`: `{ type: "intro", duration: 2.5 }`
- `up_next`: `song_003.mp3`
- `dj_intent_committed`: `{ outro: true, ids: 1, intro: true, song: ... }`

#### Station Lifecycle

- `station_starting`
- `station_running`
- `station_stopping`
- `station_idle`
- `restarting`

Great for telling OBS: *"Switch to the standby scene until audio resumes."*

#### DJ Behavior Events

- `dj_talk_planned`
- `dj_id_triggered`
- `dj_outro_selected`
- `dj_intro_selected`
- `dj_ticklers_consumed`

#### Rotation & Music Metadata

- Song metadata (artist, album, year, length)
- Rotation weight info
- Recent plays
- Holiday weighting sample

OBS could show "Now Playing" from this data.

### 10.3 How Clients Subscribe (Client-Agnostic)

**Potential transport options (choose 1 or several):**

#### 1. WebSocket feed

- Continuous JSON events
- Perfect for OBS, web UIs, dashboards
- Bi-directional if needed (but not required)

#### 2. Server-Sent Events (SSE)

- One-way event stream
- Super lightweight
- Perfect for LAN dashboards/Web UIs
- No external deps

#### 3. JSON-over-HTTP polling endpoint

- Simple fallback
- `/now_playing`
- `/dj_intent`
- `/state`

#### 4. Optional Icecast Metadata Integration

- If you choose Icecast later, we can push "Now Playing" updates
- That's optional and separate from the audio playout

### 10.4 What This Enables for OBS Without Hard Dependencies

OBS would simply:

1. Listen to the side-channel (WebSocket or SSE)
2. When it sees:
   - `{ "event": "station_stopping" }` → Switch to "Please Stand By"
   - `{ "event": "segment_started", "type": "song" }` → Switch to your main scene

This keeps Appalachia Radio:
- **pure**
- **platform-independent**
- **deterministic**
- **not tied to OBS's web socket API**
- **safe from breaking changes in OBS**

### 10.5 Technical Benefits

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
- **Extremely easy to test:** You can watch the event stream with:
  ```bash
  curl http://localhost:8000/events
  ```

### 10.6 Future Extensions (Optional)

- Add "timeline markers" so clients can visually align audio and events
- Add animated avatars reacting to intros/outros
- Build a full HTML5 "Radio Control Room" UI
- Add analytics on event stream consumption
- Add "DJ heartbeats" for health monitoring
- Build a REST API for controlling low-level station features
- Add a "visualizer plugin" that reacts to PCM amplitude values coming from the mixer

### 10.7 Architectural Direction

**This is the correct architectural direction.**

You maintain:
- **pure audio stream** → radio's core
- **stateless metadata/event feed** → everything else

This is **EXACTLY** how professional broadcast systems (Zetta, ENCO, WideOrbit) operate when interfacing with companion systems.

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
- `/mnt/media/appalachia-radio/system/please-stand-by.mp3`

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

## 12. Summary

This document is a sandbox of ideas — future enhancements that can extend Appalachia Radio beyond its core architecture.

Nothing here changes the THINK/DO design or the canonical architecture.

This wishlist is:
- **optional**
- **unbounded**
- **creativity-focused**
- **non-binding**

It exists so the architecture doc stays clean while your system continues evolving naturally.
