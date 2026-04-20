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
    base_dir: str = "exports"
    lineup_pool_dir: str = field(default="")
    ranked_lineup_dir: str = field(default="")
    output_dir: str = "exports"

    def __post_init__(self):
        """Derive computed paths after initialization."""
        # Only override if not explicitly set
        if not self.lineup_pool_dir:
            self.lineup_pool_dir = os.path.join(self.base_dir, "lineup-pools")
        if not self.ranked_lineup_dir:
            self.ranked_lineup_dir = os.path.join(self.base_dir, "ranked-lineups")

    def ensure_directories(self):
        """Create required directories if they don't exist.

        This is separated from __post_init__ to avoid side effects during
        instantiation, allowing for testing without filesystem operations.

        Raises:
            OSError: If one or more directories could not be created.
        """
        failed = []
        for d in [self.projs_dir, self.lineup_pool_dir, self.ranked_lineup_dir, self.output_dir]:
            if not os.path.exists(d):
                try:
                    os.makedirs(d, exist_ok=True)
                except OSError as e:
                    print(f"Warning: Failed to create directory '{d}': {e}")
                    failed.append(d)
        if failed:
            raise OSError(f"Could not create required directories: {failed}")


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
        base_dir=os.getenv("NBA_LINEUP_DIR", "exports"),
        output_dir=os.getenv("NBA_OUTPUT_DIR", "exports"),
    )

    # Ensure directories exist
    config.ensure_directories()

    return config
