# Implementation Plan: Complete and Validate Late Swap Functionality

## Phase 1: Research & Baseline
- [x] Task: Analyze current `late_swapper.py` implementation and identify missing logic. (Commit: b5eac54)
    - *Findings:*
        - Locking logic depends on "(LOCKED)" string; needs to use game start times.
        - Missing flexible slotting optimization (late players in UTIL).
        - CSV reading/writing needs to be more robust for DK compatibility.
- [ ] Task: Create a baseline test suite with a mock `DKEntries.csv` and projections.
- [ ] Task: Conductor - User Manual Verification 'Phase 1: Research & Baseline' (Protocol in workflow.md)

## Phase 2: Core Implementation
- [ ] Task: Implement robust player locking logic based on game timestamps.
- [ ] Task: Implement the PuLP optimization loop for per-lineup re-optimization.
    - [ ] Write Tests for optimization logic
    - [ ] Implement optimization logic
- [ ] Task: Implement flexible roster slotting to maximize late-swap options.
    - [ ] Write Tests for slotting logic
    - [ ] Implement slotting logic
- [ ] Task: Conductor - User Manual Verification 'Phase 2: Core Implementation' (Protocol in workflow.md)

## Phase 3: Export & Validation
- [ ] Task: Finalize the CSV export logic to match DraftKings' late-swap format.
- [ ] Task: Perform an end-to-end dry run with real data.
- [ ] Task: Conductor - User Manual Verification 'Phase 3: Export & Validation' (Protocol in workflow.md)
