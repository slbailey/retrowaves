# Phase 10 Fixes Implementation Plan

## Status Summary

✅ **Completed Fixes:**
1. Removed grace period logic from AudioPump (A8 violation) - DONE
2. Implemented fallback provider logic (M7.2, M16) - DONE

🔄 **Remaining Fixes:**
3. Implement continuous silence during BOOTING (S7.2)
4. Fix Supervisor stdin initialization
5. Fix Supervisor startup ordering (S19.16)
6. Fix drain thread frame parsing (F9)
7. Fix restart buffer preservation
8. Update Tower Runtime HTTP layer

## Detailed Fix Requirements

### Fix 3: Continuous Silence During BOOTING (S7.2)
**Files:** `tower/encoder/encoder_manager.py`
**Issue:** Tests expect at least 5 silence frame writes during BOOTING, but 0 writes are captured.
**Solution:** Ensure `next_frame()` writes silence continuously during BOOTING. The code already does this (line 746), but tests may not be capturing it. May need to ensure AudioPump is running during tests.

### Fix 4: Supervisor stdin initialization
**Files:** `tower/encoder/ffmpeg_supervisor.py`
**Issue:** `_stdin` is None when boot priming attempts to write (thread exception in Phase 9).
**Solution:** Ensure `_stdin` is assigned immediately after Popen object creation, before any threads attempt to write.

### Fix 5: Supervisor startup ordering (S19.16)
**Files:** `tower/encoder/ffmpeg_supervisor.py`
**Issue:** Drain threads must start BEFORE first PCM write.
**Solution:** Ensure drain threads start before boot priming or any PCM writes occur.

### Fix 6: Drain thread frame parsing (F9)
**Files:** `tower/encoder/ffmpeg_supervisor.py` (specifically `_stdout_drain()`)
**Issue:** Drain thread should accumulate bytes and detect frame boundaries. Currently pushes arbitrary chunks.
**Solution:** 
- Add byte accumulator buffer
- Detect MP3 frame boundaries (frame size ≈384 bytes for 128kbps@48kHz, computed as (144 * bitrate_bps) / sample_rate)
- Only push complete frames to buffer
- Handle partial frames by accumulating until complete

### Fix 7: Restart buffer preservation
**Files:** `tower/encoder/ffmpeg_supervisor.py`
**Issue:** MP3 buffer should preserve frames during restart, but test shows 10 frames instead of expected 2.
**Solution:** Ensure buffer is not cleared during restart. Buffer should be preserved per contract [S4].

### Fix 8: Update Tower Runtime HTTP layer
**Files:** `tower/http/server.py`, `tower/tests/contracts/test_tower_runtime.py`
**Issue:** Test expects `service.http_server.connection_manager` attribute which doesn't exist.
**Solution:** Add `connection_manager` property to HTTPServer that forwards to `_connected_clients` for backwards compatibility with tests.

## Next Steps

1. Implement Fix 3 (continuous silence) - verify test setup
2. Implement Fix 4 & 5 (supervisor initialization and ordering)
3. Implement Fix 6 (drain thread frame parsing) - most complex
4. Implement Fix 7 (buffer preservation)
5. Implement Fix 8 (HTTP layer compatibility)
6. Run full test suite to verify all fixes





