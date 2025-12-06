#!/usr/bin/env python3
"""Check if test modules can be imported (syntax/import errors)"""
import sys
import os
import traceback

os.chdir('/opt/retrowaves')
sys.path.insert(0, '/opt/retrowaves')

test_dir = '/opt/retrowaves/tower/tests/contracts'
test_files = [f for f in os.listdir(test_dir) if f.startswith('test_') and f.endswith('.py')]

print(f"Checking {len(test_files)} test files for import errors...")
print("=" * 80)

import_errors = []
for test_file in sorted(test_files):
    module_name = test_file[:-3]  # Remove .py
    full_path = os.path.join(test_dir, test_file)
    
    try:
        spec = __import__('importlib.util').spec_from_file_location(module_name, full_path)
        if spec and spec.loader:
            module = __import__('importlib.util').module_from_spec(spec)
            spec.loader.exec_module(module)
            print(f"✓ {test_file}")
    except Exception as e:
        error_msg = f"{test_file}: {str(e)}"
        print(f"✗ {error_msg}")
        import_errors.append((test_file, str(e), traceback.format_exc()))

print("=" * 80)
if import_errors:
    print(f"\nFound {len(import_errors)} import errors:")
    for file, error, tb in import_errors:
        print(f"\n{file}:")
        print(f"  {error}")
    sys.exit(1)
else:
    print("\nAll test files imported successfully!")
    print("\nAttempting to run pytest...")
    print("=" * 80)
    
    try:
        import pytest
        exit_code = pytest.main(['tower/tests/', '-v', '--tb=short', '-x', '--no-header'])
        sys.exit(exit_code)
    except Exception as e:
        print(f"ERROR: {e}")
        traceback.print_exc()
        sys.exit(1)
