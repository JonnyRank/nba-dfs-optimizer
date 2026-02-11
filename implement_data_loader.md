## Task: Integrate Direct Excel Data Loading for NBA Optimizer

**Objective:**
Replace the current manual VBA CSV export process with a direct Python data ingestion function. This function will read the daily projection `.xlsm` file, archive a CSV copy for records, and return a clean DataFrame directly to the optimizer's main execution flow.

**Instructions for the Assistant:**

1. **Analyze the Existing Codebase:** Look at the current optimizer script to understand the existing variable naming conventions, data structures, and standard library imports.
2. **Adapt the Code Below:** The Python code provided below is a *template* containing the core logic. You **must** modify this code to fit the existing project structure.

   * Rename functions and variables to align with the project's style (e.g., if the project uses `snake\_case` or `camelCase`, match it).
   * Ensure the returned DataFrame matches the structure expected by the optimizer (e.g., if the optimizer expects specific column names or index types, apply those transformations here).
   * Update file paths to match the user's actual directory structure found in the project configuration or constants.

3. **Preserve Core Logic:**

   * Locate the file `NBA-Projs-YYYY-MM-DD.xlsm` (defaulting to the current date).

     * Folder path (`PROJS\_DIR`): `G:\\My Drive\\Documents\\NBA-DFS-25-26\\NBA-25-26-Projs`

   * Read the "For-Export" sheet.
   * **Crucial:** Replicate the VBA logic for finding the last valid row. The data should be trimmed from the bottom up, finding the last row where *both* the "Player ID" (Column A) and "Own Projection" (Column C) are non-empty.
   * Save a timestamped CSV to an archive folder (`G:\\My Drive\\Documents\\CSV-Exports`).
   * Return the clean DataFrame.

**Reference Code (Template):**

```python
import pandas as pd
import datetime
import os

def load\_and\_archive\_projections(target\_date=None, base\_folder=r"G:\\My Drive\\Documents"):
    """
    Locates the NBA projections file, 'trims' it according to the VBA logic, 
    saves a CSV archive, and returns the DataFrame for the optimizer.
    """
    
    # 1. Determine File Path (Default to today if no date provided)
    if target\_date is None:
        target\_date = datetime.date.today()
    
    # NOTE: Check if existing project uses a config object for paths
    date\_str = target\_date.strftime("%Y-%m-%d")
    file\_name = f"NBA-Projs-{date\_str}.xlsm"
    file\_path = os.path.join(base\_folder, file\_name)
    
    print(f"Attempting to load: {file\_path}")
    
    if not os.path.exists(file\_path):
        # Handle this error according to project standards (logging vs raising)
        raise FileNotFoundError(f"Could not find file: {file\_path}")

    # 2. Load Data
    try:
        # Engine 'openpyxl' is required for .xlsm files
        df = pd.read\_excel(file\_path, sheet\_name="For-Export", engine="openpyxl")
    except Exception as e:
        raise ValueError(f"Error reading Excel file: {e}")

    # 3. Replicate VBA 'Last Row' Logic
    # We need to find the last row where specific columns have data.
    # Adjust column indices \[0] and \[2] if the project structure differs.
    
    col\_a\_valid = df.iloc\[:, 0].astype(str).str.strip().replace('nan', '') != ''
    col\_c\_valid = df.iloc\[:, 2].astype(str).str.strip().replace('nan', '') != ''
    
    valid\_rows\_mask = col\_a\_valid \& col\_c\_valid
    
    if valid\_rows\_mask.any():
        # Find the index of the \*last\* valid row and slice up to it
        last\_valid\_index = valid\_rows\_mask\[valid\_rows\_mask].index\[-1]
        df\_clean = df.loc\[:last\_valid\_index].copy()
    else:
        df\_clean = df.head(0)

    # 4. Save to CSV (Archival)
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d\_%H%M%S")
    csv\_filename = f"NBA-Projs-{timestamp}.csv"
    csv\_path = os.path.join(base\_folder, "CSV-Exports", csv\_filename)
    
    os.makedirs(os.path.dirname(csv\_path), exist\_ok=True)
    df\_clean.to\_csv(csv\_path, index=False)
    print(f"Archive saved to: {csv\_path}")
    
    # 5. Return for Optimizer
    return df\_clean

