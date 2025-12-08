# Retrowaves — Unified System Architecture

A DJ-driven, event-timed, intent-based radio automation engine with real audio playout.

**Note:** Retrowaves is the software platform. Appalachia Radio is the first station instance that uses this software.

This is the canonical architecture document and supersedes all previous versions.

---

## 1. Executive Summary

The system uses a THINK/DO split with a DJ Intent model:
- THINK (Prep Window): while a segment is playing, the DJ decides the next break and selects concrete MP3 files.
- DO (Transition Window): when a segment finishes, the DJ pushes those pre-selected files to the playout queue with zero blocking.

It also provides full real-world audio integration:
- Real filesystem-backed media (songs and DJ assets) loaded at startup.
- FFmpeg-based decoding to PCM frames.
- A real-time mixer and output sinks (file or streaming via ffmpeg).
- Strict non-blocking guarantees maintained; all selection happens in THINK.

Result: A deterministic, operational radio automation system with realistic DJ behavior and real audio output.

---

## 2. Core Principles

### 2.1 The DJ Is the Brain
The DJ is the sole source of programming decisions:
- selects songs, intros, outros, station IDs
- schedules talk segments and manages pacing/cadence
- consumes/creates ticklers for future content
- applies personality and spacing rules

Decisions are made as concrete MP3 file paths during THINK, never during DO.

### 2.2 Playback Engine Uses Clock A (Decode Metronome)
The PlayoutEngine:
- decodes audio to frames, paces frame consumption using Clock A (decode metronome), mixes frames, sends frames to outputs
- uses Clock A to ensure songs play at real duration (e.g., 200-second MP3 takes 200 seconds)
- emits lifecycle events:
  - `on_segment_started(segment)` → THINK
  - `on_segment_finished(segment)` → DO
- never makes programming decisions; it only plays what it's given
- never attempts Tower-synchronized pacing (Tower owns broadcast timing via Clock B)

### 2.3 THINK vs DO
- THINK (Prep Window, during `on_segment_started`): plan the next break; select exact MP3s (outro?, ID(s)?, intro?, next song).
- DO (Transition Window, during `on_segment_finished`): atomically push pre-selected assets to queue; no decision making, no blocking.

### 2.4 Real-Time PCM Pipeline
All playout uses:
`AudioEvent (mp3 path) → FFmpegDecoder → PCM frames (numpy) → Mixer → OutputSink`
- deterministic playback and timing
- non-blocking event flow
- real-time safe components

### 2.5 No Real-Time Generation
Never generate assets during DO. No TTS, scanning, or re-encoding on the transition path. If assets are missing, fall back to safe generics selected during THINK.

---

## 3. System Lifecycle Events

### 3.1 on_station_start
`Station.start()` handles state loading directly during boot:
- Load media library, AssetDiscoveryManager, DJ/rotation state.
- AssetDiscoveryManager discovers intros, outros, and generic intros by scanning DJ asset directories based on naming conventions. Performs hourly rescans during THINK windows to maintain an in-memory cache of available assets.
- Choose first song and queue it to start playback.
- Transition to normal THINK/DO operation.

Note: `DJEngine.on_station_start` exists for future expansion but is not part of the active flow. State loading is handled directly by `Station.start()`, not through this callback.

### 3.2 on_segment_started (THINK)
- Clear previously executed intent.
- Optionally consume ticklers (future-only).
- Decide break structure: talk?, ID?, intro?, legal ID?
- Select concrete MP3 files for:
  - outro (optional)
  - station ID(s) (0..N)
  - intro (optional)
  - next song (required; chosen by RotationManager)
- Validate asset availability; substitute safe generics if needed.
- Commit a `DJIntent` capturing the exact AudioEvents.

No queue mutations occur in THINK.

Ticklers constraint:
- Ticklers must never generate assets that are immediately used in the same THINK/DO cycle (no “generate now, use now”).

### 3.3 on_segment_finished (DO)
- Retrieve the current `DJIntent`.
- Push events in order: `[outro?] → [id(s)?] → [intro?] → [next_song]`.
- Clear the `DJIntent`.
- Optionally schedule ticklers for future content.

No decisions, no blocking, no external calls in DO.

### 3.4 on_station_stop
`Station.stop()` handles state saving directly during shutdown:
- Save DJ/rotation state and any tickler backlog.
- Safely stop decoder and output sinks.
- Ensure warm-start avoids immediate repeats.

Note: `DJEngine.on_station_stop` exists for future expansion but is not part of the active flow. State saving is handled directly by `Station.stop()`, not through this callback.

---

## 4. DJ Brain & Intent Model

### 4.1 DJ State Includes
- rotation history and last-N songs
- intro/outro/ID cooldowns
- legal/non-legal ID timing rules
- talk frequency/cadence tracking
- tickler queue for future prep
- references to cached assets and library listings

### 4.2 DJIntent
Represents exactly what will be pushed during DO, resolved to concrete MP3s:
- `next_song: AudioEvent` (required)
- `outro: Optional[AudioEvent]`
- `station_ids: list[AudioEvent]`
- `intro: Optional[AudioEvent]`
- `has_legal_id: bool` — determined during THINK; indicates whether the station ID chosen qualifies as a legal ID for compliance/timestamp tracking.

Built during THINK, executed during DO.

Note: `has_legal_id` is metadata only and is used exclusively in DO to update compliance timestamps.

---

## 5. Rotation & Song Selection

### 5.1 RotationManager
Weighted selection with:
- immediate-repeat penalty and recent-play decay (queue-like)
- time-based bonus for tracks not played recently
- never-played bonus
- play-count balancing for fairness
- holiday-aware pool selection with date-based probability ramp (Nov–Dec)

Tracks are passed as full paths. History/play counts are tracked and can be persisted to disk. The DJ excludes the currently playing song at THINK time to avoid THINK/DO timing repeats.

### 5.2 MediaLibrary
Filesystem-backed discovery for available songs:
- loads from `REGULAR_MUSIC_PATH` and `HOLIDAY_MUSIC_PATH`
- provides validated lists to RotationManager
- does not make rotation decisions

---

## 6. Audio Pipeline Components

### 6.1 FFmpegDecoder
- Spawns an ffmpeg subprocess to decode MP3 to `pcm_s16le` frames
- Yields frames as numpy arrays
- Frame size configurable; timing stable

### 6.2 Mixer
- Applies gain from `AudioEvent`
- Foundation for crossfades, ducking, overlays
- Real-time safe; passes normalized frames to sink

### 6.3 OutputSink
- FileSink (debug) writes raw/muxed PCM
- FFMPEGSink (production) encodes to AAC/MP3/Icecast/HLS, etc.
- Non-blocking, continuous operation

### 6.4 Canonical Audio Format
- PCM s16le
- 48 kHz sample rate
- 2 channels (stereo)
- frame_size = 1024 samples
- frame_duration = ~21.333 ms (1024 samples / 48000 Hz)

**Clock A decode pacing:**
- Station may pace decode consumption at ~21.333ms per frame using Clock A
- This ensures songs play at real duration (e.g., 200-second MP3 takes 200 seconds)
- Socket writes remain non-blocking and fire immediately (no pacing on writes)

---

## 7. PlayoutEngine (Event-Driven, Real Audio)

High-level loop:
1. Start segment S → emit `on_segment_started(S)` (THINK)
2. Decode S via FFmpegDecoder → Clock A paces frame consumption (~21.333ms per frame) → Mixer → OutputSink (writes fire immediately, non-blocking)
3. On completion → emit `on_segment_finished(S)` (DO)
4. DJ pushes `[outro?][id(s)?][intro?][next_song]` from `DJIntent`
5. Repeat

PlayoutEngine decodes and plays exactly one segment at a time; no prefetching or concurrent decoding occurs.

**Two-Clock Architecture:**
- **Clock A (Station decode metronome):** Paces decode consumption for local playback correctness. Ensures songs play at real duration (e.g., 200-second MP3 takes 200 seconds). Monotonic, wall-clock-fidelity. Never observes Tower state. Never alters pacing based on socket success/failure.
- **Clock B (Tower AudioPump):** Sole authority for broadcast timing (strict 21.333ms). Station never attempts to match or influence Clock B.

**Decode pacing rules:**
- After decoding a PCM frame, Station: `next_frame_time += FRAME_DURATION` (~21.333 ms), then `sleep(max(0, next_frame_time - now))`
- Socket writes fire immediately (non-blocking, no pacing on writes)
- No adaptive pacing, buffer-based pacing, or rate correction
- No Tower-synchronized pacing

Non-goals in 3.2:
- No gapless transition rules
- No embossing/concatenation
- No real-time transformations beyond decoding/mixing

---

## 8. Environment & Assets

### 8.1 .env variables
```
REGULAR_MUSIC_PATH=/path/to/songs
HOLIDAY_MUSIC_PATH=/path/to/holiday_songs
DJ_PATH=/path/to/dj_assets
```

### 8.2 Directory expectations
- `REGULAR_MUSIC_PATH/*.mp3`
- `HOLIDAY_MUSIC_PATH/*.mp3`
- `DJ_PATH/`
  - `intros/intro_*.mp3`
  - `outros/outro_*.mp3` (canonical spelling)
  - `outros/outtro_*.mp3` (legacy spelling, accepted for compatibility)
  - `ids/id_*.mp3` (legal and generic)
  - `talk/talk_*.mp3`

**Note on outro filename patterns:** Both `_outro` and `_outtro` filename patterns are accepted for legacy compatibility. The canonical spelling is `_outro`. Phase B will normalize spellings automatically.

### 8.3 Asset availability rules
- If a requested file is missing at DO, never block; DO must not fail.
- THINK ensures substitutions to safe generics if needed.

---

## 9. Directory Structure (informative)

**Note:** The architecture above describes a logical module layout. The physical codebase resides under `station/`.

```
retrowaves/
└── station/
    ├── app/                      # station orchestration
    ├── music_logic/              # rotation, library
    ├── dj_logic/                 # dj engine, intent, ticklers, cache
    ├── broadcast_core/           # audio event, playout engine, sinks/decoders
    ├── mixer/                    # audio mixer
    ├── outputs/                  # sinks
    ├── clock/                    # timing utilities
    └── state/                    # DJ state persistence (DJStateStore)
```

---

## 10. Startup / Shutdown

Startup:
- Load MediaLibrary and AssetDiscoveryManager
- Load rotation/DJ state
- Select first song and queue initial `AudioEvent`
- Start the real-time playout loop

Shutdown:
- Terminate decoder and sinks cleanly
- Persist DJ/rotation state

---

## 11. Summary

- THINK/DO model with `DJIntent` controls all programming decisions and execution timing.
- Real audio pipeline: filesystem-backed assets, FFmpeg decoding, mixer, and output sinks.
- Control flow: THINK decides, DO executes, playout is metronomic and non-blocking.

---

Document: Unified Architecture (canonical)  
Last Updated: 2025-12-03  
Authority: This document supersedes prior architecture documents.


