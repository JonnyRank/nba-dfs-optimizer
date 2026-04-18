# Testing Patterns

## Core Sections (Required)

### 1) Test Stack and Commands

- Primary test framework: None configured
- Assertion/mocking tools: None configured
- Commands: N/A

```bash
# No test commands available
```

### 2) Test Layout

- Test file placement pattern: Previously had a `tests/` directory (evidenced by git churn: `tests/test_late_swapper.py`, `tests/test_data/DKEntries.csv`). These files were removed in commit `f0498b1` ("chore: remove deprecated test data and scripts").
- Current state: No test files exist in the repository.

### 3) Test Scope Matrix

| Scope | Covered? | Typical target | Notes |
|-------|----------|----------------|-------|
| Unit | No | N/A | No test files exist |
| Integration | No | N/A | No test files exist |
| E2E | No (manual) | Full pipeline | Verification is done by running the pipeline and inspecting CSV output |

### 4) Mocking and Isolation Strategy

- No mocking strategy exists. The project has no test infrastructure.

### 5) Coverage and Quality Signals

- Coverage tool + threshold: None
- Current reported coverage: None
- Known gaps: All code is untested. The highest-churn files (`engine.py` at 14 changes, `late_swapper.py` at 8) have no automated tests.

### 6) Evidence

- Git churn output (scan): `tests/test_late_swapper.py` appears in high-churn list but no longer exists
- Commit `f0498b1`: "chore: remove deprecated test data and scripts"
- `README.md`: No mention of testing or test commands
