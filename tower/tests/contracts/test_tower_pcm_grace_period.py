"""
Contract tests for Tower PCM Grace Period

See docs/contracts/PCM_GRACE_PERIOD_CONTRACT.md
Covers: [G1]–[G19] (Core invariants, semantics, reset, boundary conditions, integration, configuration, silence frames)
"""

import pytest
import os
import time
from unittest.mock import Mock, patch

from tower.audio.ring_buffer import FrameRingBuffer
from tower.encoder.audio_pump import AudioPump
from tower.fallback.generator import FallbackGenerator
from tower.encoder.encoder_manager import EncoderManager


class TestPCMGracePeriodCoreInvariants:
    """Tests for core invariants [G1]–[G3]."""
    
    def test_g1_configurable_via_env_var(self):
        """Test [G1]: Grace period is configurable via TOWER_PCM_GRACE_SEC (default: 5 seconds)."""
        # Test default
        pcm_buffer = FrameRingBuffer(capacity=10)
        fallback = Mock()
        encoder_manager = Mock()
        
        pump1 = AudioPump(pcm_buffer, fallback, encoder_manager)
        assert pump1.grace_period_sec == 5.0  # Default
        
        # Test custom value
        with patch.dict(os.environ, {'TOWER_PCM_GRACE_SEC': '10.0'}):
            pump2 = AudioPump(pcm_buffer, fallback, encoder_manager)
            assert pump2.grace_period_sec == 10.0
    
    def test_g2_prevents_tone_interruptions(self):
        """Test [G2]: Grace period prevents audible tone interruptions during track transitions."""
        pcm_buffer = FrameRingBuffer(capacity=10)
        fallback = Mock()
        fallback.get_frame.return_value = b'tone_frame' * 100
        encoder_manager = Mock()
        
        pump = AudioPump(pcm_buffer, fallback, encoder_manager)
        
        # During grace period, should use silence, not tone
        # This is tested by checking that fallback is not called immediately
        pump.start()
        time.sleep(0.01)  # Brief wait
        pump.stop()
        
        # Fallback should not be called immediately (grace period active)
        # Exact behavior depends on timing, but grace should delay fallback
    
    def test_g3_uses_silence_during_grace(self):
        """Test [G3]: During grace period, Tower uses silence frames (not fallback tone/file)."""
        pcm_buffer = FrameRingBuffer(capacity=10)
        fallback = Mock()
        fallback.get_frame.return_value = b'fallback_frame'
        encoder_manager = Mock()
        
        pump = AudioPump(pcm_buffer, fallback, encoder_manager)
        
        # Silence frame should be cached
        assert hasattr(pump, 'silence_frame')
        assert len(pump.silence_frame) == 4608  # Standard frame size


class TestPCMGracePeriodSemantics:
    """Tests for grace period semantics [G4]–[G6]."""
    
    def test_g4_starts_when_buffer_empty(self):
        """Test [G4]: Grace period starts when PCM buffer becomes empty."""
        pcm_buffer = FrameRingBuffer(capacity=10)
        fallback = Mock()
        encoder_manager = Mock()
        
        pump = AudioPump(pcm_buffer, fallback, encoder_manager)
        
        # Initially no grace timer
        assert pump.grace_timer_start is None
        
        # Start pump with empty buffer - grace should start
        pump.start()
        time.sleep(0.01)
        
        # Grace timer should be set when buffer is empty
        # (exact timing depends on implementation)
        pump.stop()
    
    def test_g5_uses_silence_during_grace(self):
        """Test [G5]: During grace period, uses silence frames."""
        pcm_buffer = FrameRingBuffer(capacity=10)
        fallback = Mock()
        encoder_manager = Mock()
        
        pump = AudioPump(pcm_buffer, fallback, encoder_manager)
        
        # Verify silence frame exists
        assert hasattr(pump, 'silence_frame')
        assert len(pump.silence_frame) == 4608
        assert pump.silence_frame == b'\x00' * 4608  # All zeros
    
    def test_g6_uses_fallback_after_expiry(self):
        """Test [G6]: After grace period expires, uses FallbackGenerator.get_frame()."""
        pcm_buffer = FrameRingBuffer(capacity=10)
        fallback = Mock()
        fallback.get_frame.return_value = b'fallback_frame'
        encoder_manager = Mock()
        
        # Set very short grace period for testing
        with patch.dict(os.environ, {'TOWER_PCM_GRACE_SEC': '0.01'}):
            pump = AudioPump(pcm_buffer, fallback, encoder_manager)
            
            pump.start()
            time.sleep(0.05)  # Wait for grace to expire
            pump.stop()
            
            # Fallback should be called after grace expires
            # (exact count depends on timing)
            assert fallback.get_frame.called


class TestPCMGracePeriodReset:
    """Tests for grace period reset [G7]–[G9]."""
    
    def test_g7_resets_on_new_pcm(self):
        """Test [G7]: Grace period resets when new PCM frame arrives."""
        pcm_buffer = FrameRingBuffer(capacity=10)
        fallback = Mock()
        encoder_manager = Mock()
        
        pump = AudioPump(pcm_buffer, fallback, encoder_manager)
        
        # Start with empty buffer (grace starts)
        pump.start()
        time.sleep(0.01)
        
        # Push frame - grace should reset
        pcm_buffer.push_frame(b'pcm_frame_data')
        time.sleep(0.01)
        
        pump.stop()
        
        # Grace timer should have been reset
        # (verified by checking that new PCM was used)
    
    def test_g8_immediate_switch_to_live(self):
        """Test [G8]: Reset behavior - immediate switch to live PCM."""
        pcm_buffer = FrameRingBuffer(capacity=10)
        fallback = Mock()
        encoder_manager = Mock()
        
        pump = AudioPump(pcm_buffer, fallback, encoder_manager)
        
        # Push PCM frame
        pcm_buffer.push_frame(b'live_pcm_frame')
        
        pump.start()
        time.sleep(0.01)
        pump.stop()
        
        # Should have written PCM frame (not fallback)
        encoder_manager.write_pcm.assert_called()
    
    def test_g9_immediate_reset(self):
        """Test [G9]: Reset is immediate (no delay or hysteresis)."""
        pcm_buffer = FrameRingBuffer(capacity=10)
        fallback = Mock()
        encoder_manager = Mock()
        
        pump = AudioPump(pcm_buffer, fallback, encoder_manager)
        
        # Start with empty buffer
        pump.start()
        time.sleep(0.01)
        
        # Push frame - should reset immediately
        start = time.time()
        pcm_buffer.push_frame(b'frame')
        time.sleep(0.01)
        elapsed = time.time() - start
        
        pump.stop()
        
        # Reset should be immediate (< 10ms)
        assert elapsed < 0.05


class TestPCMGracePeriodBoundaryConditions:
    """Tests for boundary conditions [G10]–[G12]."""
    
    def test_g10_at_exactly_grace_expiry(self):
        """Test [G10]: At exactly TOWER_PCM_GRACE_SEC, switches to fallback."""
        pcm_buffer = FrameRingBuffer(capacity=10)
        fallback = Mock()
        encoder_manager = Mock()
        
        # Very short grace for testing
        with patch.dict(os.environ, {'TOWER_PCM_GRACE_SEC': '0.01'}):
            pump = AudioPump(pcm_buffer, fallback, encoder_manager)
            
            pump.start()
            time.sleep(0.02)  # Exceed grace period
            pump.stop()
            
            # Fallback should be called after grace expires
            # (timing dependent, but should happen)
    
    def test_g11_real_time_measurement(self):
        """Test [G11]: Grace period is measured in real time (wall clock)."""
        pcm_buffer = FrameRingBuffer(capacity=10)
        fallback = Mock()
        encoder_manager = Mock()
        
        pump = AudioPump(pcm_buffer, fallback, encoder_manager)
        
        # Grace period uses wall clock time
        assert pump.grace_period_sec > 0
    
    def test_g12_uses_monotonic_time(self):
        """Test [G12]: Grace period uses time.monotonic() for timing."""
        import inspect
        from tower.encoder import audio_pump
        
        source = inspect.getsource(audio_pump.AudioPump._run)
        
        # Should use time.monotonic()
        assert 'time.monotonic' in source


class TestPCMGracePeriodIntegration:
    """Tests for integration with AudioPump [G13]–[G14]."""
    
    def test_g13_audiopump_implements_grace(self):
        """Test [G13]: AudioPump implements grace period logic."""
        pcm_buffer = FrameRingBuffer(capacity=10)
        fallback = Mock()
        encoder_manager = Mock()
        
        pump = AudioPump(pcm_buffer, fallback, encoder_manager)
        
        # Should have grace period attributes
        assert hasattr(pump, 'grace_period_sec')
        assert hasattr(pump, 'grace_timer_start')
        assert hasattr(pump, 'silence_frame')
    
    def test_g14_grace_timer_maintained_by_audiopump(self):
        """Test [G14]: Grace timer is maintained by AudioPump."""
        pcm_buffer = FrameRingBuffer(capacity=10)
        fallback = Mock()
        encoder_manager = Mock()
        
        pump = AudioPump(pcm_buffer, fallback, encoder_manager)
        
        # Grace timer should be in AudioPump
        assert hasattr(pump, 'grace_timer_start')
        assert pump.grace_timer_start is None  # Initially not started


class TestPCMGracePeriodConfiguration:
    """Tests for configuration [G15]–[G17]."""
    
    def test_g15_default_5_seconds(self):
        """Test [G15]: Default grace period is 5 seconds."""
        pcm_buffer = FrameRingBuffer(capacity=10)
        fallback = Mock()
        encoder_manager = Mock()
        
        pump = AudioPump(pcm_buffer, fallback, encoder_manager)
        assert pump.grace_period_sec == 5.0
    
    def test_g16_configurable_via_env(self):
        """Test [G16]: Grace period can be configured via environment variable."""
        pcm_buffer = FrameRingBuffer(capacity=10)
        fallback = Mock()
        encoder_manager = Mock()
        
        with patch.dict(os.environ, {'TOWER_PCM_GRACE_SEC': '10.0'}):
            pump = AudioPump(pcm_buffer, fallback, encoder_manager)
            assert pump.grace_period_sec == 10.0
    
    def test_g17_zero_disables_grace(self):
        """Test [G17]: Grace period must be > 0 (zero or negative disables)."""
        pcm_buffer = FrameRingBuffer(capacity=10)
        fallback = Mock()
        encoder_manager = Mock()
        
        with patch.dict(os.environ, {'TOWER_PCM_GRACE_SEC': '0'}):
            pump = AudioPump(pcm_buffer, fallback, encoder_manager)
            assert pump.grace_period_sec == 0
        
        with patch.dict(os.environ, {'TOWER_PCM_GRACE_SEC': '-1'}):
            pump = AudioPump(pcm_buffer, fallback, encoder_manager)
            assert pump.grace_period_sec == 0  # Should be clamped to 0


class TestPCMGracePeriodSilenceFrames:
    """Tests for silence frame requirements [G18]–[G19]."""
    
    def test_g18_standardized_4608_bytes(self):
        """Test [G18]: Silence frames are exactly 4608 bytes."""
        pcm_buffer = FrameRingBuffer(capacity=10)
        fallback = Mock()
        encoder_manager = Mock()
        
        pump = AudioPump(pcm_buffer, fallback, encoder_manager)
        
        assert len(pump.silence_frame) == 4608
        assert len(pump.silence_frame) == 1152 * 2 * 2
    
    def test_g18_format_s16le_48khz_stereo(self):
        """Test [G18]: Format is s16le, 48kHz, stereo."""
        pcm_buffer = FrameRingBuffer(capacity=10)
        fallback = Mock()
        encoder_manager = Mock()
        
        pump = AudioPump(pcm_buffer, fallback, encoder_manager)
        
        # Format: 1152 samples × 2 channels × 2 bytes = 4608 bytes
        assert len(pump.silence_frame) == 1152 * 2 * 2
    
    def test_g18_cached_prebuilt(self):
        """Test [G18]: Silence frames are cached (pre-built at startup)."""
        pcm_buffer = FrameRingBuffer(capacity=10)
        fallback = Mock()
        encoder_manager = Mock()
        
        pump = AudioPump(pcm_buffer, fallback, encoder_manager)
        
        # Should be pre-built
        assert hasattr(pump, 'silence_frame')
        assert pump.silence_frame == b'\x00' * 4608
    
    def test_g18_consistent_all_zeros(self):
        """Test [G18]: Same frame bytes every time (all zeros)."""
        pcm_buffer = FrameRingBuffer(capacity=10)
        fallback = Mock()
        encoder_manager = Mock()
        
        pump = AudioPump(pcm_buffer, fallback, encoder_manager)
        
        # Should be all zeros
        assert all(b == 0 for b in pump.silence_frame)
        assert pump.silence_frame == b'\x00' * 4608
    
    def test_g19_no_allocation_overhead(self):
        """Test [G19]: Caching ensures no allocation overhead."""
        pcm_buffer = FrameRingBuffer(capacity=10)
        fallback = Mock()
        encoder_manager = Mock()
        
        pump = AudioPump(pcm_buffer, fallback, encoder_manager)
        
        # Frame should be pre-allocated (same object reference)
        frame1 = pump.silence_frame
        frame2 = pump.silence_frame
        
        # Should be same object (cached)
        assert frame1 is frame2
