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
    # Need parent directory (/opt/retrowaves) in path for station.* imports
    project_root = Path(__file__).parent.parent.parent
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))
    from station.app.station import Station

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
    
    # Track if shutdown has been initiated (per SL2.2.4: idempotent shutdown)
    shutdown_initiated = False
    
    # Set up signal handlers for graceful shutdown (per SL2.1)
    def signal_handler(sig, frame):
        nonlocal shutdown_initiated
        if shutdown_initiated:
            logger.debug("[STATION] Shutdown already in progress, ignoring duplicate signal")
            return
        
        shutdown_initiated = True
        signal_name = "SIGTERM" if sig == signal.SIGTERM else "SIGINT"
        logger.info(f"\n[STATION] Received {signal_name} signal - initiating graceful shutdown")
        
        # Per SL2.1: All shutdown triggers (SIGTERM, SIGINT, stop()) MUST be treated identically
        # Call station.stop() which implements two-phase shutdown
        # Note: This is synchronous and will block until shutdown completes
        try:
            station.stop()
            logger.info("[STATION] Shutdown complete, exiting")
        except Exception as e:
            logger.error(f"[STATION] Error during shutdown: {e}", exc_info=True)
        finally:
            # Force exit even if shutdown had issues
            sys.exit(0)
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    try:
        # Start station (includes HTTP streaming server if enabled)
        station.start()
        
        # Run continuously until interrupted or shutdown
        logger.info("[STATION] Station running. Press Ctrl+C to stop.")
        try:
            while station.running and not shutdown_initiated:
                time.sleep(0.1)  # Shorter sleep for more responsive shutdown
            
            # If shutdown was initiated, exit immediately
            if shutdown_initiated:
                logger.debug("[STATION] Shutdown initiated, main loop exiting")
                return
        except KeyboardInterrupt:
            # This should rarely be hit since signal handler should catch SIGINT
            # But handle it gracefully if it does
            logger.info("\n[STATION] Interrupted by user (KeyboardInterrupt)")
            if not shutdown_initiated:
                shutdown_initiated = True
                try:
                    station.stop()
                    logger.info("[STATION] Shutdown complete, exiting")
                except Exception as e:
                    logger.error(f"[STATION] Error during shutdown: {e}", exc_info=True)
                finally:
                    sys.exit(0)
        
    except Exception as e:
        logger.error(f"[STATION] Error: {e}", exc_info=True)
        raise
    finally:
        # Stop station (saves state, closes connections) if not already stopped
        if not shutdown_initiated:
            station.stop()


if __name__ == "__main__":
    main()
