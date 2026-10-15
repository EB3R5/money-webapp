"""Produce the 1024px master PNG for money.icns.

The icon source is app/static/img/money.png (512px, gradient + ring + $). This just resamples it
to 1024 with sips so build.sh has one code path across repos.
Usage: python make_icon.py <output.png>
"""
import subprocess
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[3] / "app" / "static" / "img" / "money.png"
OUT = sys.argv[1] if len(sys.argv) > 1 else "icon_1024.png"
subprocess.run(["sips", "-z", "1024", "1024", str(SRC), "--out", OUT],
               check=True, stdout=subprocess.DEVNULL)
print("wrote", OUT)
