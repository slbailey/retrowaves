#!/usr/bin/env python3
"""
Generate Contract Test Audit Report using pytest's programmatic API
"""
import sys
import os

os.chdir('/opt/retrowaves')
sys.path.insert(0, '/opt/retrowaves')

try:
    import pytest
except ImportError:
    print("ERROR: pytest not available")
    sys.exit(1)

# Run pytest and collect results
print("Running pytest...", file=sys.stderr)

# Use pytest's hook system to collect results
class ResultCollector:
    def __init__(self):
        self.tests = []
        self.current_test = None
    
    def pytest_runtest_setup(self, item):
        self.current_test = {
            'name': str(item.nodeid),
            'status': None,
            'error': None,
            'category': None
        }
    
    def pytest_runtest_logreport(self, report):
        if self.current_test and report.nodeid == self.current_test['name']:
            if report.when == 'call':
                if report.outcome == 'passed':
                    self.current_test['status'] = 'PASS'
                    self.tests.append(self.current_test)
                    self.current_test = None
                elif report.outcome == 'failed':
                    self.current_test['status'] = 'FAIL'
                    self.current_test['error'] = report.longrepr if hasattr(report, 'longrepr') else str(report)
                    self.tests.append(self.current_test)
                    self.current_test = None
            elif report.when == 'setup' and report.outcome == 'failed':
                self.current_test['status'] = 'ERROR'
                self.current_test['error'] = report.longrepr if hasattr(report, 'longrepr') else str(report)
                self.tests.append(self.current_test)
                self.current_test = None

collector = ResultCollector()

# Run pytest on contract tests only
exit_code = pytest.main(
    ['tower/tests/contracts/', '-q', '--disable-warnings', '--tb=short', '--maxfail=1'],
    plugins=[collector]
)

# Categorize errors
def categorize_error(test_name, error_text):
    """Categorize test failure/error"""
    if not error_text:
        return "UNKNOWN", "No error details"
    
    error_lower = str(error_text).lower()
    
    if 'fixture' in error_lower and 'not found' in error_lower:
        return "SYNTAX FIXED", "Missing test fixture - fixture needs to be in conftest.py or shared scope"
    
    if 'modulenotfounderror' in error_lower or 'importerror' in error_lower:
        return "SYNTAX FIXED", "Import error"
    
    if 'attributeerror' in error_lower:
        if "'nonetype'" in error_lower or "'none' has no attribute" in error_lower:
            return "CONTRACT MISMATCH", "Accessing attribute on None - contract requires implementation"
        return "CONTRACT MISMATCH", "Missing attribute/method - contract requires it"
    
    if 'assertionerror' in error_lower or 'assert' in error_lower:
        return "CONTRACT MISMATCH", "Assertion failed - behavior doesn't match contract"
    
    if 'typeerror' in error_lower:
        return "CONTRACT MISMATCH", "Type mismatch - interface doesn't match contract"
    
    return "IMPLEMENTATION DEFECT", "Runtime error during test execution"

# Categorize all tests
for test in collector.tests:
    if test['status'] in ('FAIL', 'ERROR'):
        category, reason = categorize_error(test['name'], test['error'])
        test['category'] = category
        test['reason'] = reason

# Generate report
passed = [t for t in collector.tests if t['status'] == 'PASS']
failed = [t for t in collector.tests if t['status'] == 'FAIL']
errors = [t for t in collector.tests if t['status'] == 'ERROR']

print("=== CONTRACT TEST AUDIT ===")
print()
print(f"Tests executed: {len(collector.tests)}  | Passed: {len(passed)} | Failed: {len(failed)} | Errors: {len(errors)}")
print()

# Sort by category
category_order = {'SYNTAX FIXED': 0, 'CONTRACT MISMATCH': 1, 'CONTRACT OUT OF DATE': 2, 
                  'DOCS AMBIGUOUS': 3, 'IMPLEMENTATION DEFECT': 4, 'UNKNOWN': 5}
all_issues = failed + errors
all_issues.sort(key=lambda x: (category_order.get(x.get('category', 'UNKNOWN'), 99), x['name']))

# Print issues
for test in all_issues:
    symbol = "❌" if test['status'] == "FAIL" else "⚠"
    print(f"{symbol} {test['status']} {test['name']}")
    print()
    
    # Extract error reason
    error_text = test.get('error', '')
    if error_text:
        error_lines = str(error_text).split('\n')
        # Find the actual error line
        error_line = None
        for line in error_lines:
            if line.strip() and 'error' in line.lower() and ('fixture' in line.lower() or 'attribute' in line.lower() or 'assert' in line.lower() or 'import' in line.lower()):
                error_line = line.strip()
                break
        if not error_line and error_lines:
            error_line = error_lines[0].strip()
        
        if error_line:
            if len(error_line) > 150:
                error_line = error_line[:147] + "..."
            print(f"Reason: {error_line}")
        else:
            print(f"Reason: {test.get('reason', 'Unknown error')}")
    else:
        print(f"Reason: {test.get('reason', 'Unknown error')}")
    print()
    print(f"Category: {test.get('category', 'UNKNOWN')}")
    print()
    
    # Resolution
    category = test.get('category', 'UNKNOWN')
    if category == "SYNTAX FIXED":
        resolution = "Fix syntax/import/fixture issue"
    elif category == "CONTRACT MISMATCH":
        resolution = "Code must be updated to match contract requirements"
    elif category == "CONTRACT OUT OF DATE":
        resolution = "Contract must be revised"
    elif category == "DOCS AMBIGUOUS":
        resolution = "Specification needs clarification"
    else:
        resolution = "Implementation defect - fix code logic"
    
    print(f"Resolution: {resolution}")
    print()

# Print passed summary
if passed:
    print("\n=== PASSED TESTS ===")
    import re
    files = {}
    for test in passed:
        match = re.match(r'(tower/tests/.*?/.*?\.py)::', test['name'])
        if match:
            fname = match.group(1)
            files.setdefault(fname, []).append(test['name'])
    
    for fname in sorted(files.keys()):
        print(f"\n✔ {fname}: {len(files[fname])} tests passed")

print()
print("=" * 80)
print(f"Summary: {len(passed)} passed, {len(failed)} failed, {len(errors)} errors")

