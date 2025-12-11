#!/usr/bin/env python3

"""
Temporary dev runner for the refactored Tower architecture.
Allows testing without Station, so fallback tone → MP3 chain can be validated.
"""
import logging
import os
import sys

def _load_dotenv_simple(dotenv_path: str = None) -> None:
    """
    Simple .env file loader (no external dependencies).
    Loads KEY=VALUE pairs from a file, skipping comments and empty lines.
    """
    if dotenv_path is None:
        # Try tower/tower.env first, then .env in project root
        dotenv_path = os.path.join(os.path.dirname(__file__), "tower", "tower.env")
        if not os.path.exists(dotenv_path):
            dotenv_path = os.path.join(os.path.dirname(__file__), ".env")
    
    if not os.path.exists(dotenv_path):
        return
    
    try:
        with open(dotenv_path, "r") as f:
            for line in f:
                line = line.strip()
                # Skip comments and empty lines
                if not line or line.startswith("#"):
                    continue
                # Parse KEY=VALUE
                if "=" in line:
                    key, value = line.split("=", 1)
                    key = key.strip()
                    value = value.strip().strip('"').strip("'")  # Remove quotes if present
                    # Only set if not already in environment (env vars take precedence)
                    if key and key not in os.environ:
                        os.environ[key] = value
    except Exception as e:
        logging.warning(f"Failed to load .env file {dotenv_path}: {e}")

# Load environment variables from tower.env file
_load_dotenv_simple()

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
