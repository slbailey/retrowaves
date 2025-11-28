#!/bin/bash
# Helper script to activate venv and run main.py in interactive mode

cd "$(dirname "$0")"
source venv/bin/activate
python main.py --interactive --local

