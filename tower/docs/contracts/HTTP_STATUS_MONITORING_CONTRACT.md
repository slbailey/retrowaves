# Contract: HTTP_STATUS_MONITORING

This contract defines the requirements for HTTP status and monitoring endpoints that allow external systems (such as Station) to monitor Tower's internal state for adaptive throttling and operational monitoring.

## Purpose

The Tower HTTP server must expose status endpoints that enable external systems to:
- Monitor input ring buffer fullness for adaptive throttling
- Monitor encoder state and operational status
- Make informed decisions about data transmission rates

This functionality was present in the legacy implementation and must be preserved in the new Tower architecture.

## Legacy Implementation Reference

In the legacy implementation (`tower/_legacy/http_server.py`), the following endpoints were provided:

1. **`GET /tower/buffer`** - Exposed input ring buffer fullness
   - Returns JSON: `{"fill": <count>, "capacity": <capacity>}`
   - Used by Station for adaptive throttling based on buffer fullness
   - Source: `audio_input_router._queue.get_stats()`

2. **`GET /status`** - General operational status
   - Returns encoder state, source mode, client count, uptime
   - Included router queue stats when available

## Requirements

### [M1] Input Ring Buffer Monitoring Endpoint

- [M1.1] Tower MUST expose an HTTP endpoint that reports the current state of the **input PCM ring buffer** (AudioInputRouter).
- [M1.2] The endpoint MUST return buffer fullness metrics in JSON format.
- [M1.3] The endpoint MUST be accessible via HTTP GET request.
- [M1.4] The endpoint MUST return the following fields:
  - `fill`: Current number of frames in the buffer (integer, 0 to capacity)
  - `capacity`: Maximum number of frames the buffer can hold (integer)
- [M1.5] The endpoint MAY return additional metrics such as:
  - `overflow_count`: Total number of frames dropped due to buffer being full
  - `utilization_percent`: Percentage of buffer capacity in use (0-100)
- [M1.6] The endpoint MUST be thread-safe and non-blocking.
- [M1.7] The endpoint MUST return data that is consistent with the actual buffer state at the time of the request (may be slightly stale due to concurrent access, but must be accurate within the constraints of thread-safe access).

### [M2] Endpoint Path and Naming

- [M2.1] The input buffer monitoring endpoint SHOULD be accessible at `/tower/buffer` to maintain compatibility with legacy Station implementations.
- [M2.2] Alternative paths MAY be provided (e.g., `/api/buffer`, `/status/buffer`) but `/tower/buffer` MUST be supported.
- [M2.3] The endpoint path MUST be documented in the contract and remain stable across versions.
- [M2.4] `/tower/buffer` is a **stable long-term compatibility endpoint**.
  - It MUST NOT be removed or renamed without a deprecation cycle.
  - Stations depend on it for adaptive throttling.
  - This is a **must-exist public API with stability guarantees**.

### [M3] Response Format

- [M3.1] The endpoint MUST return HTTP 200 OK on success.
- [M3.2] The response MUST have `Content-Type: application/json` header.
- [M3.3] The response body MUST be valid JSON.
- [M3.4] The response MUST follow this schema:
  ```json
  {
    "fill": <integer>,
    "capacity": <integer>
  }
  ```
- [M3.5] On error (e.g., buffer not available), the endpoint MUST return HTTP 503 Service Unavailable with an appropriate error message.

### [M4] Integration with AudioInputRouter

- [M4.1] The endpoint MUST read buffer statistics from the AudioInputRouter instance.
- [M4.2] The endpoint MUST use the AudioInputRouter's thread-safe statistics methods.
- [M4.3] The endpoint MUST NOT require direct access to internal buffer state (must use public API).
- [M4.4] AudioInputRouter MUST provide a method to retrieve buffer statistics (count, capacity) that is thread-safe and non-blocking.

### [M5] Use Case: Adaptive Throttling

- [M5.1] The endpoint is designed to enable Station to implement adaptive throttling:
  - Station can poll `/tower/buffer` periodically (e.g., every 100-500ms)
  - When `fill` approaches `capacity`, Station can reduce transmission rate
  - When `fill` is low, Station can increase transmission rate
- [M5.2] The endpoint MUST be efficient enough to support frequent polling without impacting Tower performance.
- [M5.3] The endpoint MUST NOT block or delay other Tower operations.

### [M6] Additional Status Endpoints (Future)

- [M6.1] Tower MAY expose additional status endpoints for:
  - Encoder state (running, stopped, restarting, failed)
  - Operational mode (LIVE_INPUT, FALLBACK, etc.)
  - Client connection count
  - System uptime
  - MP3 output buffer statistics
- [M6.2] These endpoints are OPTIONAL but recommended for operational monitoring.
- [M6.3] If implemented, these endpoints MUST follow the same JSON response format conventions.

### [M7] HTTP Server Integration

- [M7.1] The status endpoints MUST be integrated into the Tower HTTP server (`tower/http/server.py` or equivalent).
- [M7.2] The HTTP server MUST have access to the AudioInputRouter instance to query buffer statistics.
- [M7.3] The HTTP server MUST handle endpoint requests in a non-blocking manner.
- [M7.4] The HTTP server MUST handle client disconnections gracefully (no errors when clients disconnect during request handling).

### [M8] Thread Safety

- [M8.1] All status endpoint handlers MUST be thread-safe.
- [M8.2] Concurrent requests to status endpoints MUST NOT cause data races or inconsistent responses.
- [M8.3] Status endpoint handlers MUST NOT hold locks for extended periods.

### [M9] Error Handling

- [M9.1] If the AudioInputRouter is not available or not initialized, the endpoint MUST return HTTP 503 Service Unavailable.
- [M9.2] If an unexpected error occurs, the endpoint MUST return HTTP 500 Internal Server Error.
- [M9.3] Error responses MUST include a JSON body with an error message:
  ```json
  {
    "error": "<error message>"
  }
  ```

### [M10] Performance Requirements

- [M10.1] Status endpoint responses MUST be generated quickly (< 10ms typical, < 100ms maximum).
- [M10.2] Status endpoint handlers MUST NOT perform expensive operations (file I/O, network calls, etc.).
- [M10.3] Status endpoint handlers MUST NOT block on locks or other synchronization primitives.

## Implementation Notes

### Current State

**⚠️ NOT YET IMPLEMENTED** - This contract documents a requirement that must be implemented in the Tower architecture.

The legacy implementation (`tower/_legacy/http_server.py`) provided this functionality via:
- `GET /tower/buffer` endpoint (lines 247-279)
- Integration with `AudioInputRouter._queue.get_stats()`

### Required Changes

To implement this contract:

1. **AudioInputRouter Enhancement** (if needed):
   - Ensure `AudioInputRouter` provides a thread-safe method to get buffer statistics
   - Method should return `count` and `capacity` at minimum
   - Consider adding `overflow_count` if not already tracked

2. **HTTPServer Enhancement**:
   - Add route handler for `GET /tower/buffer`
   - Inject `AudioInputRouter` instance into HTTPServer (or provide access via TowerService)
   - Implement JSON response formatting
   - Add error handling for unavailable buffer

3. **TowerService Integration**:
   - Ensure HTTPServer has access to AudioInputRouter instance
   - Wire components appropriately during startup

### Testing Requirements

- Unit tests for endpoint handlers
- Integration tests verifying buffer statistics accuracy
- Performance tests ensuring endpoint response times meet requirements
- Thread-safety tests for concurrent endpoint access

## Related Contracts

- **AUDIO_INPUT_ROUTER_CONTRACT.md**: Defines the AudioInputRouter interface and statistics methods
- **TOWER_SERVICE_INTEGRATION_CONTRACT.md**: Defines how components are wired together
- **HTTP_CONNECTION_MANAGER_CONTRACT.md**: Defines HTTP connection management
- **TOWER_RUNTIME_CONTRACT.md**: Defines runtime behavior and endpoint availability

## References

- Legacy implementation: `tower/_legacy/http_server.py` (lines 247-279)
- Legacy AudioInputRouter: `tower/_legacy/audio_input_router.py`
- Current AudioInputRouter: `tower/audio/input_router.py`
- Current HTTPServer: `tower/http/server.py`
