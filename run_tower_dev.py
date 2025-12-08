#!/usr/bin/env python3

"""
Temporary dev runner for the refactored Tower architecture.
Allows testing without Station, so fallback tone → MP3 chain can be validated.
"""
import logging
import os
import sys

# Set default log level from environment, or INFO if not set
# Use DEBUG only if explicitly requested: LOG_LEVEL=DEBUG python run_tower_dev.py
log_level = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, log_level, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)

# Suppress verbose DEBUG logs from specific modules even if DEBUG is enabled
# These generate too much noise during normal operation
logging.getLogger("tower.fallback.generator").setLevel(logging.INFO)

# Enable DEBUG for AudioPump to see diagnostic messages
# Set LOG_LEVEL=DEBUG to enable, or set this to logging.DEBUG to always enable
if log_level == "DEBUG":
    logging.getLogger("tower.encoder.audio_pump").setLevel(logging.DEBUG)

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
