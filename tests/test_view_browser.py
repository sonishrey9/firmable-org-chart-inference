"""Optional browser check of the chart's initial view. Skipped unless ORGCHART_BROWSER_TESTS=1
and playwright is installed (it is not in requirements-dev.txt, to keep CI light)."""
import os
import socket
import subprocess
import sys
import time
import urllib.request

import pytest

pytestmark = pytest.mark.skipif(os.environ.get("ORGCHART_BROWSER_TESTS") != "1", reason="set ORGCHART_BROWSER_TESTS=1")


def test_initial_view_keeps_leaders_readable_and_on_screen():
    pytest.importorskip("playwright")
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
    srv = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(port)])
    try:
        for _ in range(50):
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{port}/health"); break
            except OSError:
                time.sleep(0.2)
        cmd = [sys.executable, "scripts/check_view.py", "--url", f"http://127.0.0.1:{port}"]
        if os.environ.get("CHROME"):
            cmd += ["--chrome", os.environ["CHROME"]]
        assert subprocess.run(cmd).returncode == 0
    finally:
        srv.terminate()
