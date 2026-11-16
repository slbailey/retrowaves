"""Build the reorganized Appalachia Radio media tree (v2).

Inputs (all read-only):
  NEW   = the 2026-11-16 Fallout 76 extraction (Music/, Julie/, Julie transcripts.csv)
  LIVEJ = copy of the live julie/ dir     (holiday clips, lifecycle, legacy IDs, story order)
  LIVEH = copy of the live holiday_songs/ dir
  MATCH = audio-fingerprint match of live clips -> new extraction (match.json)
Output:
  OUT/music/{regular,holiday}/<Artist - Title>.mp3
  OUT/julie/between-songs/<Artist - Title>/{Intro,Outro} - <id> - <text>.mp3
  OUT/julie/generic/Intro - ....mp3
  OUT/julie/station-ids/{legal,generic,sequences/collectron}/
  OUT/julie/lifecycle/{startup,shutdown}/
  OUT/julie/story/NN - <id> - <text>.mp3
  OUT/julie/archive/   (kept, never scheduled)
  OUT/transcripts.csv, OUT/MANIFEST.csv
"""
import csv, json, os, re, shutil, sys
from pathlib import Path

NEW, LIVEJ, LIVEH, MATCH, OUT = map(Path, sys.argv[1:6])
manifest = []


def put(src, rel, origin, gid="", line="", replaces=""):
    dst = OUT / rel
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        raise SystemExit(f"collision: {rel}")
    shutil.copy2(src, dst)
    manifest.append({"path": rel.as_posix(), "origin": origin, "game_id": gid,
                     "line": line, "replaces_live": replaces})


trans = {r["file"]: r for r in csv.DictReader(open(NEW / "Julie transcripts.csv", encoding="utf-8-sig"))}
gid_of = lambda name: (re.search(r"([0-9A-F]{8}_\d+)", name) or [None, ""])[1] if re.search(r"([0-9A-F]{8}_\d+)", name) else ""
match = json.load(open(MATCH, encoding="utf-8"))
# live file -> new file it is (only confident matches)
live_to_new = {k: v[0][1] for k, v in match.items() if v[0][0] >= 0.85}
new_to_live = {}
for k, v in live_to_new.items():
    new_to_live.setdefault(v, []).append(k)


def line_for(fname):
    t = trans.get(fname)
    return t["line"] if t else ""


# ---- regular music + per-song clips (straight from the new extraction)
songs = sorted(p.stem for p in (NEW / "Music").glob("*.mp3"))
for s in songs:
    put(NEW / "Music" / f"{s}.mp3", Path("music/regular") / f"{s}.mp3", "fo76-2026-11-16")
    folder = NEW / "Julie" / "Between Songs" / s
    if not folder.is_dir():
        raise SystemExit(f"no clip folder for song {s!r}")
    for clip in sorted(folder.glob("*.mp3")):
        rel_new = clip.relative_to(NEW).as_posix()
        put(clip, Path("julie/between-songs") / s / clip.name, "fo76-2026-11-16",
            gid_of(clip.name), line_for(clip.name), ";".join(new_to_live.get(rel_new, [])))
extra = {p.name for p in (NEW / "Julie" / "Between Songs").iterdir()} - set(songs)
if extra:
    raise SystemExit(f"clip folders with no song: {extra}")

# ---- holiday music (renamed to Artist - Title) + its 4 clip pairs
HOLIDAY = {
    "Baby_It's_Cold_Outside_-_Margaret_Whiting_Johnny_Mercer": "Margaret Whiting Johnny Mercer - Baby Its Cold Outside",
    "Benny_Goodman_Orchestra_Peggy_Lee_-_Winter_Weather": "Benny Goodman Orchestra Peggy Lee - Winter Weather",
    "Boogie_Woogie_Santa_Claus_-_Mabel_Scott": "Mabel Scott - Boogie Woogie Santa Claus",
    "Christmas_is_Coming_At_Last_-_The_Rhythm_Kings": "The Rhythm Kings - Christmas Is Coming At Last",
    "Christmas_Island_-_Andrews_Sisters_Guy_Lombardo": "Andrews Sisters Guy Lombardo - Christmas Island",
    "Happy_Holiday_-_Bing_Crosby_The_Music_Maids": "Bing Crosby The Music Maids - Happy Holiday",
    "I_Told_Santa_Claus_to_Bring_Me_You_-_Bernie_Cummins_and_His_Orchestra": "Bernie Cummins And His Orchestra - I Told Santa Claus To Bring Me You",
    "I_ve_Got_My_Love_to_Keep_Me_Warm_-_Billie_Holiday": "Billie Holiday - Ive Got My Love To Keep Me Warm",
    "I've_Got_My_Love_To_Keep_Me_Warm_-_Les_Brown": "Les Brown - Ive Got My Love To Keep Me Warm",
    "Jingle_Bells_-_Benny_Goodman": "Benny Goodman - Jingle Bells",
    "Let_It_Snow_Let_It_Snow_Let_It_Snow_-_Vaughn_Monroe": "Vaughn Monroe - Let It Snow Let It Snow Let It Snow",
    "Little_Jack_Frost_Get_Lost_-_Frankie_Carle": "Frankie Carle - Little Jack Frost Get Lost",
    "Parade_of_the_Wooden_Soldiers_-_Larry_Clinton": "Larry Clinton - Parade Of The Wooden Soldiers",
    "Rudolph_The_Red-Nosed_Reindeer_-_Gene_Autry": "Gene Autry - Rudolph The Red Nosed Reindeer",
    "Santa_Claus_Came_in_the_Spring_-_Benny_Goodman": "Benny Goodman - Santa Claus Came In The Spring",
    "Santa_Claus_is_Coming_to_Town_-_Tommy_Dorsey_His_Orchestra": "Tommy Dorsey His Orchestra - Santa Claus Is Coming To Town",
    "Send_Me_Your_Love_for_Christmas_-_The_Raymond_Scott_Orchestra": "The Raymond Scott Orchestra - Send Me Your Love For Christmas",
    "Silver_Bells_-_Bing_Crosby_Carol_Richards": "Bing Crosby Carol Richards - Silver Bells",
    "Sleigh_Ride_-_Andrews_Sisters_with_Vic_Schoen_and_His_Orchestra": "Andrews Sisters With Vic Schoen And His Orchestra - Sleigh Ride",
    "The_Christmas_Song_-_Nat_King_Cole": "Nat King Cole - The Christmas Song",
    "The_Ink_Spots_-_White_Christmas": "Ink Spots - White Christmas",
    "The_Man_With_The_Bag_-_Kay_Starr": "Kay Starr - The Man With The Bag",
    "The_Night_Before_Christmas_-_Eddy_Duchin_His_Orchestra": "Eddy Duchin His Orchestra - The Night Before Christmas",
    "There_s_Frost_on_the_Moon_-_Artie_Shaw": "Artie Shaw - Theres Frost On The Moon",
    "What_Will_Santa_Claus_Say_When_He_Finds_Everybody_Swingin_-_Louis_Prima_His_New_Orleans_Gang": "Louis Prima His New Orleans Gang - What Will Santa Claus Say When He Finds Everybody Swingin",
    "When_Winter_Comes_-_Tony_Pastor_The_Artie_Shaw_Orchestra": "Tony Pastor The Artie Shaw Orchestra - When Winter Comes",
    "Winter_Weather_-_Peggy_Lee_Art_Lund_Benny_Goodman_Orchestra": "Peggy Lee Art Lund Benny Goodman Orchestra - Winter Weather",
}
have = {p.stem for p in LIVEH.glob("*.mp3")}
if have != set(HOLIDAY):
    raise SystemExit(f"holiday mismatch: missing map {have - set(HOLIDAY)}, missing file {set(HOLIDAY) - have}")
for old, new in HOLIDAY.items():
    put(LIVEH / f"{old}.mp3", Path("music/holiday") / f"{new}.mp3", "live-carryover", replaces=f"holiday_songs/{old}.mp3")
    for role, pat in (("Intro", "intro"), ("Outro", "outtro")):
        src = LIVEJ / f"{old}_{pat}.mp3"
        if src.exists():
            put(src, Path("julie/between-songs") / new / f"{role} - holiday-01.mp3", "live-carryover",
                replaces=src.name)

# ---- generic intro pool: the one genuinely song-agnostic line
bc = next((NEW / "Julie" / "Between Songs" / "Bob Crosby - Dear Hearts And Gentle People").glob("Intro - 0059C7ED_1*"))
put(bc, Path("julie/generic") / bc.name, "fo76-2026-11-16", "0059C7ED_1", line_for(bc.name), "generic_intro1.mp3")

# ---- station IDs
ids = {p.name: p for p in (NEW / "Julie" / "Station IDs").glob("*.mp3")}
for name, p in sorted(ids.items()):
    gid = gid_of(name)
    rel_new = p.relative_to(NEW).as_posix()
    repl = ";".join(new_to_live.get(rel_new, []))
    if gid == "0059BF56_1":
        rel = Path("julie/station-ids/legal") / name
    elif gid.startswith("0059BF55_"):
        rel = Path("julie/station-ids/sequences/collectron") / f"{gid[-1].zfill(2)} - {name}"
    else:
        rel = Path("julie/station-ids/generic") / name
    put(p, rel, "fo76-2026-11-16", gid, line_for(name), repl)
for n in ("generic_id_002", "generic_id_003", "generic_id_004", "generic_id_005"):
    put(LIVEJ / "ids" / "generic" / f"{n}.mp3", Path("julie/station-ids/generic") / f"legacy - {n}.mp3",
        "live-carryover", replaces=f"ids/generic/{n}.mp3")

# ---- lifecycle announcements (custom, not in the game data)
for sub, dst in (("station_starting_up", "startup"), ("station_shutting_down", "shutdown")):
    for p in sorted((LIVEJ / sub).glob("*.mp3")):
        put(p, Path("julie/lifecycle") / dst / p.name, "live-carryover", replaces=f"{sub}/{p.name}")

# ---- Julie's Story, ordered as the live station had it (JulieScene01-pt1..12)
story_new = {}
for i in range(1, 13):
    tgt = live_to_new.get(f"JulieScene01-pt{i}.mp3")
    if not tgt:
        raise SystemExit(f"story part {i} unmatched")
    story_new[i] = NEW / tgt
if len(set(story_new.values())) != 12:
    raise SystemExit("story parts not unique")
for i, p in story_new.items():
    put(p, Path("julie/story") / f"{i:02d} - {p.name}", "fo76-2026-11-16", gid_of(p.name), line_for(p.name),
        f"JulieScene01-pt{i}.mp3")

# ---- archive: kept, never scheduled
put(LIVEJ / "generic5.mp3", Path("julie/archive/generic5 (128s, unidentified, never aired).mp3"),
    "live-carryover", replaces="generic5.mp3")

shutil.copy2(NEW / "Julie transcripts.csv", OUT / "transcripts.csv")
with open(OUT / "MANIFEST.csv", "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=list(manifest[0]))
    w.writeheader()
    w.writerows(manifest)
print(f"built {len(manifest)} files")
