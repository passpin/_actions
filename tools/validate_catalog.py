"""Development-only validation of editable JSON and its normalized artifact."""
from pathlib import Path
import runpy
import sys

if __name__ == "__main__":
    sys.argv = [str(Path(__file__).parent / "reverse/build_catalog.py"), "--check", *sys.argv[1:]]
    runpy.run_path(sys.argv[0], run_name="__main__")
