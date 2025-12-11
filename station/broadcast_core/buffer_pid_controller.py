"""
Buffer PID Controller for Adaptive Clock A Pacing (PE6).

Implements optional adaptive buffer management with PID controller per
PLAYOUT_ENGINE_CONTRACT.md PE6.

This controller adjusts Clock A decode pacing based on Tower buffer status
to maintain target buffer fill level while preserving all architectural invariants.
"""

import logging
import threading
import time
from typing import Optional, Dict, Any

import httpx

logger = logging.getLogger(__name__)


class BufferPIDController:
    """
    PID controller for adaptive Clock A decode pacing.
    
    Per PE6: Adjusts decode sleep duration based on Tower buffer status
    to maintain target buffer fill ratio while preserving:
    - Clock A remains decode metronome
    - Clock B unchanged (Tower AudioPump)
    - Segment timing wall-clock based
    - Socket writes non-blocking
    """
    
    def __init__(
        self,
        tower_host: str = "127.0.0.1",
        tower_port: int = 8005,
        kp: float = 0.1,
        ki: float = 0.01,
        kd: float = 0.05,
        target_ratio: float = 0.5,
        min_sleep: float = 0.0,
        max_sleep: float = 0.1,
        integral_windup_limit: float = 10.0,
        update_interval: float = 0.5,
        query_timeout: float = 0.1,
        enabled: bool = True,
    ):
        """
        Initialize PID controller.
        
        Args:
            tower_host: Tower HTTP server host
            tower_port: Tower HTTP server port
            kp: Proportional gain (default: 0.1)
            ki: Integral gain (default: 0.01)
            kd: Derivative gain (default: 0.05)
            target_ratio: Target buffer fill ratio (default: 0.5)
            min_sleep: Minimum sleep duration in seconds (default: 0.0)
            max_sleep: Maximum sleep duration in seconds (default: 0.1)
            integral_windup_limit: Integral windup limit (default: 10.0)
            update_interval: Buffer status update interval in seconds (default: 0.5)
            query_timeout: HTTP query timeout in seconds (default: 0.1)
            enabled: Whether PID controller is enabled (default: True)
        """
        # PE6.3: Configuration Parameters
        self.kp = kp
        self.ki = ki
        self.kd = kd
        self.target_ratio = target_ratio
        self.min_sleep = min_sleep
        self.max_sleep = max_sleep
        self.integral_windup_limit = integral_windup_limit
        self.update_interval = update_interval
        self.query_timeout = query_timeout
        self.enabled = enabled
        
        # PE6.4: Initialization
        self.integral_sum = 0.0
        self.previous_error = 0.0
        self.base_frame_duration = 21.333 / 1000.0  # 21.333 ms in seconds
        self.last_update_time = time.monotonic()
        self.last_buffer_status: Optional[Dict[str, Any]] = None
        
        # PE6.6: Performance metrics
        self.query_count = 0
        self.query_failures = 0
        self.limit_hits = 0
        self.windup_events = 0
        
        # Thread safety
        self._lock = threading.RLock()  # Reentrant lock for nested calls
        self._polling_lock = threading.Lock()  # Lock for polling state
        
        # Tower connection
        self.tower_host = tower_host
        self.tower_port = tower_port
        self.base_url = f"http://{tower_host}:{tower_port}"
        
        # Polling state
        self._last_poll_time = 0.0
        self._polling_in_progress = False
        
        # Suppress httpx INFO level logging
        httpx_logger = logging.getLogger("httpx")
        httpx_logger.setLevel(logging.WARNING)
        
        logger.info(
            f"BufferPIDController initialized (enabled={enabled}, "
            f"target_ratio={target_ratio}, kp={kp}, ki={ki}, kd={kd})"
        )
    
    def get_sleep_duration(self, now: float) -> float:
        """
        Get sleep duration based on PID calculation.
        
        PE6.2: PID Controller Algorithm
        PE6.4: Thread-safe read
        
        NOTE: This method returns absolute sleep duration for backward compatibility with tests.
        In production, use get_sleep_adjustment() and add to Clock A base sleep.
        
        Args:
            now: Current time (time.monotonic())
            
        Returns:
            Sleep duration in seconds (clamped to min_sleep/max_sleep)
        """
        adjustment = self.get_sleep_adjustment(now)
        return self.base_frame_duration + adjustment
    
    def get_sleep_adjustment(self, now: float) -> float:
        """
        Get sleep adjustment (not absolute duration) based on PID calculation.
        
        PE6.2: PID Controller Algorithm
        PE6.4: Thread-safe read
        PE6.5: PID adjusts Clock A pacing, does not replace it
        
        Args:
            now: Current time (time.monotonic())
            
        Returns:
            Sleep adjustment in seconds (can be positive or negative)
            This is added to Clock A's base sleep duration
        """
        with self._lock:
            # PE6.8: If disabled, return zero adjustment (use Clock A only)
            if not self.enabled:
                return 0.0
            
            # PE6.4: Fallback to zero adjustment if no buffer status
            if self.last_buffer_status is None:
                return 0.0
            
            # PE6.2: Calculate error
            # Get ratio from buffer status, calculating if missing
            if "ratio" in self.last_buffer_status:
                current_ratio = self.last_buffer_status["ratio"]
            elif "fill" in self.last_buffer_status and "capacity" in self.last_buffer_status:
                # Calculate ratio from fill/capacity if ratio not provided
                capacity = self.last_buffer_status.get("capacity", 1)
                if capacity > 0:
                    current_ratio = self.last_buffer_status.get("fill", 0) / capacity
                else:
                    current_ratio = 0.0
            else:
                # Fallback if neither ratio nor fill/capacity available
                current_ratio = 0.5
            
            # Ensure ratio is between 0.0 and 1.0
            current_ratio = max(0.0, min(1.0, current_ratio))
            error = self.target_ratio - current_ratio
            
            # PE6.2: Calculate P term
            p_term = self.kp * error
            
            # PE6.2: Calculate I term (with windup prevention)
            dt = now - self.last_update_time
            
            # PE6.2: Handle dt edge cases
            if dt <= 0:
                # dt = 0 or negative: skip I and D terms
                i_term = 0.0
                d_term = 0.0
            else:
                # Update integral sum
                self.integral_sum += error * dt
                
                # PE6.2: Windup prevention
                if abs(self.integral_sum) > self.integral_windup_limit:
                    self.integral_sum = (
                        self.integral_windup_limit if self.integral_sum > 0
                        else -self.integral_windup_limit
                    )
                    self.windup_events += 1
                
                i_term = self.ki * self.integral_sum
                
                # PE6.2: Calculate D term
                # Handle small dt: clamp derivative to prevent explosion
                # Handle large dt: derivative may be stale, but still calculate
                if dt < 0.001:  # Very small dt (< 1ms)
                    # Disable D term for extremely small dt to prevent explosion
                    d_term = 0.0
                else:
                    # Normal D term calculation
                    d_term = self.kd * (error - self.previous_error) / dt
                    # Clamp D term to prevent extreme values
                    max_d_term = 0.1  # Reasonable limit for D term
                    if abs(d_term) > max_d_term:
                        d_term = max_d_term if d_term > 0 else -max_d_term
            
            # PE6.2: Combined PID output
            # When buffer is low (positive error): increase sleep (slow decode) so Tower catches up
            # When buffer is high (negative error): decrease sleep (fast decode) so Tower drains
            sleep_adjustment = p_term + i_term + d_term
            adjusted_sleep = self.base_frame_duration + sleep_adjustment
            
            # PE6.3: Clamp adjustment to reasonable limits
            # Adjustment is relative to base_frame_duration, so clamp to prevent extreme values
            max_adjustment = self.max_sleep - self.base_frame_duration
            min_adjustment = self.min_sleep - self.base_frame_duration
            sleep_adjustment = max(min_adjustment, min(sleep_adjustment, max_adjustment))
            
            # Track if adjustment hit limits
            if sleep_adjustment == min_adjustment or sleep_adjustment == max_adjustment:
                self.limit_hits += 1
            
            # Update state
            self.previous_error = error
            self.last_update_time = now
            
            return sleep_adjustment
    
    def update_buffer_status(self, buffer_status: Optional[Dict[str, Any]]) -> None:
        """
        Update buffer status (non-blocking).
        
        PE6.4: Non-blocking buffer queries
        
        Args:
            buffer_status: Buffer status dict from /tower/buffer or None if unavailable
        """
        with self._lock:
            self.query_count += 1
            
            if buffer_status is None:
                self.query_failures += 1
                # PE6.4: Fallback behavior - reset integral on unavailability
                if self.last_buffer_status is None:
                    # No previous status: reset integral
                    self.integral_sum = 0.0
                # Keep last_buffer_status for last-known-value behavior
            else:
                # Update buffer status
                self.last_buffer_status = buffer_status
    
    def poll_buffer_status(self) -> Optional[Dict[str, Any]]:
        """
        Poll Tower buffer status endpoint (non-blocking with timeout).
        
        PE6.4: Non-blocking queries with timeout
        PE6.5: Periodic updates
        
        Returns:
            Buffer status dict or None if unavailable/timed out
        """
        # PE6.5: Use last known status if query in progress
        with self._polling_lock:
            if self._polling_in_progress:
                with self._lock:
                    return self.last_buffer_status
            
            # Check if enough time has passed since last poll
            now = time.monotonic()
            if now - self._last_poll_time < self.update_interval:
                with self._lock:
                    return self.last_buffer_status
            
            # Mark polling in progress
            self._polling_in_progress = True
            self._last_poll_time = now
        
        try:
            # PE6.4: Non-blocking query with timeout
            url = f"{self.base_url}/tower/buffer"
            
            try:
                # Use httpx with timeout
                with httpx.Client(timeout=self.query_timeout) as client:
                    response = client.get(url)
                    response.raise_for_status()
                    buffer_data = response.json()
                    
                    # PE6.4: Validate response format
                    if not isinstance(buffer_data, dict):
                        logger.warning(f"[PID] Invalid buffer response format: {buffer_data}")
                        return None
                    
                    # Extract ratio (required field per T-BUF2)
                    # If ratio is missing, calculate it from fill/capacity
                    if "ratio" not in buffer_data:
                        if "fill" in buffer_data and "capacity" in buffer_data:
                            capacity = buffer_data.get("capacity", 1)
                            if capacity > 0:
                                buffer_data["ratio"] = buffer_data.get("fill", 0) / capacity
                            else:
                                buffer_data["ratio"] = 0.0
                        else:
                            logger.warning(f"[PID] Buffer response missing 'ratio' and cannot calculate from fill/capacity: {buffer_data}")
                            return None
                    
                    # Ensure ratio is between 0.0 and 1.0
                    buffer_data["ratio"] = max(0.0, min(1.0, buffer_data["ratio"]))
                    
                    # Update buffer status
                    self.update_buffer_status(buffer_data)
                    return buffer_data
                    
            except httpx.TimeoutException:
                logger.debug(f"[PID] Buffer query timeout ({self.query_timeout}s)")
                self.update_buffer_status(None)
                return None
            except httpx.HTTPError as e:
                logger.debug(f"[PID] Buffer query failed: {e}")
                self.update_buffer_status(None)
                return None
            except Exception as e:
                logger.warning(f"[PID] Unexpected error querying buffer: {e}")
                self.update_buffer_status(None)
                return None
                
        finally:
            with self._polling_lock:
                self._polling_in_progress = False
    
    def get_state(self) -> Dict[str, Any]:
        """
        Get PID state for observability.
        
        PE6.6: Observability and Monitoring
        
        Returns:
            Dict with PID state (current_ratio, target_ratio, error, terms, etc.)
        """
        with self._lock:
            current_ratio = (
                self.last_buffer_status.get("ratio", 0.0)
                if self.last_buffer_status else 0.0
            )
            error = self.target_ratio - current_ratio
            
            return {
                "current_ratio": current_ratio,
                "target_ratio": self.target_ratio,
                "error": error,
                "p_term": self.kp * error,
                "i_term": self.ki * self.integral_sum,
                "d_term": 0.0,  # D term requires previous_error, simplified here
                "integral_sum": self.integral_sum,
                "previous_error": self.previous_error,
                "enabled": self.enabled,
            }
    
    def get_metrics(self) -> Dict[str, Any]:
        """
        Get performance metrics.
        
        PE6.6: Observability and Monitoring
        
        Returns:
            Dict with performance metrics
        """
        with self._lock:
            return {
                "query_count": self.query_count,
                "query_failures": self.query_failures,
                "limit_hits": self.limit_hits,
                "windup_events": self.windup_events,
                "enabled": self.enabled,
            }

