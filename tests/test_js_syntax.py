import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


@pytest.mark.skipif(not shutil.which("node"), reason="không có Node.js")
@pytest.mark.parametrize("rel", ["web/app.js", "web/data.js", "web/config.js", "web/live.js", "frontend/app.js"])
def test_js_files_parse(rel):
    f = ROOT / rel
    if not f.exists():
        pytest.skip(f"{rel} không có")
    r = subprocess.run(["node", "--check", str(f)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr[:500]
