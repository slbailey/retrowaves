"""
Example Tower bootstrap showing Phase 4 integration.

This file demonstrates how to integrate all Phase 4 components:
- AudioInputRouter
- FallbackGenerator
- AudioPump
- EncoderManager
- BroadcastLoop

This is an example - actual Tower service may have additional components.
"""

import logging
import os
from typing import Optional

from tower.audio.input_router import AudioInputRouter
from tower.audio.ring_buffer import FrameRingBuffer
from tower.broadcast.loop import BroadcastLoop
from tower.encoder.audio_pump import AudioPump
from tower.encoder.encoder_manager import EncoderManager
from tower.fallback.generator import FallbackGenerator

logger = logging.getLogger(__name__)


def create_tower_components():
    """
    Create and initialize all Tower Phase 4 components.
    
    Returns:
        dict: Dictionary containing all initialized components
    """
    # Read configuration from environment
    pcm_buffer_size = int(os.getenv("TOWER_PCM_BUFFER_SIZE", "100"))
    mp3_buffer_capacity = int(os.getenv("TOWER_MP3_BUFFER_CAPACITY_FRAMES", "400"))
    stall_threshold_ms = int(os.getenv("TOWER_ENCODER_STALL_THRESHOLD_MS", "2000"))
    
    # Create buffers
    pcm_buffer = FrameRingBuffer(capacity=pcm_buffer_size)
    mp3_buffer = FrameRingBuffer(capacity=mp3_buffer_capacity)
    
    # Create AudioInputRouter (PCM input from Station)
    router = AudioInputRouter(capacity=pcm_buffer_size)
    
    # Create FallbackGenerator (fallback audio when no live PCM)
    fallback = FallbackGenerator()
    
    # Create EncoderManager (FFmpeg encoder lifecycle)
    encoder_manager = EncoderManager(
        pcm_buffer=pcm_buffer,
        mp3_buffer=mp3_buffer,
        stall_threshold_ms=stall_threshold_ms,
    )
    
    # Create AudioPump (pumps PCM frames to encoder at 21.333ms intervals)
    audio_pump = AudioPump(
        router=router,
        encoder_manager=encoder_manager,
        fallback=fallback,
    )
    
    # Create BroadcastLoop (broadcasts MP3 frames to HTTP clients at 15ms intervals)
    # Note: connection_manager would be created separately (HTTP server component)
    # For this example, we'll use None and it should be set before starting
    broadcast_loop = None  # Will be set after connection_manager is created
    
    return {
        "router": router,
        "fallback": fallback,
        "encoder_manager": encoder_manager,
        "audio_pump": audio_pump,
        "broadcast_loop": broadcast_loop,
        "pcm_buffer": pcm_buffer,
        "mp3_buffer": mp3_buffer,
    }


def start_tower(components: dict, connection_manager) -> None:
    """
    Start all Tower components.
    
    Args:
        components: Dictionary of components from create_tower_components()
        connection_manager: HTTPConnectionManager instance
    """
    logger.info("Starting Tower components...")
    
    # Start EncoderManager (starts FFmpeg process and drain thread)
    components["encoder_manager"].start()
    logger.info("EncoderManager started")
    
    # Start AudioPump (pumps PCM frames to encoder)
    components["audio_pump"].start()
    logger.info("AudioPump started")
    
    # Create and start BroadcastLoop
    broadcast_loop = BroadcastLoop(
        encoder_manager=components["encoder_manager"],
        connection_manager=connection_manager,
    )
    components["broadcast_loop"] = broadcast_loop
    broadcast_loop.start()
    logger.info("BroadcastLoop started")
    
    logger.info("All Tower components started")


def stop_tower(components: dict) -> None:
    """
    Stop all Tower components gracefully.
    
    Args:
        components: Dictionary of components from create_tower_components()
    """
    logger.info("Stopping Tower components...")
    
    # Stop BroadcastLoop
    if components["broadcast_loop"]:
        components["broadcast_loop"].stop(timeout=2.0)
        logger.info("BroadcastLoop stopped")
    
    # Stop AudioPump
    components["audio_pump"].stop(timeout=2.0)
    logger.info("AudioPump stopped")
    
    # Stop EncoderManager
    components["encoder_manager"].stop(timeout=5.0)
    logger.info("EncoderManager stopped")
    
    logger.info("All Tower components stopped")


# Example usage:
if __name__ == "__main__":
    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # Create components
    components = create_tower_components()
    
    # Mock connection manager for example
    class MockConnectionManager:
        def broadcast(self, data: bytes) -> None:
            logger.debug(f"Broadcasting {len(data)} bytes to clients")
    
    connection_manager = MockConnectionManager()
    
    # Start Tower
    try:
        start_tower(components, connection_manager)
        logger.info("Tower running... Press Ctrl+C to stop")
        
        # Keep running until interrupted
        import time
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Shutting down...")
    finally:
        stop_tower(components)

