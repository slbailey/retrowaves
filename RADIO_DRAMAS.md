# Radio dramas and loudness leveling

## Radio dramas

Drop episodes into `<DJ_PATH>/dramas/<series>/`:

```
dramas/Tales from the West Virginia Hills/
  Flatwoods - Part 1.mp3
  Flatwoods - Part 2.mp3
  Intro - Flatwoods - Part 1.mp3     optional DJ lead-in  (aired right before the part)
  Outro - Flatwoods - Part 1.mp3     optional DJ lead-out (aired right after; "Outtro" also accepted)
  The Lonely Road.mp3                a story with no " - Part N" is a one-part story
```

Other files (`.txt` transcripts and so on) are ignored. Parts must start at
Part 1 with no gaps: a story with no Part 1 never airs, and if Part 2 is
missing, Part 3 and later don't air either. The scan logs a warning for both.

### Scheduling rules

| Rule | Default | Env |
|---|---|---|
| At most one drama part per interval | 3600 s | `DRAMA_INTERVAL_SEC` |
| Songs that must air between two drama slots (never back to back) | 3 | `DRAMA_MIN_SONGS_BETWEEN` |
| One part per slot; the next slot after Part N is always Part N+1 of the same story | always | |
| New stories are picked at random from those not aired recently, so every story airs before any repeats | always | |
| First drama on a fresh install, about half an interval after start | | |
| Off switch | on | `DRAMA_ENABLED=false` |

A drama break airs: `[lead-in] → part → [lead-out] → [legal ID if due] → next song`.
Song outros, song intros and generic IDs are dropped from that break so Julie
doesn't talk three times in a row.

Progress is saved to `DRAMA_STATE_PATH` (default
`/var/lib/retrowaves/drama_state.json`) at the moment a part **starts
airing**, not when it's queued. A crash or restart between Part 1 and Part 2
therefore can't lose the place, and a shutdown with a part still in the queue
can't skip one. This is separate from the DJ state file, which is only
written on a clean shutdown (SL2.3.1).

The `segment_playing` event for a part carries `segment_class=radio_drama`
plus `series_id`, `episode_id`, `part_number` and `total_parts`.

## Loudness leveling

Everything that airs (songs, holiday songs, Julie clips, IDs, dramas) is
played at a gain that brings it to a common integrated loudness.

- A background thread measures every `.mp3` under `REGULAR_MUSIC_PATH`,
  `HOLIDAY_MUSIC_PATH` and `DJ_PATH` with FFmpeg's EBU R128 meter at idle CPU
  priority. It re-sweeps hourly and only re-measures files whose size or
  mtime changed. Files queued for the next break jump the line.
- Results are cached in `LOUDNESS_CACHE_PATH` (default
  `/var/lib/retrowaves/loudness.json`), so the full measurement happens once.
- Gain = target − measured loudness, capped at +12 / −20 dB, and the boost is
  capped further so the file's sample peak never exceeds
  `LOUDNESS_MAX_PEAK_DBFS` (default −1). Applying it can't clip.
- The gain is looked up in DJ DO, which is a dict lookup with no filesystem
  access. A file that hasn't been measured yet plays at unity gain, as before.

| Setting | Default |
|---|---|
| `LOUDNESS_ENABLED` | `true` |
| `LOUDNESS_TARGET_LUFS` | `-18` |
| `LOUDNESS_MAX_PEAK_DBFS` | `-1` |
| `LOUDNESS_CACHE_PATH` | `/var/lib/retrowaves/loudness.json` |

Measured on the live v2 library (2026-11-17): Julie and IDs sit at about −18
LUFS. Regular songs average −16.3 (range −18.7 to −13.8). Holiday songs range
from −24.6 to −11.0. The radio dramas are at −23. At a −18 target, every file
reaches the target without hitting the peak cap.
