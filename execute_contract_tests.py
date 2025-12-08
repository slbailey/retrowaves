#!/usr/bin/env python3
"""
Execute contract tests and generate audit report.
"""
import subprocess
import sys
import os

os.chdir('/opt/retrowaves')
sys.path.insert(0, '/opt/retrowaves')

print("=" * 80)
print("Running Contract Tests")
print("=" * 80)
print()

# Try to run pytest
try:
    result = subprocess.run(
        [sys.executable, '-m', 'pytest', 
         'tower/tests/contracts/', 
         '-q', '--disable-warnings', '--tb=short', '-v'],
        cwd='/opt/retrowaves',
        capture_output=True,
        text=True,
        timeout=300
    )
    
    print("STDOUT:")
    print(result.stdout)
    print()
    print("STDERR:")
    print(result.stderr)
    print()
    print("Return code:", result.returncode)
    
except subprocess.TimeoutExpired:
    print("ERROR: Test execution timed out")
except FileNotFoundError:
    print("ERROR: pytest not found")
except Exception as e:
    print(f"ERROR: {e}")
    import traceback
    traceback.print_exc()
