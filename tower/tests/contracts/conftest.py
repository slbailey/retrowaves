"""
Shared pytest fixtures for contract tests.
"""
import pytest
from unittest.mock import Mock

from tower.audio.ring_buffer import FrameRingBuffer
from tower.encoder.encoder_manager import EncoderManager


@pytest.fixture
def components():
    """Create test components for AudioPump tests.
    
    Returns:
        tuple: (pcm_buffer, fallback, encoder_manager)
    """
    pcm_buffer = FrameRingBuffer(capacity=10)
    fallback = Mock()
    fallback.get_frame.return_value = b'\x00' * 4608  # 1152 samples * 2 channels * 2 bytes
    encoder_manager = Mock(spec=EncoderManager)
    encoder_manager.write_pcm = Mock()
    return pcm_buffer, fallback, encoder_manager

