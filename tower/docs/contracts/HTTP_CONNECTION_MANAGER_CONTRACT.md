# Contract: HTTP_CONNECTION_MANAGER

This contract defines the behavior of HTTPConnectionManager, which manages HTTP streaming clients.

## 1. Core Invariants

- [H1] HTTPConnectionManager manages a **thread-safe** list of connected clients.
- [H2] **Non-blocking broadcast**: Broadcast operations MUST be non-blocking with respect to the main loop. Writes to slow clients MUST NOT delay other clients; slow clients MAY be dropped or written to via non-blocking semantics or background handling.
- [H3] Slow clients are **automatically dropped** after timeout.

## 2. Interface Contract

- [H4] **Client registration**: HTTPConnectionManager provides:
  - `add_client(client_socket: socket.socket, client_id: str)` → registers a client socket with an associated ID used for metrics/logging. Adds client to broadcast list.
  - `remove_client(client_id: str)` → removes client from list
  - `broadcast(data: bytes)` → sends data to all clients
- [H5] All methods are thread-safe (protected by locks or thread-safe data structures).

## 3. Broadcast Behavior

- [H6] `broadcast(data: bytes)`:
  - Iterates through all connected clients
  - Uses non-blocking writes (`sendall()` or equivalent)
  - Drops clients that cannot accept data within `TOWER_CLIENT_TIMEOUT_MS`
- [H7] All clients receive the **same data** (single broadcast signal).

## 3.1. HTTPConnectionManager Broadcast Semantics

- [H11] **socket.send() return value handling**:
  - `socket.send()` MUST return an integer number of bytes successfully written.
  - Non-integer returns (e.g., Mock objects, None, strings) MUST be treated as 0 bytes sent.
  - Errors and non-write events (exceptions, 0-byte returns) MUST trigger graceful disconnect.

## 4. Client Management

- [H8] Client disconnects are detected and handled gracefully.
- [H9] Slow clients (>250ms timeout) are removed from broadcast list.
- [H10] Client list modifications are atomic and thread-safe.

## Required Tests

- `tests/contracts/test_tower_http_connection_manager.py` MUST cover:
  - [H1]–[H3]: Thread safety and non-blocking behavior
  - [H4]–[H5]: Interface contract and thread safety
  - [H6]–[H7]: Broadcast behavior
  - [H11]: socket.send() return value handling (integer validation, Mock handling)
  - [H8]–[H10]: Client management

