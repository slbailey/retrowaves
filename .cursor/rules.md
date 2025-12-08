# Tower Dev Workflow Rules

## Primary Objective

Cursor MUST run **pytest across ALL tests** and evaluate real current-state compliance.

## Core Workflow Philosophy

**Contracts are the source of truth** - They represent what we want.

**Tests verify contracts** - Tests are crafted to test components to make sure we are able to get what we want.

**Implementation follows** - Code implements to satisfy contracts/tests.

The workflow is: **contracts → tests → implementation**.

When a test fails:
- **If implementation is wrong** → Fix the code
- **If contract/requirements are wrong** → Document as a finding (don't change contracts without discussion)

---

## Golden Rules (Non-Negotiable)

### Decision Process for Test Failures

For each failing test:
1. **Check the contract requirement** - What does the contract say we want?
2. **Check if the test correctly verifies the contract** - Does the test accurately test the contract?
3. **If both are correct** → Fix the implementation (code is wrong)
4. **If contract needs clarification or is wrong** → Document as a finding (don't change contracts without discussion)

### DO NOT:
- Change contracts without documenting as a finding first
- Update tests to force them to pass unless the test is objectively broken (syntax/typo)
- Implement features not explicitly defined in contracts
- Assume contract intent - if unclear, document as finding

### Allowed:
- ✓ Fix implementation when it doesn't match contract requirements
- ✓ Fix syntax errors, import paths, missing parentheses
- ✓ Update tests if they incorrectly verify the contract (test bug, not contract change)

### Not Allowed:
- ✗ Changing contracts without discussion/documentation
- ✗ Modifying architecture without contract support

---

## Required Behavior When Running Tests

When instructed to run full contract validation:

### 1. Run Tests
```bash
pytest -q --disable-warnings --maxfail=1
```
Then continue with `pytest --continue-on-collection-errors` style behavior.

### 2. For Each Failure
- Stop at the failure point
- **Determine root cause**:
  1. Read the contract requirement being tested
  2. Verify the test correctly tests the contract
  3. Check if implementation matches contract
- **Decision**:
  - **If contract is correct and test is correct** → Fix implementation (IMPLEMENTATION DEFECT)
  - **If contract is unclear/wrong** → Document as finding (CONTRACT ISSUE / UNCLEAR SPEC)
  - **If test incorrectly verifies contract** → Fix test (TEST BUG)
  - **If syntax error** → Fix syntax (SYNTAX FIXED)
- Fix code **ONLY** if:
  - Implementation doesn't match contract (implementation defect)
  - Syntax/import/typo errors

### 3. Log Finding in Findings Report

Format:
```
<TestName>
Status: PASS | FAIL
Reason: (traceback summary)
Category: SYNTAX FIXED | IMPLEMENTATION DEFECT | CONTRACT ISSUE | TEST BUG | UNCLEAR SPEC
Contract Reference: (section)
Root Cause: (contract correct? test correct? implementation correct?)
Next Action Required: (fix code / document contract issue / fix test / clarify spec)
```

**Category Definitions:**
- **SYNTAX FIXED**: Trivial syntax/import/typo - fixed immediately
- **IMPLEMENTATION DEFECT**: Contract is correct, test is correct, code is wrong - fix code
- **CONTRACT ISSUE**: Contract needs revision/clarification - document as finding
- **TEST BUG**: Test incorrectly verifies contract - fix test
- **UNCLEAR SPEC**: Contract is ambiguous - document as finding

### 4. Continue
Continue to next test until all tests evaluated.

---

## Output Format Required After Execution

Cursor must return a **Contract Test Audit Report** in the following format:

```
=== CONTRACT TEST AUDIT ===

Tests executed: XXX  | Passed: XXX | Failed: XXX | Errors: XXX



❌ FAIL test_tower_encoder_manager::test_restart_on_stall

Reason: AttributeError: 'NoneType' object has no attribute 'write'

Category: CONTRACT MISMATCH

Resolution: Contract requires restart logic, code only logs.



⚠ FAIL test_tower_http_connection_manager::test_remove_client_by_id

Reason: function signature mismatch

Category: CONTRACT OUT OF DATE

Resolution: Contract must be revised



✔ PASS test_tower_fallback_generator::test_generates_tone

...
```

### Report Structure

- **Header**: Summary statistics (tests executed, passed, failed, errors)
- **Status Indicators**:
  - `❌ FAIL` - Test failed (contract mismatch or implementation defect)
  - `⚠ FAIL` - Test failed (contract out of date or spec ambiguous)
  - `✔ PASS` - Test passed
- **For Each Test**:
  - Test name (full path)
  - Reason: Brief error summary or pass confirmation
  - Category: CONTRACT MISMATCH | CONTRACT OUT OF DATE | DOCS AMBIGUOUS | IMPLEMENTATION DEFECT | SYNTAX FIXED
  - Resolution: Specific guidance on what needs to be done

### Categories

- **SYNTAX FIXED**: Trivial syntax/import/typo issue that was fixed
- **IMPLEMENTATION DEFECT**: Contract is correct, test is correct, but code doesn't match - **fix code**
- **CONTRACT ISSUE**: Contract needs revision/clarification - **document as finding**
- **TEST BUG**: Test incorrectly verifies the contract - **fix test**
- **UNCLEAR SPEC**: Contract is ambiguous or unclear - **document as finding**

**Important:** Cursor must NOT claim full compliance unless tests executed and verified.

---

## Behavior Overrides for LLM

When interacting in a Tower context:

- **Contracts are the source of truth** - They define what we want
- **Tests verify contracts** - They ensure we can achieve what we want
- **Implementation must satisfy both** - Code must match contracts and pass tests
- Prefer truth over optimism
- If uncertain about behavior → **flag ambiguity, do not assume**
- When contracts conflict with code → **Determine if contract is wrong or code is wrong**
  - If contract is wrong → Document as finding
  - If code is wrong → Fix code
- If no contract exists for failing behavior → mark as "SPEC UNDEFINED"

---

## TL;DR

> **Contracts are the source of truth.**  
> **Tests verify contracts.**  
> **Implementation must satisfy both.**  
> 
> **When tests fail:**
> - If contract is correct and test is correct → Fix code
> - If contract is wrong/unclear → Document as finding
> - If test is wrong → Fix test