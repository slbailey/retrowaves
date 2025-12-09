#!/usr/bin/env python3

"""
Temporary dev runner for the refactored Station architecture.
Allows testing Station independently with the new contract-driven service architecture.
"""
import logging
import os
import sys

# Set default log level from environment, or INFO if not set
# Use DEBUG only if explicitly requested: LOG_LEVEL=DEBUG python run_station_dev.py
log_level = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, log_level, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)

# Suppress verbose DEBUG logs from specific modules even if DEBUG is enabled
# These generate too much noise during normal operation
# Add station-specific loggers here if needed

from station.app.station import Station

if __name__ == "__main__":
    try:
        station = Station()
        station.start()
        station.run_forever()
    except KeyboardInterrupt:
        logging.info("Station shutdown requested")
        sys.exit(0)
    except Exception as e:
        logging.error(f"Station failed to start: {e}", exc_info=True)
        sys.exit(1)
