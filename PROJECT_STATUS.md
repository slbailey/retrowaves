# Project Status — Retrowaves

## Current Objective
- Standardize and enforce canonical PCM cadence across docs, tools, and implementations: 1024 samples (4096 bytes) per frame at 48 kHz (≈21.333ms).

## Latest Session (2025-12-27)
- Aligned `ARCHITECTURE_TOWER.md` and `tools/pcm_ffmpeg_test.py` with 1024/4096 and ≈21.333ms.
- Replaced video-centric closeout doc with engineering-focused `SESSION_CLOSE.md`.

## Immediate Next Steps
- Audit and update remaining references to 1152/4608/24ms across repo (tests/docs).
- Run contract/integration tests to validate 1024-cadence behavior end-to-end.
- Link this status from `README.md` to surface current focus.

## How to Run
```bash
# Station
python3 run_station_dev.py

# Tower
python3 run_tower_dev.py
```

## How to Test
```bash
pytest
```


