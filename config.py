import os
from dotenv import load_dotenv

# Load environment variables from .env file if it exists
load_dotenv()

# --- ROSTER SETTINGS ---
SALARY_CAP = 50000
ROSTER_SIZE = 8
MIN_GAMES = 2

# --- DIRECTORY SETTINGS ---
# Default to local directories if environment variables are not set
# Users should set these in a .env file locally
ENTRIES_PATH = os.getenv("NBA_ENTRIES_PATH", "DKEntries.csv")
PROJS_DIR = os.getenv("NBA_PROJS_DIR", "projections")
LINEUP_DIR = os.getenv("NBA_LINEUP_DIR", "lineup-pools")
OUTPUT_DIR = os.getenv("NBA_OUTPUT_DIR", "exports")

# Ensure directories exist
for d in [PROJS_DIR, LINEUP_DIR, OUTPUT_DIR]:
    if not os.path.exists(d):
        try:
            os.makedirs(d, exist_ok=True)
        except Exception:
            # Fallback for paths that might be absolute and unreachable
            pass
