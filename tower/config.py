"""
Configuration management for Retrowaves Tower.

Reads configuration from .env file and environment variables with sensible defaults.
"""

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

try:
    from dotenv import load_dotenv
except ImportError:
    # Fallback if python-dotenv not available
    def load_dotenv(dotenv_path=None):
        """No-op if dotenv not available."""
        pass


# Default .env file location
DEFAULT_ENV_FILE = Path("/etc/retrowaves/tower.env")

logger = logging.getLogger(__name__)


def _load_env_file():
    """Load environment variables from .env file if it exists."""
    env_file = os.getenv("TOWER_ENV_FILE", str(DEFAULT_ENV_FILE))
    env_path = Path(env_file)
    
    if env_path.exists():
        load_dotenv(env_path, override=False)  # Don't override existing env vars


def _parse_backoff_schedule(backoff_str: str) -> List[int]:
    """
    Parse encoder backoff schedule from comma-separated string.
    
    Args:
        backoff_str: Comma-separated list of milliseconds (e.g., "1000,2000,4000")
        
    Returns:
        List of backoff delays in milliseconds
        
    Raises:
        ValueError: If parsing fails or values are invalid
    """
    if not backoff_str:
        raise ValueError("Backoff schedule cannot be empty")
    
    try:
        delays = [int(x.strip()) for x in backoff_str.split(",")]
        if not delays:
            raise ValueError("Backoff schedule must contain at least one value")
        if any(d <= 0 for d in delays):
            raise ValueError("All backoff delays must be positive")
        return delays
    except ValueError as e:
        if "invalid literal" in str(e) or "could not convert" in str(e):
            raise ValueError(f"Invalid backoff schedule format: {backoff_str} (must be comma-separated integers)")
        raise


@dataclass
class TowerConfig:
    """Tower configuration loaded from .env file and environment variables."""
    
    # Server settings
    host: str = "0.0.0.0"
    port: int = 8005
    
    # Audio encoding
    bitrate: str = "128k"
    tone_frequency: float = 440.0
    read_chunk_size: int = 8192
    
    # Phase 2: Source configuration
    default_source: str = "tone"
    default_file_path: Optional[str] = None
    
    # Phase 3: Unix socket configuration
    socket_path: str = "/var/run/retrowaves/pcm.sock"
    router_idle_timeout_sec: int = 30  # Timeout before marking router as dead
    pcm_grace_sec: int = 5  # Grace period before switching to tone fallback
    
    # Phase 4: Slow-client policy
    client_timeout_ms: int = 250
    client_buffer_bytes: int = 65536
    
    # Encoder / restart
    encoder_backoff_ms: List[int] = field(
        default_factory=lambda: [1000, 2000, 4000, 8000, 10000]
    )
    encoder_max_restarts: int = 5
    
    # Silence MP3 path (Phase 4 FAILED state)
    silence_mp3_path: Optional[str] = None
    
    # Logging
    log_level: str = "INFO"
    
    # Testing/dev
    test_mode: bool = False
    force_slow_client_test: bool = False
    
    # Audio format constants (canonical format - not configurable)
    sample_rate: int = 48000
    channels: int = 2
    frame_size: int = 1024  # samples per frame
    bytes_per_sample: int = 2  # s16le = 2 bytes per sample
    
    @property
    def frame_bytes(self) -> int:
        """Calculate frame size in bytes."""
        return self.frame_size * self.channels * self.bytes_per_sample  # 4096 bytes
    
    @classmethod
    def load_config(cls) -> "TowerConfig":
        """
        Load configuration from environment variables.
        
        Returns:
            TowerConfig instance with loaded values
            
        Raises:
            ValueError: If configuration is invalid
        """
        # Load .env file first (if it exists)
        _load_env_file()
        
        # Server settings
        host = os.getenv("TOWER_HOST", "0.0.0.0")
        port_str = os.getenv("TOWER_PORT", "8005")
        try:
            port = int(port_str)
        except ValueError:
            raise ValueError(f"Invalid TOWER_PORT: {port_str} (must be an integer)")
        
        # Audio encoding
        bitrate = os.getenv("TOWER_BITRATE", "128k")
        tone_frequency_str = os.getenv("TOWER_TONE_FREQUENCY", "440")
        try:
            tone_frequency = float(tone_frequency_str)
        except ValueError:
            raise ValueError(f"Invalid TOWER_TONE_FREQUENCY: {tone_frequency_str} (must be a number)")
        
        read_chunk_size_str = os.getenv("TOWER_READ_CHUNK_SIZE", "8192")
        try:
            read_chunk_size = int(read_chunk_size_str)
        except ValueError:
            raise ValueError(f"Invalid TOWER_READ_CHUNK_SIZE: {read_chunk_size_str} (must be an integer)")
        
        # Phase 2: Source configuration
        default_source = os.getenv("TOWER_DEFAULT_SOURCE", "tone")
        default_file_path = os.getenv("TOWER_DEFAULT_FILE_PATH")
        
        # Phase 3: Unix socket configuration
        socket_path = os.getenv("TOWER_SOCKET_PATH", "/var/run/retrowaves/pcm.sock")
        router_idle_timeout_sec_str = os.getenv("TOWER_ROUTER_IDLE_TIMEOUT_SEC", "30")
        try:
            router_idle_timeout_sec = int(router_idle_timeout_sec_str)
        except ValueError:
            raise ValueError(f"Invalid TOWER_ROUTER_IDLE_TIMEOUT_SEC: {router_idle_timeout_sec_str} (must be an integer)")
        
        pcm_grace_sec_str = os.getenv("TOWER_PCM_GRACE_SEC", "5")
        try:
            pcm_grace_sec = int(pcm_grace_sec_str)
        except ValueError:
            raise ValueError(f"Invalid TOWER_PCM_GRACE_SEC: {pcm_grace_sec_str} (must be an integer)")
        
        # Phase 4: Slow-client policy
        client_timeout_ms_str = os.getenv("TOWER_CLIENT_TIMEOUT_MS", "250")
        try:
            client_timeout_ms = int(client_timeout_ms_str)
        except ValueError:
            raise ValueError(f"Invalid TOWER_CLIENT_TIMEOUT_MS: {client_timeout_ms_str} (must be an integer)")
        
        client_buffer_bytes_str = os.getenv("TOWER_CLIENT_BUFFER_BYTES", "65536")
        try:
            client_buffer_bytes = int(client_buffer_bytes_str)
        except ValueError:
            raise ValueError(f"Invalid TOWER_CLIENT_BUFFER_BYTES: {client_buffer_bytes_str} (must be an integer)")
        
        # Encoder / restart
        encoder_backoff_ms_str = os.getenv("TOWER_ENCODER_BACKOFF_MS", "1000,2000,4000,8000,10000")
        try:
            encoder_backoff_ms = _parse_backoff_schedule(encoder_backoff_ms_str)
        except ValueError as e:
            raise ValueError(f"Invalid TOWER_ENCODER_BACKOFF_MS: {e}")
        
        encoder_max_restarts_str = os.getenv("TOWER_ENCODER_MAX_RESTARTS", "5")
        try:
            encoder_max_restarts = int(encoder_max_restarts_str)
        except ValueError:
            raise ValueError(f"Invalid TOWER_ENCODER_MAX_RESTARTS: {encoder_max_restarts_str} (must be an integer)")
        
        # Silence MP3 path (Phase 4 FAILED state)
        silence_mp3_path = os.getenv("TOWER_SILENCE_MP3_PATH")
        if silence_mp3_path == "":
            silence_mp3_path = None
        
        # Logging
        log_level = os.getenv("TOWER_LOG_LEVEL", "INFO")
        
        # Testing/dev
        test_mode_str = os.getenv("TOWER_TEST_MODE", "")
        test_mode = test_mode_str.lower() in ("1", "true", "yes", "on")
        
        force_slow_client_test_str = os.getenv("TOWER_FORCE_SLOW_CLIENT_TEST", "")
        force_slow_client_test = force_slow_client_test_str.lower() in ("1", "true", "yes", "on")
        
        # Create config instance
        config = cls(
            host=host,
            port=port,
            bitrate=bitrate,
            tone_frequency=tone_frequency,
            read_chunk_size=read_chunk_size,
            default_source=default_source,
            default_file_path=default_file_path,
            socket_path=socket_path,
            router_idle_timeout_sec=router_idle_timeout_sec,
            pcm_grace_sec=pcm_grace_sec,
            client_timeout_ms=client_timeout_ms,
            client_buffer_bytes=client_buffer_bytes,
            encoder_backoff_ms=encoder_backoff_ms,
            encoder_max_restarts=encoder_max_restarts,
            silence_mp3_path=silence_mp3_path,
            log_level=log_level,
            test_mode=test_mode,
            force_slow_client_test=force_slow_client_test
        )
        
        # Validate configuration
        config.validate()
        
        return config
    
    def validate(self) -> None:
        """
        Validate configuration values.
        
        Raises:
            ValueError: If configuration is invalid
        """
        if self.port < 1 or self.port > 65535:
            raise ValueError(f"Invalid port: {self.port} (must be 1-65535)")
        
        if not self.bitrate.endswith('k'):
            raise ValueError(f"Invalid bitrate format: {self.bitrate} (must end with 'k', e.g., '128k')")
        
        try:
            bitrate_value = int(self.bitrate[:-1])
            if bitrate_value <= 0:
                raise ValueError(f"Invalid bitrate value: {bitrate_value}")
        except ValueError:
            raise ValueError(f"Invalid bitrate: {self.bitrate}")
        
        if self.tone_frequency <= 0 or self.tone_frequency > 20000:
            raise ValueError(f"Invalid tone frequency: {self.tone_frequency} (must be 0-20000 Hz)")
        
        if self.read_chunk_size <= 0:
            raise ValueError(f"Invalid read chunk size: {self.read_chunk_size} (must be > 0)")
        
        # Validate Phase 4 client timeout
        if self.client_timeout_ms <= 0:
            raise ValueError(f"Invalid client timeout: {self.client_timeout_ms} (must be > 0)")
        
        # Validate client buffer size
        if self.client_buffer_bytes <= 0:
            raise ValueError(f"Invalid client buffer size: {self.client_buffer_bytes} (must be > 0)")
        
        # Validate encoder backoff schedule
        if not self.encoder_backoff_ms:
            raise ValueError("Encoder backoff schedule cannot be empty")
        if any(d <= 0 for d in self.encoder_backoff_ms):
            raise ValueError("All encoder backoff delays must be positive")
        
        # Validate encoder max restarts
        if self.encoder_max_restarts < 0:
            raise ValueError(f"Invalid encoder max restarts: {self.encoder_max_restarts} (must be >= 0)")
        
        # Validate log level
        valid_log_levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
        if self.log_level.upper() not in valid_log_levels:
            raise ValueError(
                f"Invalid log level: {self.log_level} "
                f"(must be one of: {', '.join(valid_log_levels)})"
            )
        
        # Validate Phase 2 source configuration
        if self.default_source not in ["tone", "silence", "file"]:
            raise ValueError(
                f"Invalid TOWER_DEFAULT_SOURCE: {self.default_source} "
                f"(must be 'tone', 'silence', or 'file')"
            )
        
        if self.default_source == "file":
            if not self.default_file_path:
                raise ValueError(
                    "TOWER_DEFAULT_FILE_PATH is required when TOWER_DEFAULT_SOURCE is 'file'"
                )
            if not Path(self.default_file_path).exists():
                raise FileNotFoundError(
                    f"TOWER_DEFAULT_FILE_PATH does not exist: {self.default_file_path}"
                )
        
        # Validate silence MP3 path if provided
        if self.silence_mp3_path is not None and not Path(self.silence_mp3_path).exists():
            raise FileNotFoundError(
                f"TOWER_SILENCE_MP3_PATH does not exist: {self.silence_mp3_path}"
            )


def load_config() -> TowerConfig:
    """
    Load and validate Tower configuration from environment variables.
    
    Returns:
        TowerConfig instance with loaded and validated values
        
    Raises:
        ValueError: If configuration is invalid
    """
    try:
        config = TowerConfig.load_config()
        return config
    except (ValueError, FileNotFoundError) as e:
        logger.error(f"Configuration error: {e}")
        raise


def get_config() -> TowerConfig:
    """
    Get Tower configuration instance (alias for load_config for backwards compatibility).
    
    Returns:
        TowerConfig instance
    """
    return load_config()


# Global CONFIG instance (loaded at module import time or on first access)
_CONFIG: Optional[TowerConfig] = None


def get_global_config() -> TowerConfig:
    """
    Get or load the global CONFIG instance.
    
    This should be called once at startup in main.py.
    
    Returns:
        TowerConfig instance
    """
    global _CONFIG
    if _CONFIG is None:
        _CONFIG = load_config()
    return _CONFIG


# For convenience, allow importing CONFIG directly
# This will be set by main.py after calling load_config()
CONFIG: Optional[TowerConfig] = None

