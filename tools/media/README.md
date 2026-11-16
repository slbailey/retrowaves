# Media tree tools

`build_v2_tree.py` builds the directory-categorized v2 media tree
(see `station/docs/contracts/ASSET_DISCOVERY_MANAGER_CONTRACT.md` ADM1.2) from:

1. a Fallout 76 extraction (`Music/`, `Julie/Between Songs/<Artist - Title>/`,
   `Julie/Station IDs/`, `Julie/Julie's Story/`, `Julie transcripts.csv`)
2. the pre-v2 `julie/` and `holiday_songs/` dirs (holiday clips, lifecycle
   announcements, legacy IDs, story order)
3. `match.json` from `match_clips_by_audio.py` (audio-envelope match of every
   old clip to its new-extraction twin; needs numpy + ffmpeg)

It refuses to overwrite, fails on any song/clip-folder mismatch, and writes
`MANIFEST.csv` (every file's origin, game line ID, transcript line, and the old
file it replaces).

```sh
python3 tools/media/match_clips_by_audio.py OLD_JULIE EXTRACTION match.json
python3 -I tools/media/build_v2_tree.py EXTRACTION OLD_JULIE OLD_HOLIDAY match.json OUT
```

The 2026-11-16 build lives at `/mnt/media/appalachia-radio-v2` (source
extraction + tools copy under `_source/` and `_tools/`).
