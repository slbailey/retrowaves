# Station Integration Tests

Integration tests verify that real components work together correctly.

These tests use:
- Real file system access
- Real environment variables
- Real MP3 files
- Real directory structures
- Real component instances

## Test Organization

- `test_dj_engine_integration.py` - DJEngine with real RotationManager and AssetDiscoveryManager
- `test_playout_engine_integration.py` - PlayoutEngine with real decoders and sinks
- `test_rotation_manager_integration.py` - RotationManager with real media library
- `test_asset_discovery_integration.py` - AssetDiscoveryManager with real file system
- `test_station_integration.py` - Full Station startup and operation

## Running Integration Tests

```bash
# Run all integration tests
pytest station/tests/integration/ -v

# Run with real test data
DJ_PATH=/mnt/media/appalachia-radio/julie \
REGULAR_MUSIC_PATH=/mnt/media/appalachia-radio/songs \
HOLIDAY_MUSIC_PATH=/mnt/media/appalachia-radio/holiday_songs \
pytest station/tests/integration/ -v
```






