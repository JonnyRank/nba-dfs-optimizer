import os
import sys
import pytest
import pandas as pd
from datetime import datetime
from unittest.mock import patch, MagicMock

# Add root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import late_swapper
import config

TEST_DATA_DIR = os.path.join(os.path.dirname(__file__), "test_data")

def test_get_latest_projections():
    with patch("config.PROJS_DIR", TEST_DATA_DIR):
        latest = late_swapper.get_latest_projections()
        assert "NBA-Projs-2026-02-20.csv" in latest

def test_load_data():
    projs_file = os.path.join(TEST_DATA_DIR, "NBA-Projs-2026-02-20.csv")
    entries_file = os.path.join(TEST_DATA_DIR, "DKEntries.csv")
    
    df = late_swapper.load_data(projs_file, entries_file)
    
    assert not df.empty
    assert "ID" in df.columns
    assert "Projection" in df.columns
    # Check some player
    assert any(df["Name"] == "Giannis Antetokounmpo")

def test_solve_late_swap():
    # Setup pool
    projs_file = os.path.join(TEST_DATA_DIR, "NBA-Projs-2026-02-20.csv")
    entries_file = os.path.join(TEST_DATA_DIR, "DKEntries.csv")
    df_pool = late_swapper.load_data(projs_file, entries_file)
    
    # Lineup with some locked players
    current_lineup = [
        "Kam Jones (42063199) (LOCKED)",
        "Anthony Edwards (42062863)", # NOT LOCKED
        "Gregory Jackson (42063100) (LOCKED)",
        "Taylor Hendricks (42063299) (LOCKED)",
        "Tristan Vukcevic (42063159) (LOCKED)",
        "Javon Small (42063406) (LOCKED)",
        "Jalen Johnson (42062857)", # NOT LOCKED
        "Zion Williamson (42062920)" # NOT LOCKED
    ]
    
    new_lineup = late_swapper.solve_late_swap(df_pool, current_lineup, min_salary=40000)
    
    assert len(new_lineup) == 8
    # Kam Jones must still be there (locked)
    assert any("Kam Jones" in p for p in new_lineup)
    assert any("42063199" in p for p in new_lineup)

    # Check that locked players are preserved
    locked_expected = [
        "42063199", "42063100", "42063299", "42063159", "42063406"
    ]
    for pid in locked_expected:
        assert any(pid in p for p in new_lineup), f"Player {pid} was locked but not found in new lineup"

def test_solve_late_swap_no_valid_solution():
    projs_file = os.path.join(TEST_DATA_DIR, "NBA-Projs-2026-02-20.csv")
    entries_file = os.path.join(TEST_DATA_DIR, "DKEntries.csv")
    df_pool = late_swapper.load_data(projs_file, entries_file)
    
    # Extremely high salary requirement to force failure
    current_lineup = ["Player (123) (LOCKED)"] * 8
    new_lineup = late_swapper.solve_late_swap(df_pool, current_lineup, min_salary=100000)
    
    # Should return original if failed
    assert new_lineup == current_lineup

def test_is_player_locked():
    # Mock player series with Name + ID
    p_locked = pd.Series({"Name + ID": "Kam Jones (42063199) (LOCKED)"})
    p_unlocked = pd.Series({"Name + ID": "Shai Gilgeous-Alexander (42062854)"})
    
    assert late_swapper.is_player_locked(p_locked) is True
    assert late_swapper.is_player_locked(p_unlocked) is False

def test_solve_late_swap_with_pool_locking():
    # Setup pool
    projs_file = os.path.join(TEST_DATA_DIR, "NBA-Projs-2026-02-20.csv")
    entries_file = os.path.join(TEST_DATA_DIR, "DKEntries.csv")
    df_pool = late_swapper.load_data(projs_file, entries_file)
    
    # In the updated mock data (DKEntries.csv), Giannis is locked in the pool
    # SGA is NOT locked in the pool (BKN@OKC 10:00PM ET)
    
    current_lineup = [
        "Giannis Antetokounmpo (42062851)", # Should be locked via pool data
        "Shai Gilgeous-Alexander (42062854)", # Should NOT be locked
        "Gregory Jackson (42063100)", 
        "Taylor Hendricks (42063299)",
        "Tristan Vukcevic (42063159)",
        "Javon Small (42063406)",
        "Jalen Johnson (42062857)",
        "Zion Williamson (42062920)"
    ]
    
    new_lineup = late_swapper.solve_late_swap(df_pool, current_lineup, min_salary=40000)
    
    # Giannis must still be there
    assert any("42062851" in p for p in new_lineup), "Giannis was locked in pool but not found"
    
    # SGA could potentially be swapped if there's a better option
    df_pool_low_sga = df_pool.copy()
    df_pool_low_sga.loc[df_pool_low_sga["ID"] == "42062854", "Projection"] = 0.0
    
    new_lineup_swapped = late_swapper.solve_late_swap(df_pool_low_sga, current_lineup, min_salary=40000)
    
def test_solve_late_swap_missing_projection_for_locked_player():
    # Setup pool
    projs_file = os.path.join(TEST_DATA_DIR, "NBA-Projs-2026-02-20.csv")
    entries_file = os.path.join(TEST_DATA_DIR, "DKEntries.csv")
    df_pool = late_swapper.load_data(projs_file, entries_file)
    
    # In this test, we have a player who is in the entry but NOT in the pool (e.g., projection missing)
    # Let's mock a lineup where one player is locked but missing from df_pool
    # ID 99999999 is NOT in our mock pool
    current_lineup = [
        "Missing Player (99999999) (LOCKED)",
        "Anthony Edwards (42062863)", 
        "Gregory Jackson (42063100)",
        "Taylor Hendricks (42063299)",
        "Tristan Vukcevic (42063159)",
        "Javon Small (42063406)",
        "Jalen Johnson (42062857)",
        "Zion Williamson (42062920)"
    ]
    
    new_lineup = late_swapper.solve_late_swap(df_pool, current_lineup, min_salary=40000)
    
    # It should still preserve the missing locked player in their slot
    # and not crash.
def test_flexible_slotting_prioritization():
    # Setup pool
    projs_file = os.path.join(TEST_DATA_DIR, "NBA-Projs-2026-02-20.csv")
    entries_file = os.path.join(TEST_DATA_DIR, "DKEntries.csv")
    df_pool = late_swapper.load_data(projs_file, entries_file)
    
    # We want to see if a late player is put in UTIL instead of a specific slot
    # In the mock data:
    # Giannis is 08:00PM (ID: 42062851)
    # SGA is 10:00PM (ID: 42062854)
    # Both are high projection. Let's force a lineup where one MUST be UTIL.
    
    current_lineup = ["Player (1)"] * 8 # Dummy lineup, everything is unlocked
    
    # We'll use a custom pool where we only have enough players to fill a lineup
    # and we want to see where SGA (late) and Giannis (early) end up.
    # Note: Giannis is PF/F/UTIL, SGA is PG/G/UTIL.
    
    # Let's mock a scenario where SGA and another PG are available.
    # If SGA is late, he should be in UTIL if possible.
    
    # Force SGA into the lineup with a high projection
    df_pool.loc[df_pool["ID"] == "42062854", "Projection"] = 100.0
    # Also ensure we have enough low-salary players to fit SGA and Giannis
    df_pool.loc[df_pool["Salary"] > 5000, "Salary"] = 3000
    # But keep SGA and Giannis somewhat expensive to test the cap logic if needed
    df_pool.loc[df_pool["ID"] == "42062854", "Salary"] = 10000
    df_pool.loc[df_pool["ID"] == "42062851", "Salary"] = 10000

    new_lineup = late_swapper.solve_late_swap(df_pool, current_lineup, min_salary=30000)
    
    # SGA (42062854) is 10:00PM. Giannis (42062851) is 08:00PM.
    # If the logic works, SGA should be in a more flexible slot if there's a choice.
    slots = ["PG", "SG", "SF", "PF", "C", "G", "F", "UTIL"]
    sga_slot = -1
    for i, p in enumerate(new_lineup):
        if "42062854" in p:
            sga_slot = i
            break
            
    assert sga_slot != -1, f"SGA not found in optimized lineup: {new_lineup}"
    # SGA is a PG/G/UTIL. 
    # Since he's the latest player in the pool, he should ideally be in UTIL (index 7).
    assert sga_slot in [5, 7], f"Latest player SGA was put in slot {slots[sga_slot]}, expected G or UTIL. Lineup: {new_lineup}"
