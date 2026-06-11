# Plan 002: Separate GUI dependencies from the core installation path

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving to the next step. If anything in the "STOP conditions" section occurs, stop and report — do not improvise. When done, update the status row for this plan in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat d6cbd5f..HEAD -- pyproject.toml requirements.txt README.md .github/copilot-instructions.md docs/codebase/STACK.md`
> If any in-scope file changed since this plan was written, compare the "Current state" excerpts against the live code before proceeding; on a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: S-M
- **Risk**: LOW
- **Depends on**: none
- **Category**: migration
- **Planned at**: commit `d6cbd5f`, 2026-06-11
- **Issue**: https://github.com/JonnyRank/nba-dfs-optimizer/issues/41

## Why this matters

The repo’s documented standard install path is `pip install -e .`, but the package metadata still lists `Gooey` and `wxPython` as required runtime dependencies. The project’s own onboarding instructions already admit those GUI packages fail in headless environments and are not required for the core optimizer. That means the default installation path is unnecessarily brittle for the exact environments used by agents, CI-like checks, and any user who only wants the CLI pipeline.

## Current state

Relevant files and their current roles:

- `pyproject.toml` — source of truth for package dependencies.
- `requirements.txt` — compatibility mirror for tools that still expect requirements format.
- `README.md` — user-facing installation instructions.
- `.github/copilot-instructions.md` — agent-facing environment guidance.
- `docs/codebase/STACK.md` — repo-level stack and command summary.

Current-state excerpts:

- `pyproject.toml:11-18`

  ```toml
  dependencies = [
      "pandas==3.0.1",
      "numpy==2.4.2",
      "PuLP==3.3.0",
      "highspy==1.12.0",
      "python-dotenv==1.2.2",
      "Gooey==1.0.8.1",
      "wxPython==4.2.5",
  ]
  ```

- `README.md:29-34`

  ```md
  Use `pip install -e .` as the standard install path.
  ...
  pip install -e .
  ```

- `.github/copilot-instructions.md:24-35`

  ```md
  pip install -e .
  ...
  Gooey and wxPython GUI dependencies may fail to install in headless/CI environments.
  ...
  use the --no-deps flag to ensure the core package is linked even if optional GUI dependencies fail to build.
  ```

Repo conventions to follow:

- Keep package metadata minimal and explicit.
- Preserve the current console scripts and user-facing CLI behavior.
- Update documentation when install commands or dependency expectations change.

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Core install | `pip install -e .` | exit 0 in a headless/non-GUI environment |
| Import smoke | `python -c "from nba_optimizer import cli, config, engine, ranker, exporter"` | exit 0 |
| Inspect GUI extra metadata | `python -c "import tomllib, pathlib; data = tomllib.loads(pathlib.Path('pyproject.toml').read_text()); print(data['project']['optional-dependencies']['gui'])"` | prints a list containing Gooey and wxPython |
| GUI install path (only where GUI prerequisites exist) | `pip install -e .[gui]` | exit 0 |

## Scope

**In scope**:

- `pyproject.toml`
- `requirements.txt`
- `README.md`
- `.github/copilot-instructions.md`
- `docs/codebase/STACK.md`
- optionally `requirements-gui.txt` (new) if you need a compatibility mirror for GUI extras

**Out of scope**:

- changes to optimizer logic
- changes to GUI behavior or layout
- removing the GUI entry point entirely
- adding unrelated dev-tooling changes

## Git workflow

- Branch: `advisor/002-separate-gui-dependencies`
- Commit using the repo’s conventional style, for example: `build: move GUI packages to optional extras`
- Do NOT push or open a PR unless the operator instructs it.

## Steps

### Step 1: Move GUI libraries out of core runtime dependencies

Edit `pyproject.toml` so `Gooey` and `wxPython` are no longer part of `[project.dependencies]`. Put them under `[project.optional-dependencies].gui` instead. Keep the core dependencies limited to packages required for the CLI pipeline and CSV-based optimizer.

Do not remove the `nba-dfs-optimizer-gui` console script unless packaging behavior proves it is impossible to keep. The likely happy path is that the command remains installed but only works when the `gui` extra is installed.

**Verify**: `python -c "import tomllib, pathlib; data = tomllib.loads(pathlib.Path('pyproject.toml').read_text()); print(data['project']['dependencies']); print(data['project']['optional-dependencies']['gui'])"` → core dependencies exclude `Gooey`/`wxPython`; GUI extra contains them

### Step 2: Reconcile the compatibility requirements files

Because `requirements.txt` is documented as a compatibility mirror of `pyproject.toml`, update it to reflect the new core-only dependency set. If you judge that GUI users still need a plain requirements file path, create `requirements-gui.txt` instead of putting GUI packages back into the core mirror.

Keep the mirror strategy obvious in comments at the top of the file(s).

**Verify**: `python -c "from pathlib import Path; print(Path('requirements.txt').read_text())"` → output no longer lists `Gooey` or `wxPython`

### Step 3: Update installation and onboarding docs

Update `README.md`, `.github/copilot-instructions.md`, and `docs/codebase/STACK.md` so they all agree on two paths:

- core CLI install: `pip install -e .`
- GUI install: `pip install -e .[gui]` (or the equivalent mirror file path, if you chose that route)

Remove instructions that tell users to work around broken default installs with `--no-deps`; after this plan, the default core install should already be the non-GUI path.

**Verify**: `Select-String -Path README.md,.github/copilot-instructions.md,docs/codebase/STACK.md -Pattern "\.\[gui\]|pip install -e \."` → shows the new core and GUI instructions consistently

### Step 4: Prove the core install path is now clean

In a clean environment or disposable virtual environment, run the core install and the import smoke test. If the executor environment cannot safely create a disposable virtual environment, use the existing environment but record that limitation in the reviewer note.

**Verify**: `pip install -e .` and then `python -c "from nba_optimizer import cli, config, engine, ranker, exporter"` → both exit 0

## Test plan

- Verify the package metadata exposes a `gui` extra containing `Gooey` and `wxPython`.
- Verify `pip install -e .` no longer requires GUI dependencies.
- Verify the core package imports succeed after the core install.
- If the executor has a Windows GUI-capable environment, verify `pip install -e .[gui]` succeeds too; if not, state that this check was not possible.

## Done criteria

Machine-checkable. ALL must hold:

- [ ] `pip install -e .` exits 0 without needing `--no-deps`
- [ ] `python -c "from nba_optimizer import cli, config, engine, ranker, exporter"` exits 0
- [ ] `pyproject.toml` exposes `Gooey` and `wxPython` through an optional `gui` dependency group instead of core dependencies
- [ ] `requirements.txt` mirrors core dependencies only
- [ ] `README.md`, `.github/copilot-instructions.md`, and `docs/codebase/STACK.md` all document the same install story
- [ ] No files outside the in-scope list are modified
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report back if:

- moving the GUI packages to extras breaks the console script installation in a way that requires changing runtime module structure
- another checked-in automation path depends on `requirements.txt` containing GUI packages
- the live `pyproject.toml` has already been refactored away from the excerpt above
- proving the core install path would require destructive environment changes the operator did not approve

## Maintenance notes

- Any future dependency additions should be classified deliberately as core, dev, or GUI-only; avoid returning to a single undifferentiated dependency list.
- Reviewers should scrutinize the docs for consistency more than volume. A short, correct install story is better than several fallback paragraphs.
- If a future GUI rewrite replaces Gooey/wxPython, update the optional extra instead of reintroducing GUI packages into the core runtime set.
