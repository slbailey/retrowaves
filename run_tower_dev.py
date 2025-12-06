#!/usr/bin/env python3

"""
Temporary dev runner for the refactored Tower architecture.
Allows testing without Station, so fallback tone → MP3 chain can be validated.
"""
import logging
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)

from tower.service import TowerService

if __name__ == "__main__":
    tower = TowerService()
    tower.start()
    tower.run_forever()
