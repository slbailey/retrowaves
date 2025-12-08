# Contract Test Refactoring Notes

## Summary

All contract tests have been refactored to:
1. ✅ Remove all real dependencies (environment variables, real files, real directories, real MP3)
2. ✅ Use test doubles (fakes, stubs, mocks) instead
3. ✅ Map tests directly to contract clauses (1-3 tests per clause)
4. ✅ Focus on contract compliance, not implementation details

## Test Count Reduction

- **Before**: 228 tests (many testing implementation details)
- **After**: 78 tests (focused on contract clauses only)

## Test Doubles Created

All test doubles are in `test_doubles.py`:
- `FakeMediaLibrary` - Provides test track lists without file system
- `FakeRotationManager` - Deterministic song selection
- `FakeAssetDiscoveryManager` - Pre-populated asset caches
- `StubFFmpegDecoder` - Generates fake PCM frames
- `StubOutputSink` - Records writes without real I/O
- `FakeDJStateStore` - In-memory state storage

## Test Structure

Each contract test file now:
- Maps test classes directly to contract clauses (e.g., `TestINT1_1_RequiredFields`)
- Contains 1-3 tests per clause
- Uses test doubles exclusively
- Focuses on contract structure and requirements, not implementation

## Integration Tests

Real component tests have been moved to:
- `station/tests/integration/` - Component integration tests
- `station/tests/system/` - End-to-end system tests

These will be implemented separately and use real dependencies.

## Contract Test Philosophy

Contract tests verify:
- **Structure**: Does the component have the required attributes/methods?
- **Requirements**: Does the component satisfy contract requirements?
- **Prohibitions**: Does the component avoid prohibited operations?

Contract tests do NOT verify:
- Implementation details
- Real file system behavior
- Real network behavior
- Real audio processing

These are tested in integration/system tests.





