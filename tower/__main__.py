"""
Tower package __main__ entry point.

Allows running with: python -m tower
"""

import sys
import logging
from pathlib import Path

# When running as a module, add tower/ to path so internal imports work
tower_dir = Path(__file__).parent
if str(tower_dir) not in sys.path:
    sys.path.insert(0, str(tower_dir))

from tower.service import TowerService
from tower.config import load_config


def setup_logging(log_level: str = "INFO"):
    """
    Set up logging configuration.
    
    Args:
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
    """
    # Convert string level to logging constant
    numeric_level = getattr(logging, log_level.upper(), logging.INFO)
    
    logging.basicConfig(
        level=numeric_level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )


def _log_effective_config(config):
    """Log effective configuration at INFO level (excluding secrets)."""
    logger = logging.getLogger(__name__)
    logger.info("=" * 60)
    logger.info("Tower Configuration:")
    logger.info(f"  Host: {config.host}")
    logger.info(f"  Port: {config.port}")
    logger.info(f"  Socket Path: {config.socket_path}")
    logger.info(f"  Client Timeout: {config.client_timeout_ms} ms")
    logger.info(f"  Client Buffer: {config.client_buffer_bytes} bytes")
    logger.info(f"  Encoder Backoff: {config.encoder_backoff_ms} ms")
    logger.info(f"  Encoder Max Restarts: {config.encoder_max_restarts}")
    logger.info(f"  Silence MP3 Path: {config.silence_mp3_path or '(generated internally)'}")
    logger.info(f"  Log Level: {config.log_level}")
    logger.info(f"  Test Mode: {config.test_mode}")
    logger.info("=" * 60)


def main():
    """Main entry point."""
    try:
        # Load configuration first (before setting up logging)
        config = load_config()
        
        # Set up logging with configured level
        setup_logging(config.log_level)
        
        # Store global CONFIG
        import tower.config as config_module
        config_module.CONFIG = config
        
        # Log effective configuration
        logger = logging.getLogger(__name__)
        _log_effective_config(config)
        
        logger.info(f"Starting Tower on {config.host}:{config.port}")
        
        service = TowerService(config)
        service.start()
        service.run_forever()
    except KeyboardInterrupt:
        pass
    except Exception as e:
        # Try to get logger, but if config failed, use basic logging
        try:
            logger = logging.getLogger(__name__)
        except Exception:
            logging.basicConfig(level=logging.ERROR)
            logger = logging.getLogger(__name__)
        logger.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()

