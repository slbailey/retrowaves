# Retrowaves Tower — Phase 5 Source Graph Contract

**Phase:** 5 (Source Graph and Mixing Layer)  
**Status:** Contract Definition  
**Date:** 2025-01-XX

This document defines the explicit, testable contract for Phase 5 of Retrowaves Tower. Phase 5 introduces the Tower "Source Graph" and Mixing Layer, providing clean, switchable, layered source routing without DSP mixing. Phase 5 enables node-based source management with primary source selection, temporary override stacking, and seamless frame-boundary switching while maintaining full backward compatibility with Phase 1–4 behavior.

---

## Overview

**Purpose of Source Graph:**
- Provide clean, switchable, layered source routing architecture
- Enable primary source selection with temporary override nodes (IDs, bumpers, alerts)
- Support seamless switching on frame boundaries
- Maintain backward compatibility with Phase 1–4 behavior

**Key Design Principles:**
- **No DSP mixing required.** "Mixing" in Phase 5 means clean switching and layering rules only
- **Exactly ONE "primary active node" at a time** (either primary source or top of override stack)
- **Frame-boundary switching:** All source switches must occur cleanly on frame boundaries
- **Automatic fallback:** Active node failures fall back to ToneSource
- **Override stack:** Temporary override nodes push onto a stack and pop when finished
- **AudioPump independence:** Mixer must never block AudioPump timing

---

## Scope

Phase 5 implements:
- ✅ SourceGraph component that owns multiple sources as nodes
- ✅ SourceNode abstraction exposing `next_frame()` and metadata (type, name, state)
- ✅ Mixer component as simple "node selector" with optional layering stack
- ✅ Primary source selection (`set_primary_source(name)`)
- ✅ Override stack management (`push_override(node_name)`, `pop_override()`)
- ✅ Frame-boundary switching (all switches occur cleanly on frame boundaries)
- ✅ Automatic fallback to ToneSource when active node fails
- ✅ Control API extensions (`set_primary`, `push_override`, `pop_override`)
- ✅ Status API extensions (`primary_source`, `override_stack[]`, `active_source`)
- ✅ Backward compatibility with Phase 1–4 behavior and tests

Phase 5 does NOT implement:
- ❌ DSP mixing (volume curves, crossfading, audio blending)
- ❌ Multiple simultaneous active sources (only one node active at a time)
- ❌ Complex layering rules beyond override stack
- ❌ Source scheduling or automation
- ❌ New source types (uses existing: ToneSource, SilenceSource, FileSource, LivePCMSource)
- ❌ Changes to Unix socket input semantics
- ❌ Changes to encoder or HTTP server behavior
- ❌ Changes to fallback behavior for Live PCM (router None → ToneSource remains)

---

## Contract Requirements

### 1. SourceGraph Component

**1.1 Component Purpose**
- Tower must implement a `SourceGraph` component
- SourceGraph must own multiple sources as nodes (ToneSource, SilenceSource, FileSource, LivePCMSource)
- SourceGraph must manage source node lifecycle (creation, registration, cleanup)
- SourceGraph must expose a unified interface to AudioPump for frame acquisition
- SourceGraph must coordinate with Mixer for node selection and switching

**1.2 SourceGraph Node Management**
- SourceGraph must maintain a registry of source nodes by name
- SourceGraph must pre-declare standard nodes at initialization:
  - `"tone"` — ToneSource node (always available)
  - `"silence"` — SilenceSource node (always available)
  - `"live_pcm"` — LivePCMSource node (always available, wraps AudioInputRouter)
- SourceGraph must create `"file"` nodes on demand when `{"mode": "file", "file_path": "..."}` command is received
- SourceGraph must register nodes with unique names
- SourceGraph must support querying node metadata (type, name, state)
- SourceGraph must handle node creation failures gracefully (log error, exclude from registry)
- SourceGraph MUST NOT auto-create nodes during `push_override` — override nodes must pre-exist

**1.3 SourceGraph Interface**
- SourceGraph must provide `get_node(name: str) -> Optional[SourceNode]` method
- SourceGraph must provide `list_nodes() -> List[str]` method (returns node names)
- SourceGraph must provide `create_node(type: str, name: str, **kwargs) -> SourceNode` method
- SourceGraph must coordinate with Mixer for active node selection
- SourceGraph must expose active node's `next_frame()` to AudioPump

**1.4 SourceGraph Thread Safety**
- SourceGraph must be thread-safe (AudioPump and control API may access concurrently)
- Node registry operations must be thread-safe
- Node creation and cleanup must be thread-safe
- SourceGraph must not block AudioPump thread during node operations

---

### 2. SourceNode Abstraction

**2.1 SourceNode Interface**
- All source nodes must implement a common `SourceNode` interface/protocol
- SourceNode must expose `next_frame() -> Optional[bytes]` method
  - Returns a frame (4096 bytes) if available
  - Returns `None` if node cannot produce a frame (failed, ended, unavailable)
- SourceNode must expose `get_metadata() -> Dict[str, Any]` method
  - Returns node metadata including: `type`, `name`, `state`
  - Metadata must be immutable or thread-safe to read
- SourceNode must produce frames in canonical PCM format (same as Phase 1–4)

**2.2 SourceNode Types**
- SourceGraph must support these node types:
  - `"tone"` — wraps ToneSource
  - `"silence"` — wraps SilenceSource
  - `"file"` — wraps FileSource (requires `file_path` parameter)
  - `"live_pcm"` — wraps LivePCMSource (wraps AudioInputRouter)
- Each node type must expose consistent `next_frame()` interface
- Each node type must expose type-specific metadata (e.g., FileSource exposes `file_path`)

**2.3 SourceNode State**
- SourceNode must expose a `state` field in metadata
- State values: `"active"`, `"inactive"`, `"failed"`, `"ended"` (implementation-defined)
- State must reflect node's ability to produce frames
- State transitions must be observable and consistent

**2.4 SourceNode Lifecycle**
- SourceNode must handle initialization errors gracefully
- SourceNode must handle runtime errors gracefully (transition to failed/ended state)
- FileSource nodes must handle file I/O errors gracefully
- LivePCMSource nodes must handle router failures gracefully
- Node cleanup must not leak resources

---

### 3. Mixer Component

**3.1 Component Purpose**
- Tower must implement a `Mixer` component
- Mixer must act as a simple "node selector" (not DSP mixer)
- Mixer must maintain primary source reference
- Mixer must maintain override stack
- Mixer must determine the active node (primary or top of override stack)

**3.2 Primary Source Management**
- Mixer must track exactly ONE primary source node (by name)
- Mixer must support `set_primary_source(name: str)` method
- Mixer must validate that primary source name exists in SourceGraph
- Mixer must handle primary source switching on frame boundaries
- Mixer must fall back to ToneSource if primary source is invalid or unavailable

**3.3 Override Stack Management**
- Mixer must maintain an override stack (LIFO: last-in-first-out)
- Mixer must support `push_override(node_name: str)` method
- Mixer must support `pop_override()` method
- Override stack must be empty by default
- Override stack MUST support at least 8 entries
- Override stack MUST NOT exceed 128 entries
- Override stack must prevent circular dependencies or invalid states

**3.4 Active Node Selection**
- Mixer must determine active node using these rules:
  1. If override stack is not empty, active node = top of override stack
  2. If override stack is empty, active node = primary source
  3. If active node fails or returns `None`, fallback to ToneSource
- Mixer must expose `get_active_node() -> Optional[SourceNode]` method
- Active node selection must be atomic (no intermediate states visible to AudioPump)
- Active node selection must be thread-safe

**3.5 Frame-Boundary Switching**
- Mixer must ensure all node switches occur on frame boundaries
- Mixer must not switch nodes mid-frame (switching only between frames)
- AudioPump must never see a partial switch (one frame from old node, next from new node)
- Switching logic must be synchronized with AudioPump's frame acquisition

**3.6 Mixer Thread Safety**
- Mixer must be thread-safe (AudioPump and control API may access concurrently)
- Primary source changes must be atomic
- Override stack operations must be atomic
- Active node selection must be atomic

---

### 4. Source Graph Behavior

**4.1 Primary Active Node Guarantee**
- Exactly ONE "primary active node" must be active at any given time
- Primary active node is determined by:
  - Override stack (if not empty): top of stack is active
  - Primary source (if override stack is empty): primary source is active
  - Fallback (if active node fails): ToneSource is active
- AudioPump must always receive frames from exactly one active node

**4.2 Override Stack Behavior**
- When `push_override(node_name)` is called:
  - Node name must be pushed onto override stack
  - Active node immediately switches to the pushed node (on next frame boundary)
  - Previous active node (primary or previous override) is preserved in stack
- When `pop_override()` is called:
  - Top node is removed from override stack
  - Active node switches back to previous node (primary or next override in stack)
  - Switching occurs on next frame boundary
- Override stack must support multiple pushes (stack can have multiple overrides)
- Override stack must handle empty stack gracefully (pop on empty stack is no-op or error)

**4.3 Switching Rules**
- All switches must occur on frame boundaries (between frames, not mid-frame)
- Switching must be clean (no audio glitches beyond MP3 decoder resynchronization)
- Switching must not interrupt AudioPump's real-time pacing
- Switching must not cause frame gaps or duplicates
- Switching must complete within bounded time (≤1 frame period, exactly 21.333 ms)

**4.4 Fallback Rules**
- If active node's `next_frame()` returns `None`:
  - Mixer must immediately fall back to ToneSource
  - Fallback must occur on same frame boundary (no delay)
  - AudioPump must receive ToneSource frame instead of `None`
- Fallback triggers include:
  - Active node fails to produce a frame
  - LivePCMSource active but router gives `None` (no writer, timeout, etc.)
  - FileSource node enters failed state (file I/O errors, file deleted, etc.)
  - Active node enters failed/ended state
- **FileSource looping behavior:** FileSource nodes must loop automatically at EOF (same as Phase 2). FileSource nodes only trigger fallback on file I/O errors, not on normal EOF (EOF triggers automatic loop restart).
- When fallback occurs:
  - ToneSource node must be used (created if needed)
  - Active node remains in override stack or primary (fallback is temporary)
  - If active node recovers, switching back must occur on next frame boundary

**4.5 AudioPump Integration**
- AudioPump must call Mixer's active node `next_frame()` method
- Mixer must never block AudioPump's frame acquisition
- Mixer must return a frame (or ToneSource fallback) within bounded time
- AudioPump timing must remain independent of source switching operations
- AudioPump must continue generating frames at exactly 21.333ms intervals during switches (Tower is the sole metronome, absolute clock timing)

---

### 5. Control API Extensions

**5.1 POST /control/source Extensions**
- `/control/source` endpoint must continue to support existing Phase 2–4 behavior:
  - `{"mode": "tone"}` — sets primary source to tone
  - `{"mode": "silence"}` — sets primary source to silence
  - `{"mode": "file", "file_path": "/path/to/file.wav"}` — sets primary source to file
- `/control/source` endpoint must support new Phase 5 commands:
  - `{"set_primary": "node_name"}` — sets primary source to named node
  - `{"push_override": "node_name"}` — pushes override node onto stack
  - `{"pop_override": true}` or `{"pop_override": null}` — pops override from stack

**5.2 set_primary Command**
- Request format: `{"set_primary": "node_name"}`
- `node_name` must be a string (e.g., "tone", "silence", "file", "live_pcm")
- Tower must validate that `node_name` exists in SourceGraph
- Tower MUST NOT auto-create nodes during `set_primary` — node must pre-exist
- Tower must return 400 if `node_name` is invalid, missing, or does not exist
- Tower must set primary source atomically
- Tower must return 200 OK on success
- Response format: `{"status": "ok", "primary_source": "node_name"}`

**5.3 push_override Command**
- Request format: `{"push_override": "node_name"}`
- `node_name` must be a string (e.g., "tone", "silence", "file", "live_pcm", "bumper", "alert")
- Tower must validate that `node_name` exists in SourceGraph
- Tower MUST NOT auto-create nodes during `push_override` — override nodes must pre-exist
- Tower must return 400 if `node_name` is invalid, missing, or does not exist
- Tower must return 400 if override stack would exceed maximum size (128 entries)
- Tower must push override onto stack atomically
- Tower must return 200 OK on success
- Response format: `{"status": "ok", "override_stack": ["node_name", ...]}`

**5.4 pop_override Command**
- Request format: `{"pop_override": true}` or `{"pop_override": null}`
- Tower must pop top override from stack atomically
- Tower must return 200 OK on success (even if stack was empty)
- Tower must return 400 if request format is invalid
- Response format: `{"status": "ok", "override_stack": [...]}` (updated stack)

**5.5 Command Validation**
- Tower must validate all command parameters
- Tower must return 400 for invalid commands or missing parameters
- Tower must return 400 if node name does not exist in SourceGraph
- Tower must return 400 if override stack would exceed maximum size (128 entries)
- Tower MUST NOT auto-create nodes for `set_primary` or `push_override` commands — nodes must pre-exist
- Tower must handle concurrent command requests gracefully (thread-safe)

**5.6 Backward Compatibility**
- Existing Phase 2–4 commands must continue to work:
  - `{"mode": "tone"}` → sets primary to "tone" node (pre-declared)
  - `{"mode": "silence"}` → sets primary to "silence" node (pre-declared)
  - `{"mode": "file", "file_path": "/path/to/file.wav"}` → creates "file" node with path, then sets as primary
- **Node creation via mode commands:** The `{"mode": "file", "file_path": "..."}` command is the ONLY way to create file nodes. File nodes are created on-demand when this command is received, then set as primary. Other commands (`set_primary`, `push_override`) require nodes to pre-exist.
- Phase 2–4 behavior must remain unchanged when using mode commands

---

### 6. Status API Extensions

**6.1 GET /status Extensions**
- `/status` endpoint must continue to return all Phase 2–4 fields:
  - `source_mode` (string, for backward compatibility)
  - `file_path` (string | null, for backward compatibility)
  - `num_clients` (integer)
  - `encoder_running` (boolean)
  - `uptime_seconds` (number)
- `/status` endpoint must add new Phase 5 fields:
  - `primary_source` (string | null) — name of primary source node
  - `override_stack` (array of strings) — override stack (top to bottom, newest to oldest)
  - `active_source` (string | null) — name of currently active source node

**6.2 primary_source Field**
- `primary_source` must be the name of the current primary source node
- `primary_source` must be `null` if no primary source is set (should not occur in normal operation)
- `primary_source` must match one of the nodes in SourceGraph

**6.3 override_stack Field**
- `override_stack` must be an array of node names
- Array order: top of stack (newest override) first, bottom (oldest) last
- Array must be empty `[]` if no overrides are active
- Each entry must be a valid node name from SourceGraph

**6.4 active_source Field**
- `active_source` must be the name of the currently active source node
- `active_source` must be:
  - Top of `override_stack` if stack is not empty
  - `primary_source` if override stack is empty
  - `"tone"` (or fallback node name) if active node failed and fallback is active
- `active_source` must never be `null` (fallback ensures always a valid source)

**6.5 Backward Compatibility**
- Existing Phase 2–4 clients must continue to work (may ignore new fields)
- `source_mode` and `file_path` fields must remain for backward compatibility
- `source_mode` should reflect primary source mode (if primary is a standard mode)
- `/status` response must remain valid JSON with all existing fields

---

### 7. Compatibility with Prior Phases

**7.1 Phase 1 Compatibility**
- All Phase 1 behavior must remain unchanged:
  - `/stream` endpoint semantics (continuous MP3, same headers)
  - FFmpeg command and encoding format
  - MP3 stream format and structure
  - Client connection handling
- Phase 1 tests must continue to pass
- When only ToneSource is used, behavior must be identical to Phase 1

**7.2 Phase 2 Compatibility**
- All Phase 2 behavior must remain unchanged:
  - `/status` endpoint (existing fields unchanged, new fields added)
  - `/control/source` endpoint (existing commands unchanged, new commands added)
  - SourceManager behavior (if still used internally, or SourceGraph wraps it)
  - Source switching does not interrupt Tower operation
- Phase 2 tests must continue to pass
- When using mode commands (`{"mode": "tone"}`), behavior must be identical to Phase 2

**7.3 Phase 3 Compatibility**
- All Phase 3 behavior must remain unchanged:
  - Unix socket input semantics
  - AudioInputRouter queue behavior (bounded queue, drop newest on overflow)
  - AudioPump fallback behavior (live PCM → fallback source)
  - Seamless switching between live PCM and fallback
- Phase 3 tests must continue to pass
- When LivePCMSource is active, behavior must be identical to Phase 3

**7.4 Phase 4 Compatibility**
- All Phase 4 behavior must remain unchanged:
  - EncoderManager encoder restart logic
  - Slow-client detection and handling
  - Backpressure protections
  - Tower stability during encoder failures
- Phase 4 tests must continue to pass
- SourceGraph must not interfere with encoder robustness features

**7.5 External API Compatibility**
- HTTP endpoints must remain backward compatible:
  - `/stream` endpoint must accept same requests, return same headers
  - `/status` endpoint must return same JSON structure (may add fields)
  - `/control/source` endpoint must accept same requests, return same responses (may add new commands)
- MP3 stream output must remain identical in format and structure
- Client connection behavior must remain identical

**7.6 Internal Architecture Compatibility**
- AudioPump must continue to function as in Phase 3–4
- AudioInputRouter must continue to function as in Phase 3–4
- EncoderManager must continue to function as in Phase 4
- HTTPConnectionManager must maintain backward compatibility
- SourceGraph may wrap or replace SourceManager (implementation choice)

---

## Explicit Invariants

### SourceGraph Invariants

**I1: Node Registry Consistency**
- SourceGraph must maintain consistent node registry at all times
- Node names must be unique within registry
- Node registry operations must be atomic
- Node registry must never be in invalid state

**I2: Node Creation Guarantee**
- SourceGraph must create nodes on demand or fail gracefully
- Node creation failures must not crash Tower
- Invalid node creation requests must be rejected (return None or raise exception)
- Node creation must be thread-safe

**I3: SourceNode Interface Compliance**
- All SourceNodes must implement `next_frame() -> Optional[bytes]`
- All SourceNodes must implement `get_metadata() -> Dict[str, Any]`
- All SourceNodes must produce frames in canonical PCM format (4096 bytes)
- SourceNode interface must be consistent across all node types

### Mixer Invariants

**I4: Single Active Node**
- Exactly ONE node must be active at any given time
- Active node must be determinable from primary source and override stack state
- Active node selection must be atomic (no intermediate states visible)
- Active node must never be `None` (fallback ensures ToneSource)

**I5: Override Stack Validity**
- Override stack must be a valid LIFO stack at all times
- Override stack must never contain invalid node names
- Override stack MUST support at least 8 entries
- Override stack MUST NOT exceed 128 entries
- Override stack operations must be atomic

**I6: Frame-Boundary Switching**
- All node switches must occur on frame boundaries
- No partial switches (one frame from old node, next from new node)
- Switching must complete within one frame period (exactly 21.333 ms)
- AudioPump must never see inconsistent active node state

**I7: Fallback Guarantee**
- If active node returns `None`, Mixer must fall back to ToneSource immediately
- Fallback must occur on same frame boundary (no delay)
- Fallback must ensure AudioPump always receives a frame
- Fallback must not block AudioPump timing

**I8: Mixer Thread Safety**
- Mixer operations must be thread-safe
- Primary source changes must be atomic
- Override stack operations must be atomic
- Active node selection must be atomic
- Mixer must not block AudioPump thread

### AudioPump Integration Invariants

**I9: AudioPump Independence (Tower is the Sole Metronome)**
- AudioPump must continue running at exactly 21.333ms intervals during source switches (absolute clock timing)
- AudioPump timing must not depend on source switching operations, router state, or Station write pattern
- Mixer must never block AudioPump frame acquisition
- AudioPump must receive frames at consistent rate (one per exactly 21.333 ms)
- Tower is the sole metronome — Station writes unpaced bursts, Tower pulls steady

**I10: Frame Continuity**
- AudioPump must always receive a frame (never `None` from Mixer)
- No frame gaps or duplicates during switches
- Frame boundaries must be respected during switches
- PCM stream to encoder must remain continuous

### Control API Invariants

**I11: Command Atomicity**
- `set_primary` command must switch primary source atomically
- `push_override` command must push override atomically
- `pop_override` command must pop override atomically
- Command responses must reflect consistent state

**I12: Command Validation**
- All control commands must validate node names
- Invalid commands must return 400 Bad Request
- Valid commands must return 200 OK
- Command validation must not block audio threads

**I13: Backward Compatibility**
- Existing Phase 2–4 commands must continue to work
- Mode commands (`{"mode": "tone"}`) must set primary source
- Control API must remain backward compatible

### Status API Invariants

**I14: Status Consistency**
- `/status` response must reflect consistent SourceGraph state
- `primary_source`, `override_stack`, `active_source` must be consistent
- `active_source` must match actual active node
- Status fields must be thread-safe to read

**I15: Status Backward Compatibility**
- Existing Phase 2–4 fields must remain unchanged
- New Phase 5 fields must not break existing clients
- `/status` response must remain valid JSON

### Fallback Invariants

**I16: Fallback Trigger Consistency**
- Fallback must trigger when active node returns `None`
- Fallback must trigger when LivePCMSource router gives `None`
- Fallback must trigger when FileSource node enters failed state (file I/O errors, not normal EOF)
- Fallback must NOT trigger on FileSource normal EOF (FileSource loops automatically)
- Fallback must trigger when active node enters failed/ended state

**I17: Fallback Behavior**
- Fallback must use ToneSource node
- Fallback must occur on same frame boundary (no delay)
- Fallback must ensure AudioPump receives frame
- Active node must remain in override stack or primary (fallback is temporary)

### Test Compatibility Invariants

**I18: Phase 1–4 Test Compatibility**
- All Phase 1 tests must continue to pass
- All Phase 2 tests must continue to pass
- All Phase 3 tests must continue to pass
- All Phase 4 tests must continue to pass
- Phase 5 behavior must remain identical to Phase 1–4 when using only standard sources

---

## Test Mapping

Each contract requirement above maps directly to one or more test cases in `tests/contracts/test_phase5_source_graph.py`:

- **Section 1 (SourceGraph Component)** → SourceGraph tests, node registry tests, node management tests, thread-safety tests
- **Section 2 (SourceNode Abstraction)** → SourceNode interface tests, node type tests, node state tests, node lifecycle tests
- **Section 3 (Mixer Component)** → Mixer tests, primary source tests, override stack tests, active node selection tests, frame-boundary switching tests
- **Section 4 (Source Graph Behavior)** → Primary active node tests, override stack behavior tests, switching rules tests, fallback rules tests, AudioPump integration tests
- **Section 5 (Control API Extensions)** → set_primary tests, push_override tests, pop_override tests, command validation tests, backward compatibility tests
- **Section 6 (Status API Extensions)** → primary_source field tests, override_stack field tests, active_source field tests, backward compatibility tests
- **Section 7 (Compatibility)** → Phase 1 regression tests, Phase 2 regression tests, Phase 3 regression tests, Phase 4 regression tests, external API compatibility tests
- **Invariants I1–I3 (SourceGraph)** → Node registry consistency tests, node creation tests, SourceNode interface compliance tests
- **Invariants I4–I8 (Mixer)** → Single active node tests, override stack validity tests, frame-boundary switching tests, fallback guarantee tests, mixer thread-safety tests
- **Invariants I9–I10 (AudioPump)** → AudioPump independence tests, frame continuity tests
- **Invariants I11–I13 (Control API)** → Command atomicity tests, command validation tests, backward compatibility tests
- **Invariants I14–I15 (Status API)** → Status consistency tests, backward compatibility tests
- **Invariants I16–I17 (Fallback)** → Fallback trigger tests, fallback behavior tests
- **Invariant I18 (Test Compatibility)** → Phase 1–4 regression tests, test compatibility verification

---

## Out of Scope (Explicitly Excluded)

The following features are explicitly excluded from Phase 5:

- ❌ DSP mixing (volume curves, crossfading, audio blending, gain adjustment)
- ❌ Multiple simultaneous active sources (only one node active at a time)
- ❌ Complex layering rules beyond override stack (no volume mixing, no blending)
- ❌ Source scheduling or automation (manual control only)
- ❌ New source types (uses existing: ToneSource, SilenceSource, FileSource, LivePCMSource)
- ❌ Custom node types beyond standard source wrappers
- ❌ Source graph visualization or debugging endpoints
- ❌ Source graph persistence or state restoration
- ❌ Source graph history or audit logging
- ❌ Changes to Unix socket input semantics (AudioInputRouter behavior unchanged)
- ❌ Changes to encoder or HTTP server behavior (encoder/HTTP unchanged)
- ❌ Changes to fallback behavior for Live PCM (router None → ToneSource remains)
- ❌ Per-source statistics or metrics (beyond basic metadata)
- ❌ Source graph import/export or configuration files
- ❌ Source graph validation beyond node existence checks

---

## Success Criteria

Phase 5 is complete when:

1. ✅ SourceGraph component exists and owns multiple sources as nodes
2. ✅ SourceNode abstraction exposes `next_frame()` and metadata interface
3. ✅ Mixer component exists as simple node selector with override stack
4. ✅ Primary source selection works (`set_primary_source(name)`)
5. ✅ Override stack management works (`push_override`, `pop_override`)
6. ✅ All switching occurs on frame boundaries (clean switching)
7. ✅ Fallback to ToneSource works when active node fails
8. ✅ Control API extensions work (`set_primary`, `push_override`, `pop_override`)
9. ✅ Status API extensions work (`primary_source`, `override_stack`, `active_source`)
10. ✅ AudioPump integration works (Mixer never blocks AudioPump)
11. ✅ All Phase 1 contract tests still pass
12. ✅ All Phase 2 contract tests still pass
13. ✅ All Phase 3 contract tests still pass
14. ✅ All Phase 4 contract tests still pass
15. ✅ All Phase 5 contract tests pass
16. ✅ All invariants are verified by tests
17. ✅ Behavior remains identical to Phase 4 when using only ToneSource or Live PCM
18. ✅ No DSP mixing is implemented (only clean switching)
19. ✅ Override stack never deadlocks or enters invalid state
20. ✅ SourceGraph always returns a frame (or fallback) to AudioPump

---

**Document:** Tower Phase 5 Source Graph Contract  
**Version:** 1.0  
**Last Updated:** 2025-01-XX

