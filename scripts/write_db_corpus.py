#!/usr/bin/env python3
"""Serialize database rows to the epistract corpus plain-text format.

Reads records from SQLite (stdlib), PostgreSQL/MySQL (SQLAlchemy), or Neo4j
(official driver) and writes one <table>_<pk>.txt file per non-empty row into
<output_dir>/docs/, ready for /epistract:ingest to consume.

Usage:
    python write_db_corpus.py <output_dir> --source sqlite --conn sqlite:///db.sqlite \
        --table patients --pk id [--limit 500]
    python write_db_corpus.py <output_dir> --source sql \
        --conn postgresql+psycopg2://user:pass@host/db \
        --query "SELECT * FROM patients" [--table patients] [--pk id]
    python write_db_corpus.py <output_dir> --source neo4j \
        --conn bolt://localhost:7687 --query "MATCH (n:Patient) RETURN n" \
        --neo4j-user neo4j --neo4j-password-env NEO4J_PASSWORD

Output file format:
    Source: {table_name} (row {pk_val})
    Database: {db_url_redacted}
    Table: {table_name}
    Row_ID: {pk_val}
    Field_{col}: {value}  [one per non-PK column with non-None value]

    CONTENT:
    {long text fields joined by newlines, or "(structured fields above)"}

Security note: --query accepts trusted SQL/Cypher only; do not paste untrusted
user input. Credentials are redacted from all output via _redact_url().
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import sys
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

try:
    from sqlalchemy import create_engine, text
    from sqlalchemy.exc import OperationalError

    HAS_SQLALCHEMY = True
except ImportError:
    HAS_SQLALCHEMY = False

try:
    import neo4j
    from neo4j import GraphDatabase

    HAS_NEO4J = True
except ImportError:
    HAS_NEO4J = False

_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.]*$")
_FILENAME_SAFE_RE = re.compile(r"[^A-Za-z0-9._-]")
_MAX_FIELD_LEN = 2000
_DEFAULT_LIMIT = 500
_USAGE = (
    "Usage: write_db_corpus.py <output_dir> --source <sqlite|sql|neo4j> "
    "--conn <url> [--query Q] [--table T] [--pk COL] [--limit N] "
    "[--neo4j-user U] [--neo4j-password-env VAR]"
)


def _require_sqlalchemy() -> None:
    """Raise ImportError with uv pip install hint when HAS_SQLALCHEMY is False."""
    if not HAS_SQLALCHEMY:
        raise ImportError(
            "sqlalchemy is required for SQL sources. "
            "Install with: uv pip install sqlalchemy psycopg2-binary"
        )


def _require_neo4j() -> None:
    """Raise ImportError with uv pip install hint when HAS_NEO4J is False."""
    if not HAS_NEO4J:
        raise ImportError(
            "neo4j driver is required for Neo4j sources. "
            "Install with: uv pip install neo4j"
        )


def _redact_url(conn_url: str) -> str:
    """Strip user:password from a connection URL via urllib.parse (not regex).

    Returns the original string unchanged when there is no hostname
    (e.g. sqlite:///./local.db).
    """
    parts = urlsplit(conn_url)
    if parts.hostname is None:
        return conn_url
    netloc = parts.hostname
    if parts.port is not None:
        netloc = f"{parts.hostname}:{parts.port}"
    return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))


def _validate_identifier(name: str) -> str:
    """Validate a SQL identifier (table/column). Raises ValueError if unsafe (T-6-02)."""
    if _IDENTIFIER_RE.match(name) is None:
        raise ValueError(f"unsafe SQL identifier: {name!r}")
    return name


def _validate_output_dir(output_dir: str) -> Path:
    """Resolve output_dir; refuse existing non-directories (T-6-03)."""
    path = Path(output_dir).resolve()
    if path.exists() and not path.is_dir():
        raise ValueError(f"output_dir exists but is not a directory: {path}")
    path.mkdir(parents=True, exist_ok=True)
    return path


def _sanitize_filename_part(s: str) -> str:
    """Replace characters outside [A-Za-z0-9._-] with underscores."""
    return _FILENAME_SAFE_RE.sub("_", s)


def serialize_row(
    row: dict,
    table_name: str,
    pk_col: str,
    db_url_redacted: str,
    docs_dir: Path,
) -> str | None:
    """Serialize one DB row to a plain-text corpus file in docs_dir.

    Returns the basename written (e.g. 'patients_42.txt'), or None when the
    row has no usable content (PK missing, or all non-PK fields None/empty).
    File format: Source/Database/Table/Row_ID header, Field_ lines, blank line,
    CONTENT: section. Filename: sanitize(table)_sanitize(pk).txt (DB-04).
    """
    pk_val = row.get(pk_col)
    if pk_val is None or str(pk_val).strip() == "":
        return None
    pk_str = str(pk_val).strip()

    content_fields = {
        k: v for k, v in row.items() if k != pk_col and v is not None and str(v) != ""
    }
    if not content_fields:
        return None

    lines: list[str] = [
        f"Source: {table_name} (row {pk_str})",
        f"Database: {db_url_redacted}",
        f"Table: {table_name}",
        f"Row_ID: {pk_str}",
    ]
    for col, val in content_fields.items():
        lines.append(f"Field_{col}: {str(val)[:_MAX_FIELD_LEN]}")
    lines.append("")
    lines.append("CONTENT:")
    long_parts = [
        str(v) for v in content_fields.values() if isinstance(v, str) and len(v) > 20
    ]
    lines.append("\n".join(long_parts) if long_parts else "(structured fields above)")

    raw_name = (
        f"{_sanitize_filename_part(table_name)}_{_sanitize_filename_part(pk_str)}.txt"
    )
    (docs_dir / raw_name).write_text("\n".join(lines), encoding="utf-8")
    return raw_name


def fetch_sqlite_rows(
    db_path: str,
    table: str,
    pk_col: str,
    limit: int,
) -> tuple[list[str], list[dict]]:
    """Fetch rows from a SQLite file via stdlib sqlite3 only (never sqlalchemy).

    SECURITY: table and pk_col validated by _validate_identifier() before
    string interpolation; limit bound as ? parameter (T-6-02).
    Returns (column_names, rows_as_dicts).
    """
    _validate_identifier(table)
    _validate_identifier(pk_col)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.execute(f"SELECT * FROM {table} ORDER BY {pk_col} LIMIT ?", (limit,))  # noqa: S608
        columns = [d[0] for d in cur.description]
        rows = [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()
    return columns, rows


def fetch_sql_rows(
    conn_url: str,
    query: str,
    limit: int,
) -> tuple[list[str], list[dict]]:
    """Run a SELECT via SQLAlchemy 2.0. Calls _require_sqlalchemy() first.

    Appends LIMIT :_db_corpus_limit via parameter binding. Re-raises
    OperationalError as ConnectionError. Returns (column_names, rows_as_dicts).
    """
    _require_sqlalchemy()
    engine = create_engine(conn_url)
    try:
        with engine.connect() as conn:
            result = conn.execute(
                text(query + " LIMIT :_db_corpus_limit"),
                {"_db_corpus_limit": int(limit)},
            )
            columns = list(result.keys())
            rows = [dict(zip(columns, row)) for row in result]
    except OperationalError as e:
        raise ConnectionError(f"Database connection failed: {e}") from e
    finally:
        engine.dispose()
    return columns, rows


def fetch_neo4j_nodes(
    uri: str,
    user: str,
    password: str,
    cypher: str,
    limit: int,
) -> list[dict]:
    """Fetch nodes from Neo4j via official driver. Calls _require_neo4j() first.

    Uses driver.execute_query() for neo4j >= 5.8; falls back to session.run()
    for older versions. Each dict contains node properties + _labels key.
    """
    _require_neo4j()
    driver = GraphDatabase.driver(uri, auth=(user, password))
    try:
        driver.verify_connectivity()
        v = tuple(int(x) for x in neo4j.__version__.split(".")[:2])
        if v >= (5, 8):
            records, _summary, _keys = driver.execute_query(
                cypher + " LIMIT $_db_corpus_limit",
                _db_corpus_limit=int(limit),
                database_="neo4j",
            )
        else:
            with driver.session() as session:
                records = list(
                    session.run(
                        cypher + " LIMIT $_db_corpus_limit", _db_corpus_limit=int(limit)
                    )
                )
        rows: list[dict] = []
        for record in records:
            for key in record.keys():
                val = record[key]
                if hasattr(val, "items") and hasattr(val, "labels"):
                    row = dict(val.items())
                    row["_labels"] = list(val.labels)
                    rows.append(row)
                else:
                    rows.append({key: val})
        return rows
    finally:
        driver.close()


def _get_flag(args: list[str], name: str, default: str | None = None) -> str | None:
    """Return the value following --name in args, or default."""
    if name in args:
        idx = args.index(name)
        if idx + 1 < len(args):
            return args[idx + 1]
    return default


def main() -> None:
    """CLI entry point. Parses sys.argv, fetches rows, serializes, prints JSON summary."""
    args = sys.argv[1:]
    if not args or "--help" in args or "-h" in args:
        print(_USAGE)
        sys.exit(0)

    try:
        output_dir = args[0]
        source = _get_flag(args, "--source")
        if source not in ("sqlite", "sql", "neo4j"):
            print(
                f"ERROR: --source must be sqlite, sql, or neo4j (got: {source!r})",
                file=sys.stderr,
            )
            sys.exit(2)

        conn = _get_flag(args, "--conn")
        if not conn:
            print("ERROR: --conn is required", file=sys.stderr)
            sys.exit(2)

        redacted_url = _redact_url(conn)
        limit = int(_get_flag(args, "--limit", str(_DEFAULT_LIMIT)) or _DEFAULT_LIMIT)
        out_path = _validate_output_dir(output_dir)
        docs_dir = out_path / "docs"
        docs_dir.mkdir(parents=True, exist_ok=True)

        rows: list[dict] = []
        table_name = _get_flag(args, "--table", "rows") or "rows"
        pk_col = _get_flag(args, "--pk", "id") or "id"

        if source == "sqlite":
            if not _get_flag(args, "--table"):
                print("ERROR: --table is required for --source sqlite", file=sys.stderr)
                sys.exit(2)
            if not _get_flag(args, "--pk"):
                print("ERROR: --pk is required for --source sqlite", file=sys.stderr)
                sys.exit(2)
            table_name = _get_flag(args, "--table") or table_name
            pk_col = _get_flag(args, "--pk") or pk_col
            db_path = (
                conn[len("sqlite:///") :] if conn.startswith("sqlite:///") else conn
            )
            _columns, rows = fetch_sqlite_rows(db_path, table_name, pk_col, limit)

        elif source == "sql":
            query = _get_flag(args, "--query")
            if not query:
                print("ERROR: --query is required for --source sql", file=sys.stderr)
                sys.exit(2)
            table_name = _get_flag(args, "--table", "rows") or "rows"
            pk_col = _get_flag(args, "--pk", "id") or "id"
            _columns, rows = fetch_sql_rows(conn, query, limit)

        else:  # neo4j
            query = _get_flag(args, "--query")
            if not query:
                print("ERROR: --query is required for --source neo4j", file=sys.stderr)
                sys.exit(2)
            user = _get_flag(args, "--neo4j-user", "neo4j") or "neo4j"
            pw_env = _get_flag(args, "--neo4j-password-env")
            password = (
                os.environ.get(pw_env, "")
                if pw_env
                else os.environ.get("NEO4J_PASSWORD", "")
            )
            rows = fetch_neo4j_nodes(
                uri=conn, user=user, password=password, cypher=query, limit=limit
            )

        written: list[str] = []
        skipped = 0
        for row in rows:
            eff_table, eff_pk = table_name, pk_col
            if source == "neo4j":
                labels = row.get("_labels", [])
                if labels:
                    eff_table = labels[0]
                for c in ("id", "uuid", "name"):
                    if c in row:
                        eff_pk = c
                        break
            fname = serialize_row(
                row=row,
                table_name=eff_table,
                pk_col=eff_pk,
                db_url_redacted=redacted_url,
                docs_dir=docs_dir,
            )
            if fname:
                written.append(fname)
            else:
                skipped += 1

        if limit == _DEFAULT_LIMIT and len(rows) == limit:
            print(
                f"WARNING: fetched exactly {limit} rows -- result set may be truncated. Use --limit to increase.",
                file=sys.stderr,
            )

        print(
            json.dumps(
                {
                    "docs_dir": str(docs_dir),
                    "source": source,
                    "redacted_url": redacted_url,
                    "rows_fetched": len(rows),
                    "written": len(written),
                    "skipped_empty": skipped,
                    "files": written,
                },
                indent=2,
            )
        )

    except (ImportError, ValueError, ConnectionError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
