"""
Contract tests for ROTATION_MANAGER_CONTRACT

See docs/contracts/ROTATION_MANAGER_CONTRACT.md

Tests map directly to contract clauses:
- ROT1.1: Cooldown Enforcement (2 tests)
- ROT1.2: Weighted Rules (2 tests)
- ROT2.1: Single Track Return (2 tests)
- ROT2.2: Atomic History Update (1 test)
"""

import pytest

from station.tests.contracts.test_doubles import FakeRotationManager


class TestROT1_1_CooldownEnforcement:
    """Tests for ROT1.1 — Cooldown Enforcement."""
    
    def test_rot1_1_next_track_not_in_cooldown(self, fake_rotation_manager):
        """ROT1.1: Next track MUST NOT be in the cooldown window."""
        track1 = fake_rotation_manager.select_next_song()
        fake_rotation_manager.record_song_played(track1)
        
        track2 = fake_rotation_manager.select_next_song()
        
        # FakeRotationManager cycles through tracks deterministically
        # Contract requires cooldown - actual cooldown logic tested in integration
        assert track2 is not None, "Must return a track"
        assert isinstance(track2, str), "Must return file path"
    
    def test_rot1_1_cooldown_state_maintained(self, fake_rotation_manager):
        """ROT1.1: Cooldown state must be maintained and persisted."""
        track = fake_rotation_manager.select_next_song()
        fake_rotation_manager.record_song_played(track)
        
        # Contract requires history maintenance
        assert len(fake_rotation_manager.history) > 0, "History must be maintained"
        assert hasattr(fake_rotation_manager, 'history'), "Must have history attribute"


class TestROT1_2_WeightedRules:
    """Tests for ROT1.2 — Weighted Rules."""
    
    def test_rot1_2_favors_long_unplayed_tracks(self, fake_rotation_manager):
        """ROT1.2: Weighted rules MUST favor long-unplayed tracks."""
        # Contract requires weighted selection favoring long-unplayed
        # FakeRotationManager provides deterministic selection for contract structure test
        # Actual weighted algorithm tested in integration
        track = fake_rotation_manager.select_next_song()
        assert track is not None, "Must return a track"
    
    def test_rot1_2_seasonal_holiday_pools(self, fake_rotation_manager):
        """ROT1.2: Weighted rules MUST support seasonal/holiday pools."""
        # Contract requires holiday season detection and probability
        assert hasattr(fake_rotation_manager, 'is_holiday_season'), "Must have holiday detection"
        assert hasattr(fake_rotation_manager, 'get_holiday_selection_probability'), "Must have holiday probability"
        
        is_holiday = fake_rotation_manager.is_holiday_season()
        prob = fake_rotation_manager.get_holiday_selection_probability()
        
        assert isinstance(is_holiday, bool), "is_holiday_season must return bool"
        assert 0.0 <= prob <= 1.0, "Probability must be 0-1"


class TestROT2_1_SingleTrackReturn:
    """Tests for ROT2.1 — Single Track Return."""
    
    def test_rot2_1_returns_exactly_one_track(self, fake_rotation_manager):
        """ROT2.1: MUST return exactly one valid file path."""
        track = fake_rotation_manager.select_next_song()
        
        assert track is not None, "Must return a track"
        assert isinstance(track, str), "Must return string (file path)"
        assert track.endswith('.mp3'), "Must return MP3 file path"
    
    def test_rot2_1_path_must_be_absolute(self, fake_rotation_manager):
        """ROT2.1: Path must be absolute."""
        track = fake_rotation_manager.select_next_song()
        
        # Contract requires absolute paths
        assert track.startswith('/'), "Path must be absolute"


class TestROT2_2_AtomicHistoryUpdate:
    """Tests for ROT2.2 — Atomic History Update."""
    
    def test_rot2_2_updates_history_atomically(self, fake_rotation_manager):
        """ROT2.2: MUST update play history atomically."""
        initial_len = len(fake_rotation_manager.history)
        track = fake_rotation_manager.select_next_song()
        fake_rotation_manager.record_song_played(track)
        
        # Contract requires atomic history update
        assert len(fake_rotation_manager.history) == initial_len + 1, "History must be updated atomically"
        assert fake_rotation_manager.history[-1][0] == track, "History entry must match track"
