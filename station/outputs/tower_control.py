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
    - Sending heartbeat events
    
    This client is stateless and transport-only. It makes no decisions about
    when to send events - it simply sends whatever it's asked to send.
    Lifecycle state management is handled by Station, not this client.
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
        
        # Suppress httpx INFO level logging (reduce noise from frequent buffer polling)
        httpx_logger = logging.getLogger("httpx")
        httpx_logger.setLevel(logging.WARNING)
        
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
    
    def get_buffer(self) -> Optional[Dict[str, Any]]:
        """
        Get Tower ring buffer status.
        
        Returns:
            Buffer dict with 'fill' and 'capacity' keys, or None if request failed
        """
        url = f"{self.base_url}/tower/buffer"
        
        try:
            response = httpx.get(url, timeout=self.timeout)
            response.raise_for_status()
            buffer_data = response.json()
            
            # Debug logging: log what we received from Tower
            if buffer_data:
                fill = buffer_data.get("fill")
                capacity = buffer_data.get("capacity")
                if fill is not None and capacity is not None:
                    fill_pct = (fill / capacity * 100) if capacity > 0 else 0.0
                    logger.debug(
                        f"[TOWER_BUFFER_TELEMETRY] Received: fill={fill}/{capacity} ({fill_pct:.1f}%)"
                    )
                else:
                    logger.debug(f"[TOWER_BUFFER_TELEMETRY] Received incomplete data: {buffer_data}")
            else:
                logger.debug(f"[TOWER_BUFFER_TELEMETRY] Received empty/null response")
            
            return buffer_data
        except httpx.HTTPError as e:
            logger.debug(f"[TOWER] Failed to get buffer status: {e}")
            return None
        except Exception as e:
            logger.debug(f"[TOWER] Unexpected error getting buffer status: {e}")
            return None
    
    def send_event(self, event_type: str, timestamp: float, metadata: Dict[str, Any]) -> bool:
        """
        Send a Station heartbeat event to Tower's event ingestion endpoint.
        
        Per contract T-EVENTS1: Events are sent via HTTP POST to /tower/events/ingest.
        Per contract T-EVENTS6: Event sending MUST be non-blocking (< 1ms typical, < 10ms maximum).
        
        This method is stateless and transport-only. It always attempts to send the event
        if called. Lifecycle event de-duplication is handled by Station, not this client.
        
        Args:
            event_type: Event type (e.g., "segment_started", "dj_think_started", "station_starting_up")
            timestamp: Station Clock A timestamp (time.monotonic())
            metadata: Event metadata dictionary
            
        Returns:
            True if event was sent successfully, False otherwise
        """
        url = f"{self.base_url}/tower/events/ingest"
        
        payload = {
            "event_type": event_type,
            "timestamp": timestamp,
            "metadata": metadata
        }
        
        try:
            # Use a very short timeout to ensure non-blocking behavior per T-EVENTS6
            response = httpx.post(url, json=payload, timeout=0.1)  # 100ms timeout for non-blocking
            response.raise_for_status()
            return True
        except (httpx.HTTPError, httpx.TimeoutException) as e:
            # Silently drop events if Tower is unavailable (non-blocking per T-EVENTS6)
            logger.debug(f"[TOWER] Failed to send event {event_type}: {e}")
            return False
        except Exception as e:
            logger.debug(f"[TOWER] Unexpected error sending event {event_type}: {e}")
            return False

