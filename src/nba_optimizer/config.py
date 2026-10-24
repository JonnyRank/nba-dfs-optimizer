import os
from dataclasses import dataclass, field
from typing import Dict, Optional

from dotenv import load_dotenv


# --- DRAFTKINGS ROSTER CONSTANTS ---
ROSTER_SLOTS = ("PG", "SG", "SF", "PF", "C", "G", "F", "UTIL")
ENTRY_HEADER_COLS = ("Entry ID", "Contest Name", "Contest ID", "Entry Fee")
SLATE_TYPES = ("main", "early", "turbo", "afternoon", "night", "late")


# --- EXPORT PREFIXES ---
STANDARD_EXPORT_PREFIX = "upload-ready-DKEntries"
LATE_SWAP_PREFIX = "late-swap-entries"


@dataclass
class Config:
    """Configuration for NBA DFS Optimizer.

    Encapsulates all configuration settings including roster rules,
    file paths, and runtime parameters. This class supports dependency
    injection to enable isolated testing and concurrent instances.
    """

    # --- ROSTER SETTINGS ---
    salary_cap: int = 50000
    min_salary: int = 49500
    roster_size: int = 8
    min_games: int = 2
    min_projection: float = 10.0

    # --- RANKING WEIGHTS (the one source of defaults; O-13 §3.4) ---
    proj_weight: float = 0.8
    own_weight: float = 0.0
    geo_weight: float = 0.2

    # --- ASSEMBLY (O-14) --- one source of the default
    min_unique: int = 1

    # --- DIRECTORY SETTINGS ---
    entries_path: str = "DKEntries.csv"
    projs_dir: str = "projections"
    # Non-main slate types' projections folders from NBA_PROJS_DIR_<TYPE>
    # (O-15); a type without one uses the sibling folder <projs_dir>-<type>.
    projs_dir_overrides: Dict[str, str] = field(default_factory=dict)
    base_dir: str = "exports"
    lineup_pool_dir: str = field(default="")
    ranked_lineup_dir: str = field(default="")
    output_dir: str = "exports"

    # --- NIGHTLY CAPTURE (O-0) ---
    # data_root "" keeps the legacy exports/ layout; when set, each slate
    # gets a folder <data_root>/<slate_id>/ holding pools, ranked files and records.
    data_root: str = ""
    downloads_dir: str = ""
    slate_type: str = "main"
    seed: Optional[int] = None

    def __post_init__(self):
        """Derive computed paths after initialization."""
        # Only override if not explicitly set
        if not self.lineup_pool_dir:
            self.lineup_pool_dir = os.path.join(self.base_dir, "lineup-pools")
        if not self.ranked_lineup_dir:
            self.ranked_lineup_dir = os.path.join(self.base_dir, "ranked-lineups")
        if not self.downloads_dir:
            self.downloads_dir = default_downloads_dir()

    def ensure_directories(self):
        """Create required directories if they don't exist.

        This is separated from __post_init__ to avoid side effects during
        instantiation, allowing for testing without filesystem operations.

        Raises:
            OSError: If one or more directories could not be created.
        """
        failed = []
        for d in [
            self.projs_dir,
            self.lineup_pool_dir,
            self.ranked_lineup_dir,
            self.output_dir,
        ]:
            if not os.path.exists(d):
                try:
                    os.makedirs(d, exist_ok=True)
                except OSError as e:
                    print(f"Warning: Failed to create directory '{d}': {e}")
                    failed.append(d)
        if failed:
            raise OSError(f"Could not create required directories: {failed}")


def _env_path(name: str) -> str:
    """Env var as a path with any trailing separator removed ("" when unset)."""
    value = os.getenv(name, "").strip()
    return value.rstrip("\\/") if value else ""


def _load_dotenv() -> None:
    """Load the project's .env: the nearest one from the package up to the project root.

    Searched from the package's location, not the working directory, so a
    pythonw.exe shortcut or Gooey's relaunch reads the same .env as a terminal.
    The walk stops at the first folder holding a pyproject.toml (the repo root
    for an editable install), so an unrelated .env further up is never read;
    without one there, python-dotenv's own search applies.
    """
    directory = os.path.dirname(os.path.abspath(__file__))
    while True:
        candidate = os.path.join(directory, ".env")
        if os.path.isfile(candidate):
            load_dotenv(candidate)
            return
        parent = os.path.dirname(directory)
        if parent == directory or os.path.isfile(os.path.join(directory, "pyproject.toml")):
            load_dotenv()
            return
        directory = parent


def default_downloads_dir() -> str:
    return os.path.join(os.path.expanduser("~"), "Downloads")


def downloads_dir_from_env() -> str:
    """NBA_DOWNLOADS_DIR (read from .env too), else ~/Downloads; for the GUI's file chooser."""
    _load_dotenv()
    return _env_path("NBA_DOWNLOADS_DIR") or default_downloads_dir()


def load_config_from_env() -> Config:
    """Load configuration from environment variables with defaults.

    Returns:
        Config: Configuration instance populated from environment variables.
    """
    # Load environment variables from .env file if it exists
    _load_dotenv()

    config = Config(
        entries_path=os.getenv("NBA_ENTRIES_PATH", "DKEntries.csv"),
        projs_dir=os.getenv("NBA_PROJS_DIR", "projections"),
        base_dir=os.getenv("NBA_LINEUP_DIR", "exports"),
        output_dir=os.getenv("NBA_OUTPUT_DIR", "exports"),
        data_root=_env_path("NBA_DATA_ROOT"),
        downloads_dir=_env_path("NBA_DOWNLOADS_DIR"),
        projs_dir_overrides={
            t: _env_path(f"NBA_PROJS_DIR_{t.upper()}")
            for t in SLATE_TYPES
            if t != "main" and _env_path(f"NBA_PROJS_DIR_{t.upper()}")
        },
    )

    # Ensure directories exist
    config.ensure_directories()

    return config
