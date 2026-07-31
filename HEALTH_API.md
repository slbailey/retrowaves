# Health API

Machine-readable health endpoints for monitoring the Station and the Tower.

Both are **non-blocking and do no filesystem work**. This is deliberate: the media
library is a *hard* NFS mount, so an `os.listdir()` in a health handler would block
forever exactly when Unraid is down — hanging the endpoint you are using to diagnose
the outage. Filesystem checks belong in the external mount guard, which wraps them in
`timeout`. It also keeps `/station/health` compliant with STATION_STATE_CONTRACT Q.1
("idempotent and non-blocking").

Neither endpoint changes the existing `/station/state` or `/tower/buffer` contracts.

---

## `GET /tower/health` — port 8005

```json
{
  "service": "tower",
  "audio_state": "PROGRAM",
  "on_air": true,
  "clients": 1,
  "buffer": {"capacity": 60, "count": 4, "ratio": 0.067, "overflow_count": 0},
  "uptime_sec": 1904.2,
  "pid": 929983
}
```

| Field | Meaning |
|---|---|
| `audio_state` | The state `EncoderManager` already tracks internally. One of `PROGRAM`, `FALLBACK_TONE`, `SILENCE_GRACE`, `DEGRADED`. |
| `on_air` | Convenience: `audio_state == "PROGRAM"`. |
| `clients` | Connected `/stream` listeners. Normally 1 (appalachia). `0` means nothing is being broadcast to the FM chain. |
| `buffer` | Same figures as `/tower/buffer`. |

**`audio_state` is the important field.** The Tower plays fallback audio whenever the
Station is not delivering PCM, so:

- `PROGRAM` — real programme audio is being encoded. Healthy.
- `FALLBACK_TONE` / `SILENCE_GRACE` — the Station is **not** feeding the Tower.
  Listeners hear "please stand by" (or a tone). **The Tower is fine; the fault is
  upstream in the Station.**

This distinction is what lets the two monitors avoid fighting each other: appalachia
must never restart itself because the Tower is on fallback — its own end is working
correctly by faithfully playing what it is being sent.

Previously this could only be inferred by grepping journald for
`"PCM loss detected"`, which is fragile and racy.

---

## `GET /station/health` — port 8000

```json
{
  "service": "station",
  "station_state": "SONG_PLAYING",
  "segment_type": "song",
  "title": "Ain't Misbehavin'",
  "artist": "Fats Waller and His Rhythm",
  "segment_age_sec": 41.2,
  "duration_sec": 238.416,
  "stalled_sec": 41.2,
  "overrun": false,
  "uptime_sec": 1904.2,
  "pid": 930009
}
```

| Field | Meaning |
|---|---|
| `stalled_sec` | **How long the current segment has not changed.** The key signal. |
| `segment_age_sec` | Wall-clock age of the current segment. |
| `overrun` | Segment has outlived its own `duration_sec` (+60s slack). |

`/station/state` answers *"what is playing"*. It cannot tell you whether playout is
**advancing** — a wedged Station cheerfully returns the same segment forever, and
looks perfectly healthy. `stalled_sec` is what distinguishes "playing a long track"
from "stuck".

Note `stalled_sec` is measured from when *this process* first observed the current
segment, so it resets on restart. Treat a value near `uptime_sec` on a
freshly-started Station as "not yet known", not as a stall.

---

## Interpreting the pair

| `tower.audio_state` | `station.stalled_sec` | Diagnosis |
|---|---|---|
| `PROGRAM` | small / advancing | Healthy, on air. |
| `FALLBACK_TONE` | large, or endpoint dead | Station wedged. It will **not** stop gracefully — a normal stop waits for the current song plus Julie's outro, and there is no song playing. Escalate. |
| `FALLBACK_TONE` | small / advancing | Station is alive but its PCM is not reaching the Tower (socket or ingest fault). |
| endpoint unreachable | — | That service is down; systemd should already be restarting it. |

### Why "tone means escalate"

A *normal* Station restart is audible as: current song → Julie's outro → (brief
fallback) → Julie's intro → music. It takes 3–4 minutes and that is by design.

Hearing a sustained **tone** means the Station never reached a normal shutdown path.
Waiting politely for a graceful stop will simply time out. That is the case where
more forceful measures (SIGKILL, then start) are correct — and only that case.
