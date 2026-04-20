import os
from dataclasses import dataclass, field
from dotenv import load_dotenv


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

    # --- DIRECTORY SETTINGS ---
    entries_path: str = "DKEntries.csv"
    projs_dir: str = "projections"
    lineup_pool_dir: str = field(default="")
    ranked_lineup_dir: str = field(default="")
    output_dir: str = "exports"

    def __post_init__(self):
        """Derive computed paths after initialization."""
        # Determine base directory for lineup exports
        base_dir = os.getenv("NBA_LINEUP_DIR", "exports")

        # Only override if not explicitly set
        if not self.lineup_pool_dir:
            self.lineup_pool_dir = os.path.join(base_dir, "lineup-pools")
        if not self.ranked_lineup_dir:
            self.ranked_lineup_dir = os.path.join(base_dir, "ranked-lineups")

    def ensure_directories(self):
        """Create required directories if they don't exist.

        This is separated from __post_init__ to avoid side effects during
        instantiation, allowing for testing without filesystem operations.
        """
        for d in [self.projs_dir, self.lineup_pool_dir, self.ranked_lineup_dir, self.output_dir]:
            if not os.path.exists(d):
                try:
                    os.makedirs(d, exist_ok=True)
                except Exception:
                    # Fallback for paths that might be absolute and unreachable
                    pass


def load_config_from_env() -> Config:
    """Load configuration from environment variables with defaults.

    Returns:
        Config: Configuration instance populated from environment variables.
    """
    # Load environment variables from .env file if it exists
    load_dotenv()

    config = Config(
        entries_path=os.getenv("NBA_ENTRIES_PATH", "DKEntries.csv"),
        projs_dir=os.getenv("NBA_PROJS_DIR", "projections"),
        output_dir=os.getenv("NBA_OUTPUT_DIR", "exports"),
    )

    # Ensure directories exist
    config.ensure_directories()

    return config


# Backward compatibility: expose module-level constants for legacy code
# These should be removed once all modules are updated
_default_config = load_config_from_env()
SALARY_CAP = _default_config.salary_cap
MIN_SALARY = _default_config.min_salary
ROSTER_SIZE = _default_config.roster_size
MIN_GAMES = _default_config.min_games
MIN_PROJECTION = _default_config.min_projection
ENTRIES_PATH = _default_config.entries_path
PROJS_DIR = _default_config.projs_dir
LINEUP_POOL_DIR = _default_config.lineup_pool_dir
RANKED_LINEUP_DIR = _default_config.ranked_lineup_dir
OUTPUT_DIR = _default_config.output_dir
