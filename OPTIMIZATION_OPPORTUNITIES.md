# Optimization Opportunities

This document outlines potential performance improvements and critical issues discovered during a review of the Retrowaves codebase.

## 1. Critical Issue: PCM Frame Size Mismatch

**Risk:** High - Potential for audio glitches, buffer overruns/underruns, and system instability.

**Description:**
There is a fundamental conflict in the core audio format specification between the `station` and `tower` components.

-   `ARCHITECTURE_STATION.md` specifies that PCM audio frames are **1024 samples**.
-   `ARCHITECTURE_TOWER.md` specifies that PCM audio frames are **1152 samples**.

If the `station` (producer) and `tower` (consumer) are operating with different frame sizes, the buffer between them will either perpetually fill or drain. This will inevitably lead to audio artifacts, dropped frames, and potential crashes over time.

**Recommendation:**
This is the highest priority issue. Immediately investigate and standardize the PCM frame size across both the `station` and `tower` modules. The correct size should be decided upon and then enforced in the implementation of both services.

## 2. Playout Latency: Station Decoder Lifecycle

**Impact:** Medium - Audible gaps of silence between audio segments (songs, station IDs, etc.).

**Description:**
The `station` currently decodes one audio file at a time, creating a new FFmpeg process for each individual audio segment. The overhead of starting a new process for every song or jingle introduces a small but noticeable delay, resulting in dead air between tracks.

**Recommendation:**
Modify the `DJEngine` and `PlayoutEngine` to be more proactive. The system should pre-emptively spawn the FFmpeg process for the *next* audio segment while the current one is still playing. This can be done during the `DJEngine`'s 'THINK' phase.

By having the decoder for the upcoming track ready *before* the current track finishes, the system can begin sending PCM data for the next segment instantly, eliminating the gap of silence.

## 3. I/O Inefficiency: Asset Discovery

**Impact:** Low to Medium - Can cause periodic high I/O and CPU usage, especially with large music libraries.

**Description:**
The `station/dj_logic/asset_discovery.py` module rescans the entire asset directory every hour. For large libraries containing thousands of files, this is an inefficient, brute-force operation that can cause unnecessary disk I/O and CPU load.

**Recommendation:**
Replace the hourly full scan with a more efficient, event-driven approach. A file system watching library like `watchdog` (which uses `inotify` on Linux) can be used to monitor asset directories for changes in real-time. This would allow the system to update its asset cache incrementally and instantly, only when files are actually added, removed, or modified.

## 4. Further Investigation: Real-time Critical Path

**Area:** `station/dj_logic/dj_engine.py`

**Description:**
The `on_segment_finished` method in the `DJEngine` is a real-time critical path that executes during the 'DO' phase. This method should be non-blocking to ensure smooth transitions. However, it calls three methods that could potentially perform blocking I/O:

-   `_record_song_played`
-   `rotation_manager.record_song_played`
-   `_schedule_ticklers`

**Recommendation:**
A deeper analysis of these methods is required to ensure they do not perform blocking operations (like synchronous database writes or file I/O). Any blocking calls should be deferred to a separate thread or an asynchronous task queue to prevent them from interfering with the real-time playout loop.
