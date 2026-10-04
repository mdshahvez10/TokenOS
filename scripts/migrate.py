"""Checksummed migrations, serialized with a PostgreSQL transaction advisory lock."""

import asyncio
import hashlib
import os
from pathlib import Path

import asyncpg
from dotenv import load_dotenv


async def main():
    load_dotenv()
    connection = await asyncpg.connect(os.environ["TOKENOS_DATABASE_URL"])
    try:
        async with connection.transaction():
            await connection.execute("SELECT pg_advisory_xact_lock(737071001)")
            await connection.execute(
                "CREATE TABLE IF NOT EXISTS tokenos_schema_migrations "
                "(name text PRIMARY KEY, checksum text NOT NULL)"
            )
            for path in sorted((Path(__file__).resolve().parents[1] / "migrations").glob("*.sql")):
                checksum = hashlib.sha256(path.read_bytes()).hexdigest()
                previous = await connection.fetchval(
                    "SELECT checksum FROM tokenos_schema_migrations WHERE name=$1", path.name
                )
                if previous is not None:
                    if previous != checksum:
                        raise RuntimeError("Previously applied migration changed: " + path.name)
                    continue
                await connection.execute(path.read_text())
                await connection.execute(
                    "INSERT INTO tokenos_schema_migrations VALUES ($1,$2)", path.name, checksum
                )
    finally:
        await connection.close()
    print("Migrations applied.")


if __name__ == "__main__":
    asyncio.run(main())
