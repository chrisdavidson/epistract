---
name: epistract-setup
description: Install and verify epistract dependencies (sift-kg, optional RDKit/Biopython)
---

Run the epistract setup script to check and install dependencies:

```bash
bash ${CLAUDE_PLUGIN_ROOT}/scripts/setup.sh
```

If any dependency is missing, install it:
- sift-kg: `uv pip install sift-kg`
- RDKit (SMILES validation): `uv pip install rdkit`
- Biopython (sequence validation): `uv pip install biopython`
- SQLAlchemy + PostgreSQL (optional, for /epistract:db-corpus --source sql with PostgreSQL): `uv pip install sqlalchemy psycopg2-binary`
- SQLAlchemy + MySQL (optional, for /epistract:db-corpus --source sql with MySQL): `uv pip install sqlalchemy pymysql`
- Neo4j (optional, for /epistract:db-corpus --source neo4j): `uv pip install neo4j`

Report the status of each dependency to the user after running.

## Usage Guard

```
Usage: /epistract:setup

Installs and verifies epistract dependencies:
  - sift-kg (required)          — knowledge graph engine
  - RDKit (optional)            — SMILES validation for drug-discovery domain
  - Biopython (optional)        — sequence validation for drug-discovery domain
  - DB connectors (optional, on demand) — sqlalchemy / psycopg2-binary / pymysql / neo4j for /epistract:db-corpus

Run with no arguments. No flags needed.
```

Run the epistract setup script to check and install dependencies:

```bash
bash ${CLAUDE_PLUGIN_ROOT}/scripts/setup.sh
```

If any dependency is missing, install it:
- sift-kg: `uv pip install sift-kg`
- RDKit (SMILES validation): `uv pip install rdkit`
- Biopython (sequence validation): `uv pip install biopython`
- SQLAlchemy + PostgreSQL (optional, for /epistract:db-corpus --source sql with PostgreSQL): `uv pip install sqlalchemy psycopg2-binary`
- SQLAlchemy + MySQL (optional, for /epistract:db-corpus --source sql with MySQL): `uv pip install sqlalchemy pymysql`
- Neo4j (optional, for /epistract:db-corpus --source neo4j): `uv pip install neo4j`

Report the status of each dependency to the user after running.

