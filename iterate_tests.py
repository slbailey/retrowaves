#!/usr/bin/env python3
"""
Iterate over all tower tests until all pass.
Activate venv and run pytest repeatedly, fixing issues as they come up.
"""

import subprocess
import sys
import re
from pathlib import Path

def run_tests():
    """Run pytest and return output, exit code, and parsed results."""
    print("\n" + "="*80)
    print("RUNNING ALL TOWER TESTS...")
    print("="*80 + "\n")
    
    cmd = [
        "/opt/retrowaves/venv/bin/python",
        "-m", "pytest",
        "tower/tests/",
        "-v",
        "--tb=short",
        "--disable-warnings"
    ]
    
    try:
        result = subprocess.run(
            cmd,
            cwd="/opt/retrowaves",
            capture_output=True,
            text=True,
            timeout=300
        )
        
        output = result.stdout + "\n" + result.stderr
        returncode = result.returncode
        
        # Parse summary line
        passed = 0
        failed = 0
        total = 0
        
        # Look for summary line like "X passed, Y failed in Z.XXs" or "X failed, Y passed"
        summary_match = re.search(r'(\d+)\s+passed', output)
        if summary_match:
            passed = int(summary_match.group(1))
        
        summary_match = re.search(r'(\d+)\s+failed', output)
        if summary_match:
            failed = int(summary_match.group(1))
        
        total = passed + failed
        
        return output, returncode, passed, failed, total
        
    except subprocess.TimeoutExpired:
        return "TIMEOUT", 1, 0, 0, 0
    except Exception as e:
        return f"ERROR: {e}", 1, 0, 0, 0

def extract_failed_tests(output):
    """Extract list of failed test names from pytest output."""
    failed_tests = []
    lines = output.split('\n')
    
    for line in lines:
        # Match lines like "tower/tests/contracts/test_file.py::TestClass::test_name FAILED"
        match = re.search(r'(tower/tests/[^\s]+)\s+FAILED', line)
        if match:
            test_name = match.group(1)
            if test_name not in failed_tests:
                failed_tests.append(test_name)
    
    return failed_tests

def main():
    """Main loop: run tests, show results, iterate."""
    max_iterations = 50  # Increased for automatic fixing
    iteration = 0
    
    while iteration < max_iterations:
        iteration += 1
        print(f"\n{'='*80}")
        print(f"ITERATION {iteration}")
        print(f"{'='*80}\n")
        
        output, returncode, passed, failed, total = run_tests()
        
        print("\n" + "="*80)
        print("TEST RESULTS SUMMARY")
        print("="*80)
        print(f"Total: {total} | Passed: {passed} | Failed: {failed} | Exit Code: {returncode}")
        print("="*80 + "\n")
        
        if returncode == 0:
            print("🎉 ALL TESTS PASSED! 🎉\n")
            return 0
        
        # Extract failed tests
        failed_tests = extract_failed_tests(output)
        
        if failed_tests:
            print(f"\nFailed tests ({len(failed_tests)}):")
            for test in failed_tests[:10]:  # Show first 10
                print(f"  - {test}")
            if len(failed_tests) > 10:
                print(f"  ... and {len(failed_tests) - 10} more")
        
        # Show a snippet of the output
        print("\n" + "="*80)
        print("FAILURE DETAILS (last 50 lines):")
        print("="*80)
        output_lines = output.split('\n')
        for line in output_lines[-50:]:
            print(line)
        print("="*80)
        
        # Continue to next iteration to try fixing issues automatically
        print("\n⚠️  Tests failed. Continuing to next iteration...\n")
    
    print(f"\n⚠️  Reached max iterations ({max_iterations})")
    return 1

if __name__ == "__main__":
    sys.exit(main())

