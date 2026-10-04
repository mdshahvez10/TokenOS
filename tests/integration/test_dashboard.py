from pathlib import Path
from unittest.mock import patch

import httpx
from streamlit.testing.v1 import AppTest


def test_dashboard_renders():
    def request(self, method, url, **kwargs):
        data = {"source": "simulated", "model": "fixture", "policy": {}}
        return httpx.Response(200, json=data, request=httpx.Request(method, url))

    with patch.object(httpx.Client, "request", request):
        app = AppTest.from_file(str(Path("dashboard/app.py").resolve())).run(timeout=20)
    assert not app.exception
    assert len(app.tabs) == 4
    assert app.warning
