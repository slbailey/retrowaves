"""
Station package __main__ entry point.

Allows running with: python -m station
"""

import sys
import os
from pathlib import Path

# CRITICAL: Add parent directory to path BEFORE any station.* imports
# The station package uses absolute imports like "from station.music_logic..."
# which require the parent directory (/opt/retrowaves) to be in sys.path

# Get the project root (parent of station directory)
project_root = Path(__file__).parent.parent
project_root_str = str(project_root.resolve())

# Also check PYTHONPATH environment variable
pythonpath = os.environ.get('PYTHONPATH', '')
if pythonpath and project_root_str not in pythonpath.split(os.pathsep):
    os.environ['PYTHONPATH'] = project_root_str + os.pathsep + pythonpath

# Add to sys.path if not already there
if project_root_str not in sys.path:
    sys.path.insert(0, project_root_str)

# Now import and run the radio module
# This import will work because project_root is now in sys.path
from station.app.radio import main

if __name__ == "__main__":
    main()



