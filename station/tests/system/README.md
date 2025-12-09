# Station System Tests

System tests verify end-to-end behavior of the complete Station system.

These tests use:
- Full Station initialization
- Real Tower connections (or mocks)
- Real audio playback
- Real state persistence
- Full THINK/DO cycles

## Test Organization

- `test_station_startup_shutdown.py` - Full startup and shutdown sequences
- `test_station_think_do_cycles.py` - Complete THINK/DO event cycles
- `test_station_tower_integration.py` - Station-Tower PCM bridge integration
- `test_station_state_persistence.py` - State save/load across restarts

## Running System Tests

```bash
# Run all system tests
pytest station/tests/system/ -v

# Run with full environment
pytest station/tests/system/ -v --envfile=/etc/retrowaves/station.env
```






