# Implementation Plan: Complete and Validate Late Swap Functionality

## Phase 1: Research & Baseline [checkpoint: b7defe6]
- [x] Task: Analyze current `late_swapper.py` implementation and identify missing logic. (Commit: b5eac54)
    - *Findings:*
        - Locking logic depends on "(LOCKED)" string; needs to use game start times.
        - Missing flexible slotting optimization (late players in UTIL).
        - CSV reading/writing needs to be more robust for DK compatibility.
- [x] Task: Create a baseline test suite with a mock `DKEntries.csv` and projections.
- [x] Task: Conductor - User Manual Verification 'Phase 1: Research & Baseline' (Protocol in workflow.md)

## Phase 2: Core Implementation [checkpoint: a524455]
- [x] Task: Implement robust player locking logic based on (LOCKED) string in Name + ID. (Commit: 1212ab7)
- [x] Task: Implement the PuLP optimization loop for per-lineup re-optimization. (Commit: 84c4d96)
- [x] Task: Implement flexible roster slotting to maximize late-swap options. (Commit: 708f13b)
- [x] Task: Conductor - User Manual Verification 'Phase 2: Core Implementation' (Protocol in workflow.md)

## Phase 3: Export & Validation
- [ ] Task: Finalize the CSV export logic to match DraftKings' late-swap format.
- [ ] Task: Perform an end-to-end dry run with real data.
- [ ] Task: Conductor - User Manual Verification 'Phase 3: Export & Validation' (Protocol in workflow.md)

## Phase: Review Fixes
- [x] Task: Apply review suggestions for string-based locking logic. (Commit: 1212ab7)
