"""Start the local sandbox API and dashboard; Ctrl-C stops both."""

import os
import secrets
import subprocess
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
env = dict(os.environ)
env.setdefault("TOKENOS_BACKEND", "memory")
env.setdefault("TOKENOS_RUNTIME_PROVIDER", "sandbox")
env.setdefault("TOKENOS_API_KEY", secrets.token_urlsafe(32))
env.setdefault("TOKENOS_API_URL", "http://127.0.0.1:8000")
processes = []
try:
    for command in [
        [
            "uvicorn",
            "tokenos.interfaces.api:create_app",
            "--factory",
            "--host",
            "127.0.0.1",
            "--port",
            "8000",
        ],
        [
            "streamlit",
            "run",
            "dashboard/app.py",
            "--server.address",
            "127.0.0.1",
            "--server.port",
            "8501",
        ],
    ]:
        processes.append(subprocess.Popen([sys.executable, "-m", *command], cwd=root, env=env))
    processes[0].wait()
except KeyboardInterrupt:
    pass
finally:
    for process in processes:
        process.terminate()
    for process in processes:
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
