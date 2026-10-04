CREATE EXTENSION IF NOT EXISTS vector;
CREATE TABLE IF NOT EXISTS tokenos_records (
 namespace TEXT NOT NULL, key TEXT NOT NULL, body JSONB NOT NULL,
 updated_at TIMESTAMPTZ NOT NULL DEFAULT now(), PRIMARY KEY(namespace,key)
);
CREATE INDEX IF NOT EXISTS tokenos_records_recent ON tokenos_records(namespace,updated_at DESC);
CREATE TABLE IF NOT EXISTS tokenos_documents (
 document_id TEXT PRIMARY KEY, revision TEXT NOT NULL, body JSONB NOT NULL
);
CREATE TABLE IF NOT EXISTS tokenos_chunks (
 chunk_id TEXT PRIMARY KEY, document_id TEXT NOT NULL REFERENCES tokenos_documents(document_id) ON DELETE CASCADE,
 body JSONB NOT NULL, embedding vector(256) NOT NULL
);
CREATE INDEX IF NOT EXISTS tokenos_chunk_document ON tokenos_chunks(document_id);
