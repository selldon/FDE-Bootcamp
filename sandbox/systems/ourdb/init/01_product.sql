-- Our PostgreSQL holds two databases: "assistant" for the labs (created by POSTGRES_DB) and "product" for the builds.
-- pgvector is switched on in both, for the policy search (1-8-7 in the labs, Build 4 in the product).
CREATE EXTENSION IF NOT EXISTS vector;
CREATE DATABASE product;
\connect product
CREATE EXTENSION IF NOT EXISTS vector;
