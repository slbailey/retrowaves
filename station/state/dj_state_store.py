"""
DJ State Storage for Appalachia Radio 3.1.

Provides atomic, crash-resistant JSON storage for DJ state persistence.
"""

import json
import os
import logging

logger = logging.getLogger(__name__)


class DJStateStore:
    """
    Simple JSON-based state storage with atomic writes.
    
    Uses a temporary file + atomic rename to ensure crash resistance.
    """
    
    def __init__(self, path: str = "/tmp/appalachia_dj_state.json"):
        """
        Initialize state store.
        
        Args:
            path: Path to JSON state file
        """
        self.path = path
        logger.debug(f"DJStateStore initialized with path: {path}")
    
    def save(self, data: dict) -> None:
        """
        Save state to JSON file atomically.
        
        Writes to a temporary file first, then atomically replaces
        the target file to prevent corruption on crashes.
        
        Args:
            data: Dictionary of state data to save
        """
        tmp = self.path + ".tmp"
        try:
            with open(tmp, "w") as f:
                json.dump(data, f, indent=2)
            os.replace(tmp, self.path)
            logger.debug(f"DJ state saved to {self.path}")
        except Exception as e:
            logger.error(f"Failed to save DJ state: {e}")
            # Clean up temp file on error
            try:
                if os.path.exists(tmp):
                    os.remove(tmp)
            except Exception:
                pass
            raise
    
    def load(self) -> dict | None:
        """
        Load state from JSON file.
        
        Returns:
            Dictionary of state data, or None if file doesn't exist or is invalid
        """
        if not os.path.exists(self.path):
            logger.debug(f"No state file found at {self.path}")
            return None
        
        try:
            with open(self.path, "r") as f:
                data = json.load(f)
            logger.debug(f"DJ state loaded from {self.path}")
            return data
        except Exception as e:
            logger.warning(f"Failed to load DJ state: {e}")
            return None

