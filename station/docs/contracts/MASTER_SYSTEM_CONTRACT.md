# Master System Contract — THINK/DO Event Model

## Purpose

This is the umbrella contract that defines the fundamental event-driven architecture for Station. All other contracts reference and depend on this model.

The THINK/DO model ensures that decision-making (THINK) is completely separated from execution (DO), preventing blocking operations and ensuring predictable, real-time audio playout.

---

## E0 — THINK/DO Event Model

### E0.1 — Lifecycle Events

Every segment **MUST** trigger exactly two lifecycle events:

1. **`on_segment_started(segment)`** → **THINK** phase
2. **`on_segment_finished(segment)`** → **DO** phase

### E0.2 — THINK Before DO

**THINK** **MUST** always complete before **DO** begins.

- THINK phase prepares all decisions and creates DJIntent
- DO phase executes the prepared intent without making decisions

### E0.3 — Non-Blocking DO

**DO** operations **MUST** be non-blocking and **MUST** finish before the next segment starts.

- DO operations may queue work but must not block the playout thread
- All DO work must complete within the current segment's duration

### E0.4 — DO Execution Only

**DO** events **MUST** never perform selection logic — only execute previously prepared intent.

- DO receives a complete DJIntent from THINK
- DO executes the intent: enqueue segments, apply IDs, etc.
- DO does NOT select songs, check cooldowns, or make routing decisions

### E0.5 — THINK Fallback

If **THINK** fails, the system **MUST** fall back to safe, substitution-based intent (all decisions still resolved before DO).

- THINK failures must not prevent DO from executing
- Fallback intent must be complete and valid
- All decisions must be resolved before DO begins, even in failure cases

### E0.6 — Queue Modification

No component **MAY** modify the playout queue except **DO**.

- THINK prepares intent but does not modify the queue
- PlayoutEngine reads from the queue but does not modify it
- Only DO operations may enqueue, dequeue, or reorder segments

---

## Contract Dependencies

All other Station contracts reference this contract:

- **StationLifecycle Contract**: Defines startup/shutdown within THINK/DO model
- **DJEngine Contract**: Implements THINK phase
- **DJIntent Contract**: Defines the output of THINK phase
- **PlayoutEngine Contract**: Executes DO phase
- **AudioEvent Contract**: Atomic unit passed from THINK to DO

---

## Implementation Notes

- THINK phase typically occurs during `on_segment_started()` callback
- DO phase typically occurs during `on_segment_finished()` callback
- The separation ensures playout never blocks on decision-making
- All state mutations (queue, rotation history) occur only during DO





