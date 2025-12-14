# Event Inventory - Station → Tower System

## Purpose

This document defines the complete inventory of events emitted in the Station → Tower system. All events originate from Station and are received and broadcast by Tower.

---

## Event Inventory Table

| Event Name | Authority | Emitter | Trigger | Segment Scope | Lifecycle | Restart Behavior | Fields |
|------------|-----------|---------|---------|---------------|-----------|------------------|--------|
| `station_starting_up` | Station | Station | Station.start() called, before playout begins | Non-segment | One-shot | Re-emitted on restart | `event_type`, `timestamp`, `metadata: {}` |
| `station_shutting_down` | Station | Station | After terminal playout completes (or timeout) | Non-segment | One-shot | Re-emitted on restart | `event_type`, `timestamp`, `metadata: {}` |
| `now_playing` | Station | NowPlayingStateManager (via TowerControlClient) | When segment starts (on_segment_started) | All segments | Start+Clear | Derived on reconnect | `event_type`, `timestamp`, `metadata: {segment_type, started_at, title?, artist?, album?, year?, duration_sec?, file_path?}` |
| `now_playing` (empty) | Station | NowPlayingStateManager (via TowerControlClient) | When segment finishes (on_segment_finished) | All segments | Start+Clear | Derived on reconnect | `event_type`, `timestamp`, `metadata: {}` |
| `dj_talking` | Station | PlayoutEngine | When intro/outro/talk segment starts, only once per talking sequence | Talk segments only | One-shot per sequence | Re-emitted on restart | `event_type`, `timestamp`, `metadata: {}` |
| `dj_think_started` | Station | DJEngine | Before THINK logic begins (on_segment_started callback) | Song/announcement segments | Repeating | Re-emitted on restart | `event_type`, `timestamp`, `metadata: {current_segment}` |
| `dj_think_completed` | Station | DJEngine | After THINK logic completes (before DO phase) | Song/announcement segments | Repeating | Re-emitted on restart | `event_type`, `timestamp`, `metadata: {think_duration_ms, dj_intent?}` |
| `station_underflow` | Station | OutputSink (TowerPCMSink) | When buffer becomes empty (buffer depth = 0) | Non-segment | Repeating | Re-emitted on restart | `event_type`, `timestamp`, `metadata: {buffer_depth, frames_dropped}` |
| `station_overflow` | Station | OutputSink (TowerPCMSink) | When buffer exceeds capacity (frames dropped) | Non-segment | Repeating | Re-emitted on restart | `event_type`, `timestamp`, `metadata: {buffer_depth, frames_dropped}` |

---

## Notes / Clarifications

### Event Authority

- **Station Authority**: Events are emitted by Station components (PlayoutEngine, DJEngine, OutputSink, Station, NowPlayingStateManager)
- **Tower Authority**: Tower receives and broadcasts Station events. Tower does not emit events in this system
- **Event Flow**: Station → Tower (one-way). Tower adds `tower_received_at` timestamp and `event_id` to received events but does not modify semantic meaning

### Emission Timing

- **`now_playing`**: Emitted synchronously with `on_segment_started` callback (via NowPlayingStateManager listener)
- **`dj_talking`**: Emitted synchronously before audio begins, only once per talking sequence (intro/outro/talk segments)
- **`dj_think_started`**: Emitted synchronously before THINK logic begins
- **`dj_think_completed`**: Emitted synchronously after THINK logic completes, before DO phase begins
- **`station_underflow`**: Emitted when buffer depth transitions from non-zero to zero, checked periodically (implementation-defined polling interval) during frame writes
- **`station_overflow`**: Emitted when buffer depth transitions to capacity (overflow condition), checked periodically (implementation-defined polling interval) during frame writes
- **`station_starting_up`**: Emitted before playout begins
- **`station_shutting_down`**: Emitted after terminal playout completes (or timeout), not when shutdown is initiated

### Segment Scope

- **Song/announcement segments**: Events that fire for song or announcement segments (e.g., `dj_think_started`, `dj_think_completed`)
- **Talk segments only**: Events that fire only for talk segments (e.g., `dj_talking`)
- **All segments**: Events that fire for any segment type (song, intro, outro, id, talk, fallback, announcement) (e.g., `now_playing`)
- **Non-segment**: Events that are not tied to segment lifecycle (e.g., `station_starting_up`, `station_underflow`)

### Lifecycle Semantics

- **Stateful Event**: `now_playing` is the only event representing authoritative current state. All other events are pulse or telemetry events.
- **One-shot**: Event fires exactly once per lifecycle (e.g., `station_starting_up`)
- **Start+Clear**: Event fires with data on start, with empty data on finish (e.g., `now_playing`)
- **Repeating**: Event can fire multiple times during operation (e.g., `dj_think_started` for each song)

### Restart Behavior

- **Re-emitted on restart**: Event is emitted again when Station restarts
- **Derived on reconnect**: Event state is reconstructed from current state when Tower reconnects

### Tower Event Processing

- Tower receives events via `/tower/events/ingest` endpoint
- Tower adds `tower_received_at` timestamp and `event_id` to received events
- Tower broadcasts events to WebSocket clients via `/tower/events` endpoint
- Tower does not modify event semantic meaning
- Tower does not emit its own events (one-way: Station → Tower)

---

## Event Flow Summary

1. **Station Lifecycle Events**: `station_starting_up` → (playout) → `station_shutting_down`
2. **Segment Lifecycle Events**: `now_playing` (with data) → (playback) → `now_playing` (empty)
3. **THINK/DO Events**: `dj_think_started` → (THINK logic) → `dj_think_completed` → (DO phase)
4. **Content Events**: `dj_talking` (when talk segments start)
5. **Buffer Health Events**: `station_underflow`, `station_overflow` (when buffer conditions detected)
