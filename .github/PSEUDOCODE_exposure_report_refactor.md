# Pseudocode Plan: Exposure Report Refactoring

## Overview

This document provides step-by-step pseudocode showing how the `get_latest_file` logic and `argparse` configuration will be refactored to support flexible file parsing.

## Step 1: Extend Config Dataclass

**File**: `src/nba_optimizer/config.py`

```python
# BEFORE (lines 12-33):
@dataclass
class Config:
    # ... existing fields ...
    output_dir: str = "exports"

    def __post_init__(self):
        # ... existing logic ...


# AFTER (insert new field after output_dir):
@dataclass
class Config:
    # ... existing fields ...
    output_dir: str = "exports"
    entries_file_pattern: str = ""  # New field: empty means auto-detect

    def __post_init__(self):
        # ... existing logic ...
```

**Change Type**: Addition only, no breaking changes

---

## Step 2: Add File Resolution Helper Function

**File**: `src/nba_optimizer/exposure_report.py`

**Location**: Insert after imports, before `run()` function (after line 9)

```python
def resolve_entries_file(cfg: Config) -> str:
    """
    Resolves which entries file to analyze.

    Precedence:
        1. cfg.entries_file_pattern (if set) - explicit user choice
        2. late-swap-entries-*.csv (if exists) - more specific/recent
        3. upload-ready-DKEntries-*.csv (if exists) - standard output
        4. Raise FileNotFoundError if none found

    Args:
        cfg: Configuration instance

    Returns:
        Full path to the entries file to analyze

    Raises:
        FileNotFoundError: If no valid entries file is found
    """
    # STEP 2.1: Handle explicit pattern/path
    IF cfg.entries_file_pattern is not empty:
        IF cfg.entries_file_pattern is an absolute path to existing file:
            RETURN cfg.entries_file_pattern
        ELSE:
            # Treat as glob pattern in output_dir
            TRY:
                RETURN get_latest_file(cfg.output_dir, cfg.entries_file_pattern, use_mtime=True)
            CATCH FileNotFoundError:
                RAISE with message "No files matching '{pattern}' in {dir}"

    # STEP 2.2: Auto-detect - try late-swap first
    TRY:
        file = get_latest_file(cfg.output_dir, "late-swap-entries-*.csv", use_mtime=True)
        PRINT "Auto-detected late-swap entries: {basename}"
        RETURN file
    CATCH FileNotFoundError:
        PASS  # Continue to next option

    # STEP 2.3: Auto-detect - try standard upload-ready
    TRY:
        file = get_latest_file(cfg.output_dir, "upload-ready-DKEntries-*.csv", use_mtime=True)
        PRINT "Using standard entries: {basename}"
        RETURN file
    CATCH FileNotFoundError:
        PASS  # Continue to error

    # STEP 2.4: Nothing found - raise comprehensive error
    RAISE FileNotFoundError with message:
        "No entry files found in {cfg.output_dir}. "
        "Expected 'late-swap-entries-*.csv' or 'upload-ready-DKEntries-*.csv'"
```

**Implementation in Python**:

```python
def resolve_entries_file(cfg: Config) -> str:
    """Resolves which entries file to analyze..."""
    # Case 1: Explicit pattern or path provided
    if cfg.entries_file_pattern:
        if os.path.isfile(cfg.entries_file_pattern):
            return cfg.entries_file_pattern
        try:
            return get_latest_file(cfg.output_dir, cfg.entries_file_pattern, use_mtime=True)
        except FileNotFoundError:
            raise FileNotFoundError(
                f"No files matching '{cfg.entries_file_pattern}' in {cfg.output_dir}"
            )

    # Case 2: Auto-detect - try late-swap first
    try:
        late_swap_file = get_latest_file(cfg.output_dir, "late-swap-entries-*.csv", use_mtime=True)
        print(f"Auto-detected late-swap entries: {os.path.basename(late_swap_file)}")
        return late_swap_file
    except FileNotFoundError:
        pass

    # Case 3: Fall back to standard files
    try:
        regular_file = get_latest_file(cfg.output_dir, "upload-ready-DKEntries-*.csv", use_mtime=True)
        print(f"Using standard entries: {os.path.basename(regular_file)}")
        return regular_file
    except FileNotFoundError:
        raise FileNotFoundError(
            f"No entry files found in {cfg.output_dir}. "
            "Expected 'late-swap-entries-*.csv' or 'upload-ready-DKEntries-*.csv'"
        )
```

---

## Step 3: Update run() Function

**File**: `src/nba_optimizer/exposure_report.py`

**Location**: Line 14 in `run()` function

```python
# BEFORE (line 14):
def run(cfg: Config, top_x: int = 0):
    try:
        # 1. Locate latest files
        entries_file = get_latest_file(cfg.output_dir, "upload-ready-DKEntries-*.csv", use_mtime=True)
        projs_file = get_latest_file(cfg.projs_dir, "NBA-Projs-*.csv", use_mtime=True)
        # ... rest of function ...


# AFTER (line 14):
def run(cfg: Config, top_x: int = 0):
    try:
        # 1. Locate latest files
        entries_file = resolve_entries_file(cfg)  # <-- ONLY CHANGE
        projs_file = get_latest_file(cfg.projs_dir, "NBA-Projs-*.csv", use_mtime=True)
        # ... rest of function unchanged ...
```

**Change Type**: Single line replacement, preserves all downstream logic

---

## Step 4: Add CLI Argument

**File**: `src/nba_optimizer/exposure_report.py`

**Location**: Lines 103-111 in `main()` function

```python
# BEFORE (lines 103-114):
def main():
    from .config import load_config_from_env

    parser = argparse.ArgumentParser(description="NBA DFS Exposure Report")
    parser.add_argument(
        "-t",
        "--top_x",
        type=int,
        default=0,
        help="Limit display to top X highest-exposed players. Use 0 for all.",
    )
    args = parser.parse_args()

    cfg = load_config_from_env()
    run(cfg, args.top_x)


# AFTER (add new argument and config override):
def main():
    from .config import load_config_from_env
    from dataclasses import replace  # <-- NEW IMPORT

    parser = argparse.ArgumentParser(description="NBA DFS Exposure Report")
    parser.add_argument(
        "-t",
        "--top_x",
        type=int,
        default=0,
        help="Limit display to top X highest-exposed players. Use 0 for all.",
    )
    # NEW ARGUMENT:
    parser.add_argument(
        "-f",
        "--entries_file",
        type=str,
        default="",
        help=(
            "Entries file to analyze. Can be: "
            "(1) full path to specific CSV, "
            "(2) glob pattern like 'late-swap-*.csv', or "
            "(3) empty (default) to auto-detect."
        ),
    )
    args = parser.parse_args()

    # Load config and apply CLI override
    cfg = load_config_from_env()
    IF args.entries_file is not empty:
        cfg = replace(cfg, entries_file_pattern=args.entries_file)  # <-- NEW LOGIC

    run(cfg, args.top_x)
```

**Implementation in Python**:

```python
def main():
    from .config import load_config_from_env
    from dataclasses import replace

    parser = argparse.ArgumentParser(description="NBA DFS Exposure Report")
    parser.add_argument(
        "-t",
        "--top_x",
        type=int,
        default=0,
        help="Limit display to top X highest-exposed players. Use 0 for all.",
    )
    parser.add_argument(
        "-f",
        "--entries_file",
        type=str,
        default="",
        help=(
            "Entries file to analyze. Can be: "
            "(1) full path to specific CSV, "
            "(2) glob pattern like 'late-swap-*.csv', or "
            "(3) empty (default) to auto-detect."
        ),
    )
    args = parser.parse_args()

    cfg = load_config_from_env()
    if args.entries_file:
        cfg = replace(cfg, entries_file_pattern=args.entries_file)

    run(cfg, args.top_x)
```

---

## Decision Tree Visualization

```
User runs: python -m nba_optimizer.exposure_report [OPTIONS]

                    │
                    ▼
        ┌───────────────────────┐
        │ Parse CLI arguments   │
        │ - top_x               │
        │ - entries_file        │
        └───────┬───────────────┘
                │
                ▼
        ┌───────────────────────┐
        │ Load Config from env  │
        └───────┬───────────────┘
                │
                ▼
        ┌───────────────────────────────┐
        │ IF args.entries_file != "":   │
        │   cfg = replace(cfg,          │
        │     entries_file_pattern=...) │
        └───────┬───────────────────────┘
                │
                ▼
        ┌───────────────────────┐
        │ Call run(cfg, top_x)  │
        └───────┬───────────────┘
                │
                ▼
        ┌─────────────────────────────┐
        │ Call resolve_entries_file() │
        └───────┬─────────────────────┘
                │
                ▼
        ┌────────────────────────────────────┐
        │ Is cfg.entries_file_pattern set?   │
        └─────┬────────────────────────┬─────┘
              │ YES                    │ NO
              ▼                        ▼
    ┌───────────────────┐    ┌──────────────────────┐
    │ Is it a file path?│    │ Try late-swap-*.csv  │
    └─┬─────────────┬───┘    └────┬────────────┬────┘
      │ YES         │ NO          │ FOUND      │ NOT FOUND
      │             │             │            │
      ▼             ▼             ▼            ▼
    Return    Use pattern    Return     Try upload-ready-*.csv
    path      in get_latest   file      └────┬─────────┬────┘
              _file()                        │ FOUND   │ NOT FOUND
              │                              │         │
              ▼                              ▼         ▼
            Return file                  Return    Raise
                                         file      FileNotFoundError
```

---

## Integration with Existing Workflow

### Scenario 1: Regular Pipeline (No Changes Needed)

```bash
$ python scripts/run_optimizer.py --num_lineups 100

# Pipeline executes:
# 1. engine.run() → lineup-pool-2026-04-24_120000.csv
# 2. ranker.run() → ranked-lineups-2026-04-24_120000.csv
# 3. exporter.run() → upload-ready-DKEntries-2026-04-24_120000.csv
# 4. exposure_report.run()
#    └─> resolve_entries_file() auto-detects upload-ready-DKEntries-2026-04-24_120000.csv
#    └─> Prints "Using standard entries: upload-ready-DKEntries-2026-04-24_120000.csv"
```

### Scenario 2: Late Swap + Manual Report

```bash
$ python scripts/run_optimizer.py --late_swap

# Pipeline executes:
# 1. late_swapper.run() → late-swap-entries-2026-04-24_123000.csv

$ python -m nba_optimizer.exposure_report

# Manual execution:
# 1. resolve_entries_file() auto-detects late-swap-entries-2026-04-24_123000.csv
# 2. Prints "Auto-detected late-swap entries: late-swap-entries-2026-04-24_123000.csv"
```

### Scenario 3: Explicit Historical Analysis

```bash
$ python -m nba_optimizer.exposure_report -f exports/upload-ready-DKEntries-2026-04-20_150000.csv

# Manual execution with explicit file:
# 1. resolve_entries_file() receives cfg.entries_file_pattern = "exports/upload-ready-DKEntries-2026-04-20_150000.csv"
# 2. Checks os.path.isfile() → TRUE
# 3. Returns the exact path without searching
```

### Scenario 4: Pattern-Based Analysis

```bash
$ python -m nba_optimizer.exposure_report -f "late-swap-*.csv"

# Manual execution with pattern:
# 1. resolve_entries_file() receives cfg.entries_file_pattern = "late-swap-*.csv"
# 2. Checks os.path.isfile() → FALSE
# 3. Calls get_latest_file(cfg.output_dir, "late-swap-*.csv", use_mtime=True)
# 4. Returns most recent matching file
```

---

## Test Cases

### Test 1: Auto-Detection with Standard Files Only

**Setup**: Only `upload-ready-DKEntries-*.csv` exists

**Command**: `python -m nba_optimizer.exposure_report`

**Expected**:
- Console prints: "Using standard entries: upload-ready-DKEntries-TIMESTAMP.csv"
- Report generated successfully

### Test 2: Auto-Detection with Late-Swap Files Only

**Setup**: Only `late-swap-entries-*.csv` exists

**Command**: `python -m nba_optimizer.exposure_report`

**Expected**:
- Console prints: "Auto-detected late-swap entries: late-swap-entries-TIMESTAMP.csv"
- Report generated successfully

### Test 3: Auto-Detection with Both Files (Late-Swap Wins)

**Setup**: Both file types exist

**Command**: `python -m nba_optimizer.exposure_report`

**Expected**:
- Console prints: "Auto-detected late-swap entries: late-swap-entries-TIMESTAMP.csv"
- Late-swap file is analyzed (not standard file)

### Test 4: Explicit File Path

**Setup**: Multiple files exist

**Command**: `python -m nba_optimizer.exposure_report -f exports/upload-ready-DKEntries-2026-04-20_120000.csv`

**Expected**:
- No auto-detection messages
- Specific file is analyzed regardless of other files

### Test 5: Explicit Pattern

**Setup**: Multiple matching files exist

**Command**: `python -m nba_optimizer.exposure_report -f "upload-ready-*.csv"`

**Expected**:
- Most recent file matching pattern is analyzed
- Uses mtime sorting

### Test 6: No Files Found (Error Handling)

**Setup**: No entry files in output directory

**Command**: `python -m nba_optimizer.exposure_report`

**Expected**:
- FileNotFoundError raised
- Error message lists expected patterns

### Test 7: Invalid Pattern (Error Handling)

**Setup**: Files exist but don't match user pattern

**Command**: `python -m nba_optimizer.exposure_report -f "nonexistent-*.csv"`

**Expected**:
- FileNotFoundError raised
- Error message mentions the invalid pattern

---

## Code Review Checklist

Before implementation approval:

- [ ] Config change is backward compatible (default empty string)
- [ ] resolve_entries_file() has clear precedence order
- [ ] All error messages are user-friendly and actionable
- [ ] CLI help text documents all three usage modes
- [ ] Follows existing patterns (dataclasses.replace, dependency injection)
- [ ] No changes to calculation logic in run()
- [ ] Console output clearly shows which file was selected
- [ ] Works with both absolute and relative paths
- [ ] Late-swap has higher precedence than standard (more specific)
- [ ] All test scenarios pass manual verification

---

## Summary

This refactoring introduces **three new elements**:

1. **Config field** (`entries_file_pattern`) for dependency injection
2. **Helper function** (`resolve_entries_file`) for smart resolution
3. **CLI argument** (`--entries_file`) for user control

The changes are **minimal and surgical**:
- 1 line added to Config
- 1 new function added to exposure_report.py
- 1 line changed in run()
- 2 lines added to main() (import + config override)
- 1 new CLI argument

**Total LOC impact**: ~40 lines added, 1 line modified

**Backward compatibility**: 100% preserved (auto-detection maintains current behavior)
