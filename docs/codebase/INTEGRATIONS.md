# External Integrations

## Core Sections (Required)

### 1) Integration Inventory

| System | Type | Purpose | Auth model | Criticality | Evidence |
|--------|------|---------|------------|-------------|----------|
| DraftKings (file-based) | CSV file exchange | Source of player pool (DKEntries.csv), target for upload-ready exports | None (manual download/upload) | High | `config.py:ENTRIES_PATH`, `exporter.py` |
| Projection CSVs | Local file | Player projections and ownership data | None (user-generated) | High | `config.py:PROJS_DIR`, `engine.py:get_latest_projections()` |
| Google Drive (via file path) | Local file system mount | Storage for lineup pools, ranked lineups, projections | OS-level file access | Medium | `.env.example:NBA_LINEUP_DIR`, `config.py` |

### 2) Data Stores

| Store | Role | Access layer | Key risk | Evidence |
|-------|------|--------------|----------|----------|
| Local filesystem (CSV) | All inter-stage data persistence | `pandas.read_csv()` / `DataFrame.to_csv()` | No transactional integrity; stale files from failed runs may be picked up | All modules |
| Google Drive (mounted) | Projection source and lineup export storage | OS file path | Availability depends on Drive sync status | `.env.example`, `design_docs/project_plan.md` |

No databases are used. The project plan mentions SQLite for historical data as a future phase, but it is not implemented.

### 3) Secrets and Credentials Handling

- Credential sources: `.env` file loaded via `python-dotenv`. Contains only file paths, no actual secrets.
- Hardcoding checks: No hardcoded secrets found. Default paths in `config.py` are generic fallbacks.
- Rotation or lifecycle notes: N/A — no credentials to rotate.

### 4) Reliability and Failure Behavior

- Retry/backoff behavior: None. If a solve fails, the worker returns `None` and the candidate is discarded.
- Timeout policy: No timeouts configured on LP solves or file operations.
- Circuit-breaker or fallback behavior: None. If the projection file or entries file is missing, a `FileNotFoundError` is raised and the pipeline aborts.

### 5) Observability for Integrations

- Logging around external calls: File paths are printed when loaded (`"Using projections: {filename}"`).
- Metrics/tracing coverage: None.
- Missing visibility gaps: No logging when files are written, no validation that output files were written correctly, no alerting on stale input files.

### 6) Evidence

- `.env.example`
- `src/nba_optimizer/config.py`
- `src/nba_optimizer/engine.py` (data loading)
- `src/nba_optimizer/exporter.py` (DK template parsing)
