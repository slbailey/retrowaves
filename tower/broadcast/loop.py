"""
Broadcast tick loop for Tower encoding subsystem.

This module provides BroadcastLoop, a tick-driven thread that broadcasts
MP3 frames to all connected HTTP clients at a fixed interval (15ms default).
The loop is oblivious to encoder state and restarts - it simply gets frames
and broadcasts them.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from typing import Optional

from tower.encoder.encoder_manager import EncoderManager

logger = logging.getLogger(__name__)


# Default tick interval: 15ms (~66 ticks/second)
DEFAULT_TICK_INTERVAL_MS = 15
TICK_INTERVAL_SEC = DEFAULT_TICK_INTERVAL_MS / 1000.0


class BroadcastLoop(threading.Thread):
    """
    Tick-driven thread that broadcasts MP3 frames to HTTP clients.
    
    Runs at a fixed interval (15ms default, configurable via
    TOWER_OUTPUT_TICK_INTERVAL_MS). The loop is dumb and simple:
    - get_frame() - always returns valid MP3 frame (never None)
    - broadcast() - sends frame to all connected clients
    - sleep() - waits until next tick
    
    Uses absolute time scheduling to avoid drift. Never blocks indefinitely.
    
    The loop is oblivious to:
    - Encoder states (RUNNING/RESTARTING/FAILED)
    - Restart logic
    - Stall detection
    
    Those are all internal to EncoderManager. The broadcast loop just calls
    get_frame(), broadcasts, and sleeps.
    
    Attributes:
        encoder_manager: EncoderManager to get MP3 frames from
        http_server: HTTPServer to broadcast to (owns client management per NEW_TOWER_RUNTIME_CONTRACT)
        tick_interval_ms: Tick interval in milliseconds
        shutdown_event: Event to signal thread shutdown
    """
    
    def __init__(
        self,
        encoder_manager: EncoderManager,
        http_server,  # HTTPServer (owns client management per NEW_TOWER_RUNTIME_CONTRACT)
        tick_interval_ms: Optional[int] = None,
    ) -> None:
        """
        Initialize broadcast loop.
        
        Args:
            encoder_manager: EncoderManager to get MP3 frames from
            http_server: HTTPServer to broadcast to (owns client management per NEW_TOWER_RUNTIME_CONTRACT)
            tick_interval_ms: Tick interval in milliseconds (default: from env or 15ms)
        """
        super().__init__(name="BroadcastLoop", daemon=False)
        self.encoder_manager = encoder_manager
        self.http_server = http_server
        
        # Read tick interval from environment or use default
        if tick_interval_ms is None:
            env_interval = os.getenv("TOWER_OUTPUT_TICK_INTERVAL_MS")
            if env_interval:
                try:
                    tick_interval_ms = int(env_interval)
                except ValueError:
                    tick_interval_ms = DEFAULT_TICK_INTERVAL_MS
            else:
                tick_interval_ms = DEFAULT_TICK_INTERVAL_MS
        
        if tick_interval_ms <= 0:
            raise ValueError(f"Tick interval must be > 0, got {tick_interval_ms}ms")
        
        self.tick_interval_ms = tick_interval_ms
        self.tick_interval_sec = tick_interval_ms / 1000.0
        self._shutdown_event = threading.Event()
    
    def run(self) -> None:
        """
        Main broadcast loop.
        
        Runs at fixed interval using absolute time scheduling to avoid drift.
        The loop is dumb: get_frame(), broadcast(), sleep().
        
        Oblivious to encoder states, restart logic, and stall detection.
        Those are all internal to EncoderManager.
        """
        logger.info(
            f"Broadcast loop started (tick interval: {self.tick_interval_ms}ms)"
        )
        
        # Absolute time scheduling to avoid drift
        tick_interval = self.tick_interval_sec
        next_tick = time.monotonic()
        
        try:
            while not self._shutdown_event.is_set():
                # Get frame from encoder (always returns valid frame, never None)
                frame = self.encoder_manager.get_frame()
                
                # Broadcast frame to all connected clients via HTTPServer
                # HTTPServer owns client management per NEW_TOWER_RUNTIME_CONTRACT
                self.http_server.broadcast(frame)
                
                # Advance to next tick (absolute time)
                next_tick += tick_interval
                
                # Calculate sleep time
                sleep_time = next_tick - time.monotonic()
                
                if sleep_time > 0:
                    # Sleep until next tick (with early wakeup on shutdown)
                    if self._shutdown_event.wait(timeout=sleep_time):
                        # Shutdown signaled during sleep
                        break
                else:
                    # We're behind; log and resync
                    logger.warning(
                        f"Broadcast loop behind schedule: "
                        f"{(-sleep_time * 1000):.1f}ms behind. Resyncing."
                    )
                    next_tick = time.monotonic()
        
        except Exception as e:
            logger.error(f"Unexpected error in broadcast loop: {e}", exc_info=True)
        finally:
            logger.info("Broadcast loop stopped")
    
    
    def stop(self, timeout: float = 2.0) -> None:
        """
        Stop the broadcast loop gracefully.
        
        Signals shutdown and waits for thread to exit.
        
        Args:
            timeout: Maximum time to wait for thread to stop (seconds)
        """
        logger.info("Stopping broadcast loop...")
        self._shutdown_event.set()
        if self.is_alive():
            self.join(timeout=timeout)
            if self.is_alive():
                logger.warning("Broadcast loop thread did not stop within timeout")
            else:
                logger.info("Broadcast loop stopped")

