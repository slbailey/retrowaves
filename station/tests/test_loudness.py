"""LoudnessIndex: gain math, caching, change detection (fake meter), plus one real ffmpeg measurement."""

import json
import math
import shutil
import subprocess

import pytest

from station.broadcast_core.loudness import LoudnessIndex, measure_ffmpeg


def db(gain):
    return 20 * math.log10(gain)


def fake_meter(values):
    calls = []

    def measure(path):
        calls.append(path)
        return values[path.replace("\\", "/").rsplit("/", 1)[-1]]
    measure.calls = calls
    return measure


def write(path, data=b"ID3"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return str(path)


def test_gain_math():
    idx = LoudnessIndex(None, target_lufs=-18, max_peak_dbfs=-1)
    assert idx.gain_db_for_measurement(-23.2, -7.2) == pytest.approx(5.2)   # quiet drama: full boost
    assert idx.gain_db_for_measurement(-11.0, -0.0) == pytest.approx(-7.0)  # hot song: cut
    assert idx.gain_db_for_measurement(-24.0, -3.0) == pytest.approx(2.0)   # boost capped by peak
    assert idx.gain_db_for_measurement(float("-inf"), float("-inf")) == 0.0  # silence: untouched
    assert idx.gain_db_for_measurement(-50.0, -40.0) == pytest.approx(12.0)  # max boost


def test_unmeasured_file_plays_at_unity(tmp_path):
    idx = LoudnessIndex(None)
    assert idx.gain_for(str(tmp_path / "nope.mp3")) == 1.0


def test_sweep_measures_caches_and_skips_unchanged(tmp_path):
    a = write(tmp_path / "music" / "a.mp3")
    write(tmp_path / "julie" / "b.mp3")
    write(tmp_path / "julie" / "_source" / "skip.mp3")
    write(tmp_path / "julie" / "notes.txt")
    meter = fake_meter({"a.mp3": (-14.0, -0.5), "b.mp3": (-19.0, -3.0)})
    cache = tmp_path / "loudness.json"
    idx = LoudnessIndex(str(cache), roots=[tmp_path / "music", tmp_path / "julie"], measure=meter)
    assert idx.sweep() == 2
    assert db(idx.gain_for(a)) == pytest.approx(-4.0)
    assert json.loads(cache.read_text())["entries"][a]["lufs"] == -14.0

    reloaded = LoudnessIndex(str(cache), roots=[tmp_path / "music", tmp_path / "julie"], measure=meter)
    assert reloaded.sweep() == 0                     # nothing changed, nothing re-measured
    assert db(reloaded.gain_for(a)) == pytest.approx(-4.0)

    write(tmp_path / "music" / "a.mp3", b"ID3 changed")
    assert reloaded.sweep() == 1


def test_deleted_files_are_dropped(tmp_path):
    a = write(tmp_path / "music" / "a.mp3")
    b = write(tmp_path / "music" / "b.mp3")
    idx = LoudnessIndex(None, roots=[tmp_path / "music"], measure=fake_meter({"a.mp3": (-18, -3), "b.mp3": (-18, -3)}))
    idx.sweep()
    (tmp_path / "music" / "b.mp3").unlink()
    idx.sweep()
    assert idx.is_measured(a) and not idx.is_measured(b)


def test_failed_measurement_leaves_unity(tmp_path):
    a = write(tmp_path / "a.mp3")
    idx = LoudnessIndex(None, roots=[tmp_path], measure=lambda p: None)
    idx.sweep()
    assert idx.gain_for(a) == 1.0


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")
def test_real_ffmpeg_measurement(tmp_path):
    out = tmp_path / "tone.mp3"
    subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i",
                    "sine=frequency=1000:duration=3", "-af", "volume=-20dB", str(out)], check=True)
    lufs, peak = measure_ffmpeg(str(out))
    # lavfi sine is 1/8 full scale (-18 dBFS peak); -20 dB more gives a -38 dBFS peak
    assert -38.5 < peak < -37.5
    assert -43 < lufs < -40
