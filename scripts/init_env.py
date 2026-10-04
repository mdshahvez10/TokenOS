"""Generate local development secrets without displaying or overwriting them."""

import secrets
from pathlib import Path

path = Path(__file__).resolve().parents[1] / ".env"
password = secrets.token_hex(24)
key = secrets.token_urlsafe(32)
with path.open("x", encoding="utf-8") as file:
    file.write(
        f"TOKENOS_API_KEY={key}\nPOSTGRES_PASSWORD={password}\n"
        "TOKENOS_BACKEND=postgres\n"
        f"TOKENOS_DATABASE_URL=postgresql://tokenos:{password}@localhost:5432/tokenos\n"
        "TOKENOS_DEMO_ENABLED=true\n"
    )
try:
    path.chmod(0o600)
except OSError:
    pass  # Windows ACLs manage permissions separately.
print("Created .env. Existing files are never overwritten.")
