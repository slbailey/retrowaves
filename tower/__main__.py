#!/usr/bin/env python3
"""
Tower main entry point.

Allows Tower to be run as a module: python3 -m tower
"""

import logging
import os
import sys

# Set default log level from environment, or INFO if not set
log_level = os.getenv("TOWER_LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, log_level, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)

# Suppress verbose DEBUG logs from specific modules even if DEBUG is enabled
logging.getLogger("tower.fallback.generator").setLevel(logging.INFO)

from tower.service import TowerService

if __name__ == "__main__":
    try:
        tower = TowerService()
        tower.start()
        tower.run_forever()
    except KeyboardInterrupt:
        logging.info("Tower shutdown requested")
        sys.exit(0)
    except Exception as e:
        logging.error(f"Tower failed to start: {e}", exc_info=True)
        sys.exit(1)






