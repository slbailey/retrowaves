#!/usr/bin/env python3
"""
Simple test runner for contract tests.
Run with: python3 run_contract_tests.py
"""

import sys
import subprocess
import os

def run_tests():
    """Run all contract tests."""
    os.chdir('/opt/retrowaves')
    
    test_files = [
        'station/tests/contracts/test_playout_engine_contract.py',
        'station/tests/contracts/test_dj_engine_contract.py',
        'station/tests/contracts/test_output_sink_contract.py',
        'station/tests/contracts/test_master_system_contract.py',
    ]
    
    print("Running Station Contract Tests...")
    print("=" * 60)
    
    for test_file in test_files:
        print(f"\nRunning: {test_file}")
        print("-" * 60)
        try:
            result = subprocess.run(
                [sys.executable, '-m', 'pytest', test_file, '-v', '--tb=short'],
                cwd='/opt/retrowaves',
                capture_output=True,
                text=True
            )
            print(result.stdout)
            if result.stderr:
                print("STDERR:", result.stderr)
            if result.returncode != 0:
                print(f"Tests in {test_file} had failures (exit code: {result.returncode})")
        except Exception as e:
            print(f"Error running {test_file}: {e}")
    
    print("\n" + "=" * 60)
    print("Test run complete!")

if __name__ == '__main__':
    run_tests()
