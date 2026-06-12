"""Manual smoke test (not part of pytest - hits the live Open-Meteo API):
    python tests/smoke_pages.py
Renders every Streamlit page headlessly and fails on any exception.
"""
import os
import sys
from pathlib import Path

os.environ.setdefault("VMFANTASY_NO_WEATHER", "1")  # skip slow local weather fetches
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

PAGES = ["Home.py", "pages/1_My_Team.py", "pages/2_Projections.py", "pages/3_Transfers.py",
         "pages/5_Data_Status.py", "pages/6_Match_Center.py"]

failed = False
for page in PAGES:
    at = AppTest.from_file(str(ROOT / page), default_timeout=180)
    at.run()
    if at.exception:
        failed = True
        print(f"FAIL {page}")
        for e in at.exception:
            print(f"  {e.message}")
            print("  " + "\n  ".join(e.stack_trace[-3:]))
    else:
        n_err = len(at.error)
        print(f"OK   {page}  (dataframes={len(at.dataframe)}, warnings={len(at.warning)}, errors={n_err})")

sys.exit(1 if failed else 0)

