# Design Document: Flexible File Parsing for Exposure Report

## Problem Statement

The exposure report module (`src/nba_optimizer/exposure_report.py`) currently hardcodes the filename pattern `"upload-ready-DKEntries-*.csv"` when locating entry files. This creates two issues:

1. **Late Swap Incompatibility**: When users run the late swap flow, entries are exported as `"late-swap-entries-*.csv"`, which the exposure report cannot find automatically.
2. **Lack of User Control**: Users cannot specify a custom entries file to analyze (e.g., for historical analysis or debugging).

## Current Architecture

### File Flow in Pipeline

**Regular Flow:**
```
engine.run() → lineup-pool-*.csv
ranker.run() → ranked-lineups-*.csv
exporter.run() → upload-ready-DKEntries-*.csv
exposure_report.run() → [reads upload-ready-DKEntries-*.csv]
```

**Late Swap Flow:**
```
late_swapper.run() → late-swap-entries-*.csv
exposure_report.run() → [CANNOT find late-swap files!]
```

### Current Implementation

```python
# exposure_report.py:14
entries_file = get_latest_file(cfg.output_dir, "upload-ready-DKEntries-*.csv", use_mtime=True)
```

## Proposed Solution

### Design Principles

1. **Fallback Logic**: Auto-detect whether late-swap or regular files exist if no explicit argument is provided
2. **Explicit Override**: Allow users to pass an explicit file path or pattern via CLI
3. **Dependency Injection**: Follow the existing pattern of Config-based configuration with CLI overrides
4. **Minimal Changes**: Only modify what's necessary in `exposure_report.py` and potentially `config.py`

### Architecture Components

#### 1. Config Extension

Add optional field to `Config` dataclass to store the entries file pattern preference:

```python
# config.py
@dataclass
class Config:
    # ... existing fields ...

    # New field for exposure report
    entries_file_pattern: str = ""  # Empty string means "auto-detect"
```

**Rationale**: This follows the existing pattern where Config holds all pipeline parameters.

#### 2. Fallback Detection Logic

Create a helper function in `exposure_report.py` to implement the fallback logic:

```python
def resolve_entries_file(cfg: Config) -> str:
    """
    Resolves the entries file to analyze with the following precedence:
    1. Explicit cfg.entries_file_pattern if set (could be full path or pattern)
    2. Auto-detect late-swap files if they exist
    3. Fall back to standard upload-ready files

    Returns:
        str: Path to the entries file to analyze

    Raises:
        FileNotFoundError: If no valid entries file can be found
    """
    # Case 1: Explicit pattern or path provided
    if cfg.entries_file_pattern:
        # Check if it's a full path to an existing file
        if os.path.isfile(cfg.entries_file_pattern):
            return cfg.entries_file_pattern

        # Otherwise treat as a glob pattern
        return get_latest_file(cfg.output_dir, cfg.entries_file_pattern, use_mtime=True)

    # Case 2: Auto-detect - try late-swap first (more specific)
    try:
        late_swap_file = get_latest_file(cfg.output_dir, "late-swap-entries-*.csv", use_mtime=True)
        print(f"Auto-detected late-swap entries: {os.path.basename(late_swap_file)}")
        return late_swap_file
    except FileNotFoundError:
        pass  # Fall through to regular files

    # Case 3: Fall back to standard upload-ready files
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

**Rationale**:
- Late-swap files are checked first because they are more specific/recent
- Clear user feedback via print statements about which file was auto-detected
- Comprehensive error message if nothing is found

#### 3. CLI Argument Addition

Add optional argument to `main()` function's argparse configuration:

```python
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
    parser.add_argument(
        "-f",
        "--entries_file",
        type=str,
        default="",
        help=(
            "Entries file to analyze. Can be: "
            "(1) full path to specific CSV, "
            "(2) glob pattern like 'late-swap-*.csv', or "
            "(3) empty to auto-detect (checks late-swap then upload-ready)."
        ),
    )
    args = parser.parse_args()

    # Override config with CLI argument using dependency injection pattern
    cfg = load_config_from_env()
    if args.entries_file:
        cfg = replace(cfg, entries_file_pattern=args.entries_file)

    run(cfg, args.top_x)
```

**Rationale**:
- `-f` / `--entries_file` follows Unix convention (similar to `-t` / `--top_x`)
- Uses `dataclasses.replace()` pattern consistent with `orchestrator.py`
- Help text clearly documents the three usage modes

#### 4. Refactored `run()` Function

Update the `run()` function to use the new resolution logic:

```python
def run(cfg: Config, top_x: int = 0):
    try:
        # 1. Locate files using new flexible resolution
        entries_file = resolve_entries_file(cfg)
        projs_file = get_latest_file(cfg.projs_dir, "NBA-Projs-*.csv", use_mtime=True)

        # Rest of the function remains unchanged...
        # 2. Parse Projections for Ownership
        df_projs = pd.read_csv(projs_file)
        # ... etc
```

**Rationale**: Minimal change to existing function - only line 14 is modified.

### Integration with Orchestrator

The orchestrator does NOT need modification because:

1. **Regular Flow**: Calls `exposure_report.run(config, top_x=args.top_x)` after exporter, which creates `upload-ready-DKEntries-*.csv` → auto-detection will find it
2. **Late Swap Flow**: Currently doesn't call exposure report at all → users can run it manually with `python -m nba_optimizer.exposure_report` and auto-detection will find late-swap files

**Future Enhancement** (not in scope): Could add optional exposure report call after late swap in orchestrator.

## Usage Examples

### Example 1: Auto-detect after regular pipeline
```bash
python scripts/run_optimizer.py
# Creates upload-ready-DKEntries-2026-04-24_120000.csv
# Exposure report automatically finds and analyzes it
```

### Example 2: Auto-detect after late swap
```bash
python scripts/run_optimizer.py --late_swap
# Creates late-swap-entries-2026-04-24_120000.csv

python -m nba_optimizer.exposure_report
# Auto-detects and analyzes late-swap-entries-2026-04-24_120000.csv
```

### Example 3: Explicit file path
```bash
python -m nba_optimizer.exposure_report -f exports/upload-ready-DKEntries-2026-04-23_150000.csv
```

### Example 4: Explicit pattern
```bash
python -m nba_optimizer.exposure_report -f "late-swap-*.csv"
```

## Acceptance Criteria Mapping

- [x] **CLI accepts an optional `--entries_file` or `--prefix` argument**: Implemented as `--entries_file` / `-f`
- [x] **Fallback logic correctly identifies whether to look for standard or late-swap exports if no argument is passed**: Implemented in `resolve_entries_file()` with late-swap checked first

## Testing Strategy

### Manual Verification Steps

1. **Test auto-detection with regular files**:
   ```bash
   python scripts/run_optimizer.py --num_lineups 10
   # Should auto-detect upload-ready-DKEntries-*.csv
   ```

2. **Test auto-detection with late-swap files**:
   ```bash
   python scripts/run_optimizer.py --late_swap
   python -m nba_optimizer.exposure_report
   # Should auto-detect late-swap-entries-*.csv
   ```

3. **Test explicit file path**:
   ```bash
   python -m nba_optimizer.exposure_report -f exports/upload-ready-DKEntries-2026-04-24_120000.csv
   ```

4. **Test explicit pattern**:
   ```bash
   python -m nba_optimizer.exposure_report -f "late-swap-*.csv"
   ```

5. **Test error handling** (no files present):
   ```bash
   rm exports/*.csv
   python -m nba_optimizer.exposure_report
   # Should show clear error message
   ```

### Output Validation

For each test, verify:
- Correct file is identified (check console output)
- Exposure statistics are calculated correctly
- No changes to output format or calculation logic

## Files to Modify

1. **`src/nba_optimizer/config.py`**: Add `entries_file_pattern: str = ""` field
2. **`src/nba_optimizer/exposure_report.py`**:
   - Add `resolve_entries_file()` helper function
   - Update `run()` to call `resolve_entries_file()` instead of hardcoded pattern
   - Add `--entries_file` argument to `main()` with config override

## Risks and Mitigations

| Risk | Mitigation |
|------|------------|
| Breaking existing workflows | Auto-detection maintains backward compatibility |
| Confusing precedence order | Clear console messages show which file was selected |
| Pattern matching multiple files | `get_latest_file()` already handles this via `use_mtime=True` |
| Users forget which flow created which files | Console output shows the basename of the file being analyzed |

## Future Enhancements (Out of Scope)

1. Add exposure report call to orchestrator after late swap flow
2. Support analyzing multiple files and showing comparative exposure
3. Add `--output` flag to save report to CSV instead of console
4. Allow pattern to search in directories other than `cfg.output_dir`

## Summary

This design maintains architectural consistency with the existing codebase by:
- Using Config dataclass for parameters
- Following CLI override pattern via `dataclasses.replace()`
- Preserving the modular structure of each pipeline stage
- Making minimal changes to existing code
- Providing clear user feedback

The fallback logic prioritizes late-swap files (more specific) over regular files (more common), ensuring the right file is analyzed in both standard and late-swap workflows.
