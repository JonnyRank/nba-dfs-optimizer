# Technology Stack

## Core Sections (Required)

### 1) Runtime Summary

| Area | Value | Evidence |
|------|-------|----------|
| Primary language | Python 3.x | `requirements.txt`, all source files |
| Runtime + version | CPython 3.x (project plan states 3.10+) | `design_docs/project_plan.md` |
| Package manager | pip | `requirements.txt` |
| Module/build system | Standard `src/` layout with `__init__.py` packages | `src/nba_optimizer/__init__.py` |

### 2) Production Frameworks and Dependencies

| Dependency | Version | Role in system | Evidence |
|------------|---------|----------------|----------|
| pandas | 3.0.1 | DataFrame manipulation for player data, lineups, CSV I/O | `requirements.txt` |
| numpy | 2.4.2 | Random projection simulation, geometric mean calculations | `requirements.txt` |
| PuLP | 3.3.0 | Linear programming model formulation | `requirements.txt` |
| highspy | 1.12.0 | HiGHS LP solver backend for PuLP | `requirements.txt` |
| python-dotenv | 1.2.2 | Load `.env` file for path configuration | `requirements.txt`, `src/nba_optimizer/config.py` |
| Gooey | 1.0.8.1 | Desktop GUI wrapper around argparse | `requirements.txt`, `scripts/run_optimizer_gui.py` |
| wxPython | 4.2.5 | GUI toolkit required by Gooey | `requirements.txt` |

### 3) Development Toolchain

| Tool | Purpose | Evidence |
|------|---------|----------|
| None configured | No linter, formatter, or test runner configured | Scan output: "No linting or formatting config files found" |

### 4) Key Commands

```bash
# Install
pip install -r requirements.txt

# Run full pipeline (CLI)
python scripts/run_optimizer.py -n 2500 -r 0.25

# Run with GUI
python scripts/run_optimizer_gui.py

# Run late swap
python scripts/run_optimizer.py --late_swap

# No build, test, or lint commands configured
```

### 5) Environment and Config

- Config sources: `.env` (loaded via `python-dotenv`), `src/nba_optimizer/config.py` (constants)
- Required env vars: `NBA_ENTRIES_PATH`, `NBA_PROJS_DIR`, `NBA_LINEUP_DIR`, `NBA_OUTPUT_DIR`
- Deployment/runtime constraints: Local-only execution on Windows. Paths reference `C:\Users\jrank\Downloads` and Google Drive.

### 6) Evidence

- `requirements.txt`
- `.env.example`
- `src/nba_optimizer/config.py`
