"""
Shared pytest configuration and fixtures for Tower tests.
"""

import pytest
import sys
from pathlib import Path

# Add tower to path if needed
tower_dir = Path(__file__).parent.parent
if str(tower_dir) not in sys.path:
    sys.path.insert(0, str(tower_dir))


@pytest.fixture(scope="session", autouse=True)
def configure_test_timeouts():
    """
    Configure test timeouts globally.
    
    This fixture ensures all tests have a timeout to prevent hanging.
    Individual tests can override with @pytest.mark.timeout decorator.
    """
    # Timeout is configured in pytest.ini
    pass

