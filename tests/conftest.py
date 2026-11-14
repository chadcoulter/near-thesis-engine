import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
os.environ.setdefault('MPLCONFIGDIR', str(ROOT / '.tmp' / 'matplotlib'))
