# Contract-Test-Code Rules

## Core Principles

### 1. Contracts are the source of truth.

Contracts define what must be true.

**They may never be changed, rewritten, softened, or "interpreted differently."**

### 2. Tests must validate the contracts exactly as written.

When running or refining tests:

- **You may only add missing tests that enforce contract requirements.**
- **You may NOT weaken tests to make code pass.**
- **You may NOT delete tests unless they contradict the contract, and then you must document why.**

### 3. Code MUST be changed to satisfy tests and contracts.

When a test fails:

- **Fix the implementation, not the contract.**
- **Never adjust the contract to match the code.**
- **Never alter tests simply to silence failures.**

### 4. If a contract appears inconsistent or impossible:

- **DO NOT modify it.**
- **Instead, write a clear entry in a file called FINDINGS.md explaining the issue.**
- **Continue coding in the spirit of the contract until clarified.**

### 5. When running all tests:

- **Fix failures one by one.**
- **Maintain the invariant: contracts → tests → code (in that order).**
- **Never reorder this chain.**

### 6. Prohibited actions for Cursor:

- **No speculative contract edits.**
- **No rewriting contract text.**
- **No removing failing tests unless they contradict the contract (and must be documented).**
- **No adding behavior not backed by contracts.**

### 7. Tests should not be made more specific than the contract requires.

But they **MUST fully cover all contract requirements.**

---

## Contract Documents

The following contracts are the source of truth:

- `tower/docs/contracts/NEW_CORE_TIMING_AND_FORMATS_CONTRACT.md` (C-series: timing, formats, buffers)
- `tower/docs/contracts/NEW_ENCODER_MANAGER_CONTRACT.md` (M-series: routing, grace period, fallback)
- `tower/docs/contracts/NEW_FALLBACK_PROVIDER_CONTRACT.md` (FP-series: fallback source selection)
- `tower/docs/contracts/NEW_TOWER_RUNTIME_CONTRACT.md` (T-series: HTTP endpoints, integration)
- `tower/docs/contracts/NEW_FFMPEG_SUPERVISOR_CONTRACT.md` (S-series: encoder lifecycle)
- `tower/docs/contracts/NEW_AUDIOPUMP_CONTRACT.md` (A-series: timing authority)

## Test Execution

Run contract tests with:
```bash
python3 run_contract_tests.py
```

This generates `CONTRACT_TEST_AUDIT_REPORT.md` with a detailed breakdown of all test results.

## Findings Documentation

If a contract appears inconsistent or impossible, document it in `FINDINGS.md` (in the project root) with:
- Which contract clause(s) are involved
- What the apparent inconsistency is
- Why it appears impossible
- How we're proceeding in the spirit of the contract

---

**Last Updated:** 2025-01-XX  
**Authority:** These rules govern all contract, test, and code modifications.

