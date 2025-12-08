# AssetDiscoveryManager Contract

## Purpose

Defines discovery, indexing, and safety for all audio assets (songs, IDs, intros, outros, talk segments).

---

## ADM1 — Discovery Rules

### ADM1.1 — Scanning Schedule

**MUST** scan **DJ_PATH** directories at startup and hourly during **THINK**.

- Initial scan occurs during Station startup
- Periodic scans occur every hour (configurable)
- Scans must not block playout or THINK/DO cycles
- Scans may run in background threads

### ADM1.2 — Directory Categorization

**MUST** categorize assets strictly by directory:

- **`intros/`**: Intro clips for songs
- **`outros/`**: Outro clips for songs
- **`ids/`**: Station identification clips
- **`talk/`**: Talk segments (if applicable)
- **`music/`** or root: Main music library

---

## ADM2 — Output Rules

### ADM2.1 — Cached Lists

**MUST** produce complete cached lists for **DJEngine**.

- Lists must be in-memory for fast access
- Lists must be updated atomically (no partial updates during scan)
- Lists must include file paths, metadata, and categorization
- DJEngine must not perform file I/O — all data comes from cache

### ADM2.2 — Legacy Pattern Support

**MUST** support both `outro_*` and legacy `outtro_*` patterns.

- Both naming conventions must be recognized
- Legacy patterns must be mapped to standard categories
- No duplicate entries for same file under different names

### ADM2.3 — Non-Blocking

**MUST NOT** block playout or **DO**.

- Scans run in background threads
- Cache updates are atomic and non-blocking
- DJEngine always reads from cache (never waits for scan)

---

## Implementation Notes

- AssetDiscoveryManager maintains in-memory cache of all assets
- Cache is updated atomically (swap old cache for new cache)
- File system events may trigger incremental updates (optional)
- Metadata extraction (duration, tags) may occur during scan
- Invalid files (corrupt, unreadable) are excluded from cache




