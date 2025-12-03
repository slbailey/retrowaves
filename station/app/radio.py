"""
Main entry point for Appalachia Radio 3.2.

This module provides the main() function that initializes all components
according to Architecture 3.2 and starts the station with HTTP streaming.

Architecture 3.2 Reference:
- Section 3: System Lifecycle Events
- Section 5: Updated Playout Engine Flow
"""

import logging
import signal
import sys
import time
from pathlib import Path
from typing import Optional

# Use relative import when running as module, absolute when running directly
try:
    from .station import Station
except ImportError:
    # Fallback for direct execution
    import sys
    from pathlib import Path
    station_dir = Path(__file__).parent.parent
    if str(station_dir) not in sys.path:
        sys.path.insert(0, str(station_dir))
    from app.station import Station

logger = logging.getLogger(__name__)


# Station class is now imported from app.station


def main(args: Optional[list[str]] = None) -> None:
    """
    Main entry point for Appalachia Radio 3.2.
    
    Initializes components, starts the station with HTTP streaming, and runs continuously.
    """
    # Initialize logging with clear format
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    logger.info("\n" + "=" * 70)
    logger.info("Appalachia Radio 3.2 - Starting Station")
    logger.info("=" * 70 + "\n")
    
    # Create station instance (includes HTTP streaming if enabled)
    station = Station()
    
    # Set up signal handlers for graceful shutdown
    def signal_handler(sig, frame):
        logger.info("\n[STATION] Received shutdown signal")
        station.stop()
        sys.exit(0)
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    try:
        # Start station (includes HTTP streaming server if enabled)
        station.start()
        
        # Run continuously until interrupted
        logger.info("[STATION] Station running. Press Ctrl+C to stop.")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            logger.info("\n[STATION] Interrupted by user")
        
    except Exception as e:
        logger.error(f"[STATION] Error: {e}", exc_info=True)
        raise
    finally:
        # Stop station (saves state, closes connections)
        station.stop()


if __name__ == "__main__":
    main()
