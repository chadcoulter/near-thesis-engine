import os
from pathlib import Path
import sys
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
os.environ.setdefault('MPLCONFIGDIR', str(ROOT / '.tmp' / 'matplotlib'))


@pytest.fixture(autouse=True)
def isolate_live_configuration(monkeypatch):
    monkeypatch.setenv('INTENTS_EVIDENCE_MODE', 'inline')
    monkeypatch.setenv('BQ_MAX_BYTES_BILLED', '20000000000')
    monkeypatch.setenv('BQ_MAX_TOTAL_BYTES', '60000000000')
