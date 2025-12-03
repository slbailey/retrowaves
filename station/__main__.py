"""
Station package __main__ entry point.

Allows running with: python -m station
"""

import sys
from pathlib import Path

# When running as a module, add station/ to path so internal imports work
station_dir = Path(__file__).parent
if str(station_dir) not in sys.path:
    sys.path.insert(0, str(station_dir))

# Now import and run the radio module
from app.radio import main

if __name__ == "__main__":
    main()


