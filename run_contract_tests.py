#!/usr/bin/env python3
"""
Run all contract tests and generate audit report per .cursor/rules.md
"""

import argparse
import queue
import subprocess
import sys
import re
import threading
from pathlib import Path

def run_pytest():
    """Run pytest on all contract tests with real-time output."""
    
    cmd = [
        sys.executable, "-m", "pytest",
        "tower/tests/contracts/",
        "-q",
        "--disable-warnings",
        "--tb=short",
        "-v"
    ]
    
    print("=" * 60)
    print("Starting pytest execution...")
    print("=" * 60)
    print()
    sys.stdout.flush()
    
    stdout_lines = []
    stderr_lines = []
    stdout_queue = queue.Queue()
    stderr_queue = queue.Queue()
    
    def read_stream(stream, queue, is_stderr=False):
        """Read from stream and put lines in queue."""
        try:
            for line in stream:
                queue.put((line, is_stderr))
        except Exception as e:
            queue.put((f"Error reading stream: {e}\n", is_stderr))
        finally:
            queue.put((None, is_stderr))  # Sentinel
    
    try:
        # Use Popen to stream output in real-time while capturing it
        process = subprocess.Popen(
            cmd,
            cwd=Path(__file__).parent,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,  # Line buffered
        )
        
        # Start threads to read stdout and stderr
        stdout_thread = threading.Thread(
            target=read_stream,
            args=(process.stdout, stdout_queue, False),
            daemon=True
        )
        stderr_thread = threading.Thread(
            target=read_stream,
            args=(process.stderr, stderr_queue, True),
            daemon=True
        )
        
        stdout_thread.start()
        stderr_thread.start()
        
        # Process output in real-time
        stdout_done = False
        stderr_done = False
        
        while not (stdout_done and stderr_done):
            # Check stdout
            try:
                line, is_stderr = stdout_queue.get(timeout=0.1)
                if line is None:
                    stdout_done = True
                else:
                    print(line, end='', flush=True)
                    stdout_lines.append(line)
            except queue.Empty:
                pass
            
            # Check stderr
            try:
                line, is_stderr = stderr_queue.get(timeout=0.1)
                if line is None:
                    stderr_done = True
                else:
                    print(line, end='', flush=True, file=sys.stderr)
                    stderr_lines.append(line)
            except queue.Empty:
                pass
            
            # Check if process finished
            if process.poll() is not None:
                # Process finished, wait for threads to finish reading
                stdout_thread.join(timeout=2.0)
                stderr_thread.join(timeout=2.0)
                
                # Drain remaining queues
                while not stdout_queue.empty():
                    line, _ = stdout_queue.get_nowait()
                    if line is not None:
                        print(line, end='', flush=True)
                        stdout_lines.append(line)
                
                while not stderr_queue.empty():
                    line, _ = stderr_queue.get_nowait()
                    if line is not None:
                        print(line, end='', flush=True, file=sys.stderr)
                        stderr_lines.append(line)
                
                break
        
        returncode = process.returncode
        stdout = ''.join(stdout_lines)
        stderr = ''.join(stderr_lines)
        
        print()
        print("=" * 60)
        print(f"Test execution completed with return code: {returncode}")
        print("=" * 60)
        print()
        sys.stdout.flush()
        
        return stdout, stderr, returncode
        
    except subprocess.TimeoutExpired:
        print("\n" + "=" * 60)
        print("ERROR: Test execution timed out after 300 seconds")
        print("=" * 60)
        sys.stdout.flush()
        return "", "Test execution timed out after 300 seconds", 1
    except Exception as e:
        print("\n" + "=" * 60)
        print(f"ERROR: Error running tests: {e}")
        print("=" * 60)
        sys.stdout.flush()
        return "", f"Error running tests: {e}", 1

def parse_pytest_output(stdout, stderr):
    """Parse pytest output and categorize failures."""
    output = stdout + "\n" + stderr
    
    # Extract test results
    tests = []
    passed = 0
    failed = 0
    errors = 0
    total = 0
    
    # First, extract summary from pytest's final summary line
    # Format: "================== X failed, Y passed, Z warnings in TIME =================="
    # or: "================== X passed, Y warnings in TIME =================="
    summary_line = None
    for line in reversed(output.split('\n')):
        if '=' * 10 in line and ('passed' in line.lower() or 'failed' in line.lower()):
            summary_line = line
            break
    
    if summary_line:
        # Parse summary line - this is the source of truth for counts
        # Match: "6 failed, 261 passed" or "261 passed, 6 failed"
        failed_match = re.search(r'(\d+)\s+failed', summary_line, re.IGNORECASE)
        if failed_match:
            failed = int(failed_match.group(1))
        
        passed_match = re.search(r'(\d+)\s+passed', summary_line, re.IGNORECASE)
        if passed_match:
            passed = int(passed_match.group(1))
        
        # Errors are typically reported as "failed" in pytest, but check for explicit errors
        error_match = re.search(r'(\d+)\s+error', summary_line, re.IGNORECASE)
        if error_match:
            errors = int(error_match.group(1))
        
        # Total = passed + failed + errors
        total = passed + failed + errors
    
    # Parse individual test results from verbose output
    # Format: "tower/tests/contracts/test_file.py::TestClass::test_name PASSED"
    # or: "tower/tests/contracts/test_file.py::TestClass::test_name FAILED"
    test_pattern = re.compile(
        r'(tower/tests/contracts/[^:]+)::([^:]+)::([^\s]+)\s+(PASSED|FAILED|ERROR|SKIPPED)',
        re.IGNORECASE
    )
    
    current_test = None
    current_error = []
    in_error_block = False
    
    lines = output.split('\n')
    for i, line in enumerate(lines):
        # Match test result lines
        match = test_pattern.search(line)
        if match:
            # Save previous test if exists
            if current_test:
                tests.append({
                    'name': current_test['full_name'],
                    'status': current_test['status'],
                    'error': '\n'.join(current_error) if current_error else None
                })
            
            # Start new test
            file_path, class_name, test_name, status = match.groups()
            full_name = f"{file_path}::{class_name}::{test_name}"
            current_test = {
                'full_name': full_name,
                'status': 'PASS' if status.upper() == 'PASSED' else 'FAIL'
            }
            current_error = []
            in_error_block = (status.upper() in ['FAILED', 'ERROR'])
            continue
        
        # Collect error details for failed tests
        if in_error_block and current_test:
            # Stop collecting at next test or summary line
            if test_pattern.search(line) or ('=' * 10 in line and 'passed' in line.lower()):
                in_error_block = False
            elif line.strip() and not line.startswith('=') and not line.startswith('-'):
                # Collect meaningful error lines (skip separators)
                if not re.match(r'^[\s=_-]+$', line):
                    current_error.append(line.strip())
    
    # Add last test if exists
    if current_test:
        tests.append({
            'name': current_test['full_name'],
            'status': current_test['status'],
            'error': '\n'.join(current_error) if current_error else None
        })
    
    # If we didn't find summary line, count from parsed tests
    if not summary_line:
        passed = sum(1 for t in tests if t['status'] == 'PASS')
        failed = sum(1 for t in tests if t['status'] == 'FAIL')
        total = len(tests)
    
    return tests, passed, failed, errors, total, output

def categorize_failure(test_name, error, status='FAIL'):
    """Categorize test failure per rules."""
    # If test actually passed, return PASS
    if status == 'PASS':
        return "PASS", "Test passed"
    
    # If test failed but no error details, categorize as unknown failure
    if not error:
        return "UNKNOWN FAILURE", "Test failed but no error details captured"
    
    error_lower = error.lower()
    
    # SYNTAX errors
    if any(x in error_lower for x in ['syntaxerror', 'indentationerror', 'nameerror', 'import error', 'modulenotfounderror']):
        return "SYNTAX FIXED", "Syntax or import error - can be fixed"
    
    # CONTRACT MISMATCH
    if any(x in error_lower for x in ['attributeerror', 'not implemented', 'notimplementederror', 'missing', 'required']):
        return "CONTRACT MISMATCH", "Code doesn't match contract requirements"
    
    # IMPLEMENTATION DEFECT
    if any(x in error_lower for x in ['assertionerror', 'valueerror', 'typeerror', 'keyerror', 'indexerror']):
        return "IMPLEMENTATION DEFECT", "Code bug unrelated to contract"
    
    # Default
    return "CONTRACT MISMATCH", "Code doesn't match contract requirements"

def generate_report(tests, passed, failed, errors, total, full_output, show_all=False):
    """Generate audit report per rules format."""
    report = []
    report.append("=== CONTRACT TEST AUDIT ===")
    report.append("")
    report.append(f"Tests executed: {total}  | Passed: {passed} | Failed: {failed} | Errors: {errors}")
    report.append("")
    report.append("")
    
    for test in tests:
        test_name = test['name']
        status = test['status']
        error = test['error']
        
        if status == 'PASS':
            if show_all:
                report.append(f"✔ PASS {test_name}")
                report.append("")
        else:
            # Test failed - categorize the failure
            category, resolution = categorize_failure(test_name, error, status=status)
            
            if category == "SYNTAX FIXED":
                symbol = "⚠"
            elif "CONTRACT" in category:
                symbol = "❌"
            else:
                symbol = "⚠"
            
            report.append(f"{symbol} FAIL {test_name}")
            report.append("")
            if error:
                # Extract first meaningful error line
                error_lines = error.split('\n')
                reason = error_lines[0] if error_lines else "Unknown error"
                if len(reason) > 100:
                    reason = reason[:100] + "..."
                report.append(f"Reason: {reason}")
            else:
                report.append("Reason: Test failed (no error details)")
            report.append("")
            report.append(f"Category: {category}")
            report.append("")
            report.append(f"Resolution: {resolution}")
            report.append("")
            report.append("")
    
    # Add full output at end for debugging
    report.append("--- Full Test Output ---")
    report.append(full_output)
    
    return "\n".join(report)

def main():
    """Main execution."""
    parser = argparse.ArgumentParser(description="Run contract tests and generate audit report")
    parser.add_argument(
        "-all", "--all",
        action="store_true",
        help="Show all tests including passing tests (default: only show failing tests)"
    )
    args = parser.parse_args()
    
    stdout, stderr, returncode = run_pytest()
    
    print("Parsing test results...")
    tests, passed, failed, errors, total, full_output = parse_pytest_output(stdout, stderr)
    
    print("Generating audit report...")
    report = generate_report(tests, passed, failed, errors, total, full_output, show_all=args.all)
    
    # Write to file
    with open("CONTRACT_TEST_AUDIT_REPORT.md", "w") as f:
        f.write(report)
    
    print()
    print("=" * 60)
    print("AUDIT REPORT SUMMARY")
    print("=" * 60)
    print()
    # Print just the summary, not the full report (which can be huge)
    summary_lines = report.split('\n')[:10]  # First 10 lines (header + summary)
    print('\n'.join(summary_lines))
    print()
    print(f"Full report written to: CONTRACT_TEST_AUDIT_REPORT.md")
    print("=" * 60)
    print()
    
    return returncode

if __name__ == "__main__":
    sys.exit(main())
