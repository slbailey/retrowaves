# Appalachia Radio — Unified System Architecture

A DJ-driven, event-timed, intent-based radio automation engine with real audio playout.

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

### 2.2 Playback Engine Is the Metronome
The PlayoutEngine:
- decodes audio to frames, mixes frames, sends frames to outputs
- emits lifecycle events:
  - `on_segment_started(segment)` → THINK
  - `on_segment_finished(segment)` → DO
- never makes programming decisions; it only plays what it’s given

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
At boot:
- Load media library, cache manager, DJ/rotation state.
- Choose first song and queue it to start playback.
- Transition to normal THINK/DO operation.

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
- Save DJ/rotation state and any tickler backlog.
- Safely stop decoder and output sinks.
- Ensure warm-start avoids immediate repeats.

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

Built during THINK, executed during DO.

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

---

## 7. PlayoutEngine (Event-Driven, Real Audio)

High-level loop:
1. Start segment S → emit `on_segment_started(S)` (THINK)
2. Decode S via FFmpegDecoder → frames → Mixer → OutputSink
3. On completion → emit `on_segment_finished(S)` (DO)
4. DJ pushes `[outro?][id(s)?][intro?][next_song]` from `DJIntent`
5. Repeat

PlayoutEngine decodes and plays exactly one segment at a time; no prefetching or concurrent decoding occurs.

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
  - `outros/outro_*.mp3`
  - `ids/id_*.mp3` (legal and generic)
  - `talk/talk_*.mp3`

### 8.3 Asset availability rules
- If a requested file is missing at DO, never block; DO must not fail.
- THINK ensures substitutions to safe generics if needed.

---

## 9. Directory Structure (informative)

```
appalachia-radio/
├── app/                      # station orchestration
├── music_logic/              # rotation, library
├── dj_logic/                 # dj engine, intent, ticklers, cache
├── broadcast_core/           # audio event, playout engine, sinks/decoders
├── mixer/                    # audio mixer
├── outputs/                  # sinks
└── clock/                    # timing utilities
```

---

## 10. Startup / Shutdown

Startup:
- Load MediaLibrary and CacheManager
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


