import os
import urllib.request

request = urllib.request.Request(
    "http://127.0.0.1:8000/health",
    headers={"X-API-Key": os.environ["TOKENOS_API_KEY"]},
)
with urllib.request.urlopen(request, timeout=3) as response:
    if response.status != 200:
        raise SystemExit(1)
