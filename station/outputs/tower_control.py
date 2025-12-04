"""
Tower Control API Client for Retrowaves Station.

Sends control commands to Tower's HTTP control API (e.g., source switching).
"""

import json
import logging
import os
from typing import Optional, Dict, Any

import httpx

logger = logging.getLogger(__name__)


class TowerControlClient:
    """
    Client for Tower's HTTP control API.
    
    Allows Station to send commands to Tower, such as:
    - Switching source modes (tone, silence, file)
    - Setting file sources
    """
    
    def __init__(self, tower_host: str = "127.0.0.1", tower_port: int = 8005):
        """
        Initialize Tower control client.
        
        Args:
            tower_host: Tower HTTP server host (default: 127.0.0.1)
            tower_port: Tower HTTP server port (default: 8005)
        """
        self.tower_host = tower_host
        self.tower_port = tower_port
        self.base_url = f"http://{tower_host}:{tower_port}"
        self.timeout = 5.0  # 5 second timeout for API calls
        
        logger.info(f"TowerControlClient initialized (url={self.base_url})")
    
    def switch_source(self, mode: str, file_path: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """
        Switch Tower's source mode.
        
        Args:
            mode: Source mode ("tone", "silence", or "file")
            file_path: File path (required if mode is "file")
            
        Returns:
            Response dict from Tower, or None if request failed
        """
        url = f"{self.base_url}/control/source"
        
        payload = {"mode": mode}
        if mode == "file" and file_path:
            payload["file_path"] = file_path
        
        try:
            response = httpx.post(url, json=payload, timeout=self.timeout)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as e:
            logger.warning(f"[TOWER] Failed to switch source to {mode}: {e}")
            return None
        except Exception as e:
            logger.error(f"[TOWER] Unexpected error switching source: {e}")
            return None
    
    def get_status(self) -> Optional[Dict[str, Any]]:
        """
        Get Tower status.
        
        Returns:
            Status dict from Tower, or None if request failed
        """
        url = f"{self.base_url}/status"
        
        try:
            response = httpx.get(url, timeout=self.timeout)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as e:
            logger.warning(f"[TOWER] Failed to get status: {e}")
            return None
        except Exception as e:
            logger.error(f"[TOWER] Unexpected error getting status: {e}")
            return None

