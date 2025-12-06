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

def run_pytest(suppress_logs=False):
    """Run pytest on all contract tests with real-time output."""
    
    cmd = [
        sys.executable, "-m", "pytest",
        "tower/tests/contracts/",
        "-v",  # Use verbose to get individual test results for parsing
        "--disable-warnings",
        "--tb=short",
        # Note: --log-cli-level doesn't suppress application logs, only pytest's own logs
        # We'll filter application logs in the output processing
    ]
    
    print("=" * 60)
    print("Starting pytest execution...")
    if suppress_logs:
        print("(Log output suppressed - see full report for details)")
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
        
        # Filter patterns for log spam (common error log prefixes from application code)
        # Only filter application logs, not pytest's own output
        import re
        log_spam_patterns = [
            r'ERROR.*tower\.encoder',  # ERROR logs from encoder modules
            r'WARNING.*tower\.encoder',  # WARNING logs from encoder modules
            r'🔥\s+',  # Fire emoji error logs
            r'\[FFMPEG\]',  # FFmpeg prefix logs
        ]
        log_spam_re = re.compile('|'.join(log_spam_patterns))
        
        # Also track test progress for minimal output
        last_test_name = None
        
        while not (stdout_done and stderr_done):
            # Check stdout
            try:
                line, is_stderr = stdout_queue.get(timeout=0.1)
                if line is None:
                    stdout_done = True
                else:
                    # Always capture for parsing
                    stdout_lines.append(line)
                    
                    # Filter output based on suppress_logs flag
                    if suppress_logs:
                        # Only show test result lines and pytest summary, suppress application logs
                        is_test_result = (
                            '::' in line and ('PASSED' in line or 'FAILED' in line or 'ERROR' in line) or
                            '=' * 10 in line or  # pytest separators
                            line.strip().startswith('tower/tests/contracts/')  # Test file paths
                        )
                        is_not_log_spam = not log_spam_re.search(line)
                        
                        if is_test_result or is_not_log_spam:
                            print(line, end='', flush=True)
                    else:
                        # Show everything
                        print(line, end='', flush=True)
            except queue.Empty:
                pass
            
            # Check stderr
            try:
                line, is_stderr = stderr_queue.get(timeout=0.1)
                if line is None:
                    stderr_done = True
                else:
                    # Always capture for parsing
                    stderr_lines.append(line)
                    
                    # Filter stderr similarly
                    if suppress_logs:
                        is_not_log_spam = not log_spam_re.search(line)
                        if is_not_log_spam:
                            print(line, end='', flush=True, file=sys.stderr)
                    else:
                        print(line, end='', flush=True, file=sys.stderr)
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
                        stdout_lines.append(line)
                        if suppress_logs:
                            is_test_result = (
                                '::' in line and ('PASSED' in line or 'FAILED' in line or 'ERROR' in line) or
                                '=' * 10 in line or
                                line.strip().startswith('tower/tests/contracts/')
                            )
                            is_not_log_spam = not log_spam_re.search(line)
                            if is_test_result or is_not_log_spam:
                                print(line, end='', flush=True)
                        else:
                            print(line, end='', flush=True)
                
                while not stderr_queue.empty():
                    line, _ = stderr_queue.get_nowait()
                    if line is not None:
                        stderr_lines.append(line)
                        if suppress_logs:
                            is_not_log_spam = not log_spam_re.search(line)
                            if is_not_log_spam:
                                print(line, end='', flush=True, file=sys.stderr)
                        else:
                            print(line, end='', flush=True, file=sys.stderr)
                
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
    # Also handle: "X passed in Y.XXs" or "X failed, Y passed in Z.XXs"
    summary_line = None
    for line in reversed(output.split('\n')):
        line_lower = line.lower()
        # Look for summary line with equals signs and test counts
        if (('=' * 10 in line or '=' * 20 in line) and 
            ('passed' in line_lower or 'failed' in line_lower or 'error' in line_lower)):
            summary_line = line
            break
        # Also check for summary without equals (some pytest formats)
        if (('passed' in line_lower or 'failed' in line_lower) and 
            ('in ' in line_lower and ('s' in line_lower or 'second' in line_lower))):
            # This looks like a summary line: "X passed in Y.XXs"
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
    parser.add_argument(
        "--show-logs",
        action="store_true",
        help="Show all log output during test execution (default: suppress log spam)"
    )
    args = parser.parse_args()
    
    stdout, stderr, returncode = run_pytest(suppress_logs=not args.show_logs)
    
    print()
    print("=" * 60)
    print("PARSING TEST RESULTS")
    print("=" * 60)
    sys.stdout.flush()
    
    try:
        tests, passed, failed, errors, total, full_output = parse_pytest_output(stdout, stderr)
        print(f"✓ Parsed {len(tests)} tests: {passed} passed, {failed} failed, {errors} errors")
    except Exception as e:
        print(f"⚠ Error parsing test results: {e}")
        import traceback
        traceback.print_exc()
        # Fallback: create minimal report
        tests = []
        passed = 0
        failed = 0
        errors = 0
        total = 0
        full_output = stdout + "\n" + stderr
    
    sys.stdout.flush()
    
    print()
    print("=" * 60)
    print("GENERATING AUDIT REPORT")
    print("=" * 60)
    sys.stdout.flush()
    
    # Determine report file path (in script's directory)
    report_path = Path(__file__).parent / "CONTRACT_TEST_AUDIT_REPORT.md"
    
    try:
        report = generate_report(tests, passed, failed, errors, total, full_output, show_all=args.all)
        
        # Ensure report is not empty
        if not report or len(report.strip()) == 0:
            report = "=== CONTRACT TEST AUDIT ===\n\nTests executed: 0  | Passed: 0 | Failed: 0 | Errors: 0\n\n(Report generation failed - no content)\n\n--- Full Test Output ---\n" + full_output
        
        # Write to file using absolute path
        try:
            with open(report_path, "w", encoding="utf-8") as f:
                f.write(report)
            print(f"✓ Report generated ({len(report)} characters)")
            print(f"✓ Report written to: {report_path}")
        except Exception as write_error:
            print(f"⚠ Error writing report file: {write_error}")
            import traceback
            traceback.print_exc()
            # Try writing to current directory as fallback
            fallback_path = Path.cwd() / "CONTRACT_TEST_AUDIT_REPORT.md"
            try:
                with open(fallback_path, "w", encoding="utf-8") as f:
                    f.write(report)
                print(f"⚠ Wrote report to fallback location: {fallback_path}")
            except Exception as fallback_error:
                print(f"✗ Failed to write report to fallback location: {fallback_error}")
    except Exception as e:
        print(f"⚠ Error generating report: {e}")
        import traceback
        traceback.print_exc()
        # Write minimal error report
        error_report = f"=== CONTRACT TEST AUDIT ===\n\nERROR: Failed to generate report: {e}\n\n--- Raw Output ---\n{full_output[:5000]}\n"
        try:
            with open(report_path, "w", encoding="utf-8") as f:
                f.write(error_report)
            print(f"✓ Error report written to: {report_path}")
        except Exception as write_error:
            print(f"⚠ Error writing error report: {write_error}")
            # Try fallback
            fallback_path = Path.cwd() / "CONTRACT_TEST_AUDIT_REPORT.md"
            try:
                with open(fallback_path, "w", encoding="utf-8") as f:
                    f.write(error_report)
                print(f"⚠ Wrote error report to fallback location: {fallback_path}")
            except Exception:
                pass
        report = error_report
    
    print()
    print()
    print("=" * 80)
    print(" " * 20 + "AUDIT REPORT SUMMARY")
    print("=" * 80)
    print()
    # Print just the summary, not the full report (which can be huge)
    summary_lines = report.split('\n')[:10]  # First 10 lines (header + summary)
    if summary_lines:
        for line in summary_lines:
            print(line)
    else:
        print("(No summary available - report may be empty)")
    print()
    print("=" * 80)
    # Verify report file exists (already determined above)
    if report_path.exists():
        file_size = report_path.stat().st_size
        print(f"✓ Report file confirmed: {report_path}")
        print(f"✓ Report file size: {file_size} bytes")
    else:
        # Check if it was written to current directory instead
        fallback_path = Path.cwd() / "CONTRACT_TEST_AUDIT_REPORT.md"
        if fallback_path.exists():
            print(f"⚠ WARNING: Report file found at fallback location: {fallback_path}")
            print(f"  Expected location: {report_path}")
        else:
            print(f"⚠ WARNING: Report file was not created at expected location: {report_path}")
            print(f"  Also checked: {fallback_path}")
    print("=" * 80)
    print()
    sys.stdout.flush()  # Ensure summary is flushed
    
    return returncode

if __name__ == "__main__":
    sys.exit(main())
