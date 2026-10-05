import hashlib
import json
import math
import re
from typing import cast

import asyncpg

from tokenos.runtime.contracts import Chunk, Document


def words(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.lower()))


def digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def embedding(text: str) -> list[float]:
    """Lexical hashing, not a learned semantic embedding; fixed version matches SQL vector(256)."""
    vector = [0.0] * 256
    for word in words(text):
        index = int.from_bytes(hashlib.blake2b(word.encode(), digest_size=2).digest(), "big") % 256
        vector[index] += 1
    norm = math.sqrt(sum(x * x for x in vector)) or 1
    return [x / norm for x in vector]


class MemoryRecords:
    def __init__(self) -> None:
        self.data: dict[tuple[str, str], dict[str, object]] = {}

    async def get(self, namespace: str, key: str) -> dict[str, object] | None:
        value = self.data.get((namespace, key))
        return None if value is None else json.loads(json.dumps(value))

    async def put(self, namespace: str, key: str, body: dict[str, object]) -> None:
        self.data[(namespace, key)] = json.loads(json.dumps(body))

    async def create(self, namespace: str, key: str, body: dict[str, object]) -> bool:
        if (namespace, key) in self.data:
            return False
        self.data[(namespace, key)] = json.loads(json.dumps(body))
        return True

    async def list(self, namespace: str, limit: int = 100) -> list[dict[str, object]]:
        return [
            json.loads(json.dumps(body))
            for (space, _), body in reversed(self.data.items())
            if space == namespace
        ][:limit]


class PostgresRecords:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self.pool = pool

    async def get(self, namespace: str, key: str) -> dict[str, object] | None:
        value = await self.pool.fetchval(
            "SELECT body FROM tokenos_records WHERE namespace=$1 AND key=$2", namespace, key
        )
        return None if value is None else cast(dict[str, object], json.loads(value))

    async def put(self, namespace: str, key: str, body: dict[str, object]) -> None:
        await self.pool.execute(
            """INSERT INTO tokenos_records(namespace,key,body) VALUES ($1,$2,$3::jsonb)
            ON CONFLICT(namespace,key) DO UPDATE SET body=EXCLUDED.body,updated_at=now()""",
            namespace,
            key,
            json.dumps(body),
        )

    async def create(self, namespace: str, key: str, body: dict[str, object]) -> bool:
        value = await self.pool.fetchval(
            """INSERT INTO tokenos_records(namespace,key,body) VALUES ($1,$2,$3::jsonb)
            ON CONFLICT(namespace,key) DO NOTHING RETURNING key""",
            namespace,
            key,
            json.dumps(body),
        )
        return value is not None

    async def list(self, namespace: str, limit: int = 100) -> list[dict[str, object]]:
        rows = await self.pool.fetch(
            "SELECT body FROM tokenos_records WHERE namespace=$1 ORDER BY updated_at DESC LIMIT $2",
            namespace,
            limit,
        )
        return [json.loads(row["body"]) for row in rows]


class MemoryCorpus:
    def __init__(self) -> None:
        self.docs: dict[str, Document] = {}
        self.chunks: dict[str, list[Chunk]] = {}

    async def upsert(self, document: Document, chunks: list[Chunk]) -> None:
        self.docs[document.document_id], self.chunks[document.document_id] = document, chunks

    async def search(self, query: str, limit: int) -> list[Chunk]:
        query_vector = embedding(query)
        results = [
            chunk.model_copy(
                update={
                    "score": sum(
                        a * b
                        for a, b in zip(
                            query_vector, embedding(chunk.title + " " + chunk.text), strict=True
                        )
                    )
                }
            )
            for chunks in self.chunks.values()
            for chunk in chunks
        ]
        return sorted(results, key=lambda c: (-c.score, c.chunk_id))[:limit]

    async def revision(self) -> str:
        return digest([doc.model_dump() for _, doc in sorted(self.docs.items())])

    async def documents(self, limit: int) -> list[Document]:
        return list(self.docs.values())[:limit]


class PostgresCorpus:
    """Corpus backed by Postgres. Uses in-Python lexical search (no pgvector required)."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self.pool = pool

    async def upsert(self, document: Document, chunks: list[Chunk]) -> None:
        async with self.pool.acquire() as connection, connection.transaction():
            await connection.execute(
                """INSERT INTO tokenos_documents(document_id,body,revision)
                VALUES ($1,$2::jsonb,$3) ON CONFLICT(document_id) DO UPDATE
                SET body=EXCLUDED.body,revision=EXCLUDED.revision""",
                document.document_id,
                document.model_dump_json(),
                digest(document.model_dump()),
            )
            await connection.execute(
                "DELETE FROM tokenos_chunks WHERE document_id=$1", document.document_id
            )
            for chunk in chunks:
                await connection.execute(
                    """INSERT INTO tokenos_chunks(chunk_id,document_id,body)
                    VALUES ($1,$2,$3::jsonb)""",
                    chunk.chunk_id,
                    document.document_id,
                    chunk.model_dump_json(),
                )

    async def search(self, query: str, limit: int) -> list[Chunk]:
        rows = await self.pool.fetch("SELECT body FROM tokenos_chunks")
        query_vector = embedding(query)
        chunks = [Chunk.model_validate_json(row["body"]) for row in rows]
        results = [
            chunk.model_copy(
                update={
                    "score": sum(
                        a * b
                        for a, b in zip(
                            query_vector,
                            embedding(chunk.title + " " + chunk.text),
                            strict=True,
                        )
                    )
                }
            )
            for chunk in chunks
        ]
        return sorted(results, key=lambda c: (-c.score, c.chunk_id))[:limit]

    async def revision(self) -> str:
        rows = await self.pool.fetch("SELECT revision FROM tokenos_documents ORDER BY document_id")
        return digest([row["revision"] for row in rows])

    async def documents(self, limit: int) -> list[Document]:
        rows = await self.pool.fetch(
            "SELECT body FROM tokenos_documents ORDER BY document_id LIMIT $1", limit
        )
        return [Document.model_validate_json(row["body"]) for row in rows]
