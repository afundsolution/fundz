#!/usr/bin/env python3
"""Sync the local FUNDz client brain into Supabase/Postgres live memory."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from fundz_credit_tracker_bridge import load_env_file
from fundz_operational_state import build_operational_state, normalize_name


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SCHEMA = ROOT / "db" / "migrations" / "001_live_memory.sql"
DEFAULT_DASHBOARD_CHUNK_BYTES = 45_000


def database_url() -> str:
    for name in ("FUNDZ_MEMORY_DATABASE_URL", "SUPABASE_DB_URL", "DATABASE_URL", "NEON_DATABASE_URL"):
        value = os.getenv(name, "").strip()
        if value:
            return value
    return ""


def require_database_url() -> str:
    url = database_url()
    if not url:
        raise SystemExit(
            "Missing Postgres URL. Set FUNDZ_MEMORY_DATABASE_URL, SUPABASE_DB_URL, "
            "DATABASE_URL, or NEON_DATABASE_URL in .env.local."
        )
    return url


def require_psql() -> str:
    psql = shutil.which(os.getenv("PSQL_BIN", "psql"))
    if not psql:
        raise SystemExit("Missing psql. Install PostgreSQL client tools or set PSQL_BIN.")
    return psql


def sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def json_literal(value: Any) -> str:
    return sql_literal(json.dumps(value, ensure_ascii=True, sort_keys=True)) + "::jsonb"


def text_array_literal(values: list[Any]) -> str:
    if not values:
        return "ARRAY[]::text[]"
    return "ARRAY[" + ", ".join(sql_literal(str(value)) for value in values) + "]::text[]"


def nullable_int(value: Any) -> str:
    return "NULL" if value in (None, "") else str(int(value))


def state_hash(state: dict[str, Any]) -> str:
    payload = json.dumps(state, ensure_ascii=True, sort_keys=True).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def build_snapshot_sql(state: dict[str, Any]) -> str:
    digest = state_hash(state)
    return "\n".join(
        [
            "insert into fundz_memory_snapshots (source_hash, state, summary)",
            f"values ({sql_literal(digest)}, {json_literal(state)}, {json_literal(state.get('summary', {}))})",
            "on conflict (source_hash) do nothing;",
        ]
    )


def build_dashboard_snapshot_sql(state: dict[str, Any]) -> str:
    """Build a compact sync marker for dashboard SQL-editor chunk uploads."""
    digest = "dashboard-sync-" + state_hash(state)
    marker_state = {
        "summary": state.get("summary", {}),
        "sync_note": "Client rows synced in SQL editor chunks because database password was not available.",
    }
    return "\n".join(
        [
            "insert into fundz_memory_snapshots (source_hash, state, summary)",
            f"values ({sql_literal(digest)}, {json_literal(marker_state)}, {json_literal(state.get('summary', {}))})",
            "on conflict (source_hash) do nothing;",
        ]
    )


def build_client_upsert_sql(client: dict[str, Any]) -> str:
    name = str(client.get("client_name") or "")
    values = {
        "client_key": str(client.get("client_key") or ""),
        "client_name": name,
        "normalized_name": normalize_name(name),
        "email": str(client.get("email") or ""),
        "is_active_client": "true" if client.get("is_active_client") else "false",
        "status": str(client.get("status") or ""),
        "stage_in_process": str(client.get("stage_in_process") or ""),
        "next_import": str(client.get("next_import") or ""),
        "next_import_days": nullable_int(client.get("next_import_days")),
        "assigned_to": str(client.get("assigned_to") or ""),
        "dispute_round": client.get("dispute_round") or {},
        "operational_flags": client.get("operational_flags") or [],
        "recommended_next_action": str(client.get("recommended_next_action") or ""),
        "send_history": client.get("send_history") or {},
        "dispute_items": client.get("dispute_items") or {},
        "sources": client.get("sources") or [],
        "profile": client,
    }
    return f"""
insert into fundz_client_memory (
  client_key, client_name, normalized_name, email, is_active_client, status,
  stage_in_process, next_import, next_import_days, assigned_to, dispute_round,
  operational_flags, recommended_next_action, send_history, dispute_items,
  sources, profile, updated_at
) values (
  {sql_literal(values["client_key"])},
  {sql_literal(values["client_name"])},
  {sql_literal(values["normalized_name"])},
  {sql_literal(values["email"])},
  {values["is_active_client"]},
  {sql_literal(values["status"])},
  {sql_literal(values["stage_in_process"])},
  {sql_literal(values["next_import"])},
  {values["next_import_days"]},
  {sql_literal(values["assigned_to"])},
  {json_literal(values["dispute_round"])},
  {text_array_literal(values["operational_flags"])},
  {sql_literal(values["recommended_next_action"])},
  {json_literal(values["send_history"])},
  {json_literal(values["dispute_items"])},
  {text_array_literal(values["sources"])},
  {json_literal(values["profile"])},
  now()
)
on conflict (client_key) do update set
  client_name = excluded.client_name,
  normalized_name = excluded.normalized_name,
  email = excluded.email,
  is_active_client = excluded.is_active_client,
  status = excluded.status,
  stage_in_process = excluded.stage_in_process,
  next_import = excluded.next_import,
  next_import_days = excluded.next_import_days,
  assigned_to = excluded.assigned_to,
  dispute_round = excluded.dispute_round,
  operational_flags = excluded.operational_flags,
  recommended_next_action = excluded.recommended_next_action,
  send_history = excluded.send_history,
  dispute_items = excluded.dispute_items,
  sources = excluded.sources,
  profile = excluded.profile,
  updated_at = now();
""".strip()


def build_sync_sql(state: dict[str, Any]) -> str:
    statements = [
        "begin;",
        build_snapshot_sql(state),
    ]
    for client in state.get("clients", []):
        if isinstance(client, dict) and client.get("client_key"):
            statements.append(build_client_upsert_sql(client))
    statements.append("commit;")
    return "\n\n".join(statements) + "\n"


def wrap_transaction(statements: list[str]) -> str:
    return "\n\n".join(["begin;", *statements, "commit;"]) + "\n"


def dashboard_sync_verification_sql(state: dict[str, Any]) -> str:
    dashboard_hash = "dashboard-sync-" + state_hash(state)
    return "\n".join(
        [
            "select",
            "  (select count(*) from fundz_client_memory) as client_count,",
            "  (select count(*) from fundz_client_memory where is_active_client) as active_client_count,",
            "  (select count(*) from fundz_active_client_memory) as active_view_count,",
            (
                "  (select count(*) from fundz_memory_snapshots "
                f"where source_hash = {sql_literal(dashboard_hash)}) as snapshot_marker_count;"
            ),
        ]
    )


def build_dashboard_chunks(state: dict[str, Any], max_bytes: int = DEFAULT_DASHBOARD_CHUNK_BYTES) -> list[tuple[str, str]]:
    if max_bytes < 10_000:
        raise ValueError("max_bytes must be at least 10000 so a client upsert can fit.")

    chunks: list[tuple[str, str]] = [("chunk-000-snapshot.sql", wrap_transaction([build_dashboard_snapshot_sql(state)]))]
    batch: list[str] = []
    batch_number = 1

    for client in state.get("clients", []):
        if not isinstance(client, dict) or not client.get("client_key"):
            continue
        statement = build_client_upsert_sql(client)
        if len(statement.encode("utf-8")) > max_bytes:
            raise ValueError(f"Client row {client.get('client_key')} is larger than max_bytes.")

        candidate = wrap_transaction([*batch, statement])
        if batch and len(candidate.encode("utf-8")) > max_bytes:
            chunks.append((f"chunk-{batch_number:03d}-clients.sql", wrap_transaction(batch)))
            batch_number += 1
            batch = [statement]
        else:
            batch.append(statement)

    if batch:
        chunks.append((f"chunk-{batch_number:03d}-clients.sql", wrap_transaction(batch)))

    chunks.append((f"chunk-{batch_number + 1:03d}-verify.sql", dashboard_sync_verification_sql(state) + "\n"))
    return chunks


def write_dashboard_chunks(state: dict[str, Any], output_dir: Path, max_bytes: int) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    files: list[Path] = []
    for filename, sql in build_dashboard_chunks(state, max_bytes=max_bytes):
        path = output_dir / filename
        path.write_text(sql, encoding="utf-8")
        files.append(path)
    return files


def run_psql(sql: str, db_url: str) -> None:
    psql = require_psql()
    subprocess.run(
        [psql, db_url, "--set", "ON_ERROR_STOP=1", "--quiet"],
        input=sql,
        text=True,
        check=True,
    )


def apply_schema(schema_path: Path, db_url: str) -> None:
    sql = schema_path.read_text(encoding="utf-8")
    run_psql(sql, db_url)


def sync_state(source_dir: Path, recent_limit: int, db_url: str) -> dict[str, Any]:
    state = build_operational_state(source_dir=source_dir, recent_limit=recent_limit)
    run_psql(build_sync_sql(state), db_url)
    return state


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply-schema", action="store_true", help="Apply db/migrations/001_live_memory.sql.")
    parser.add_argument("--sync-operational-state", action="store_true", help="Build local state and sync it to Postgres.")
    parser.add_argument("--source-dir", type=Path, default=ROOT / "data" / "dispute-fox")
    parser.add_argument("--recent-limit", type=int, default=10)
    parser.add_argument("--schema", type=Path, default=DEFAULT_SCHEMA)
    parser.add_argument("--print-sql", action="store_true", help="Print SQL instead of running psql.")
    parser.add_argument(
        "--write-dashboard-chunks",
        type=Path,
        help="Write small SQL files for Supabase dashboard SQL editor fallback instead of using psql.",
    )
    parser.add_argument(
        "--dashboard-chunk-bytes",
        type=int,
        default=DEFAULT_DASHBOARD_CHUNK_BYTES,
        help="Approximate maximum bytes per dashboard SQL chunk.",
    )
    return parser.parse_args()


def main() -> None:
    load_env_file()
    args = parse_args()
    if not args.apply_schema and not args.sync_operational_state:
        raise SystemExit("Choose --apply-schema, --sync-operational-state, or both.")
    if args.apply_schema and args.write_dashboard_chunks:
        raise SystemExit("Use --write-dashboard-chunks with --sync-operational-state only; apply the schema separately.")

    db_url = database_url()
    if not args.print_sql and not args.write_dashboard_chunks:
        db_url = require_database_url()

    if args.apply_schema:
        schema_sql = args.schema.read_text(encoding="utf-8")
        if args.print_sql:
            sys.stdout.write(schema_sql)
        else:
            apply_schema(args.schema, db_url)
            print(f"Applied live memory schema from {args.schema.relative_to(ROOT)}.")

    if args.sync_operational_state:
        state = build_operational_state(source_dir=args.source_dir, recent_limit=max(args.recent_limit, 0))
        sync_sql = build_sync_sql(state)
        if args.write_dashboard_chunks:
            files = write_dashboard_chunks(state, args.write_dashboard_chunks, max(args.dashboard_chunk_bytes, 0))
            summary = state.get("summary", {})
            print(
                "Wrote Supabase dashboard SQL chunks: "
                f"{len(files)} file(s), {summary.get('clients', 0)} client profile(s), "
                f"{summary.get('active_clients', 0)} active."
            )
            print(f"Open chunks from: {args.write_dashboard_chunks}")
        elif args.print_sql:
            sys.stdout.write(sync_sql)
        else:
            run_psql(sync_sql, db_url)
            summary = state.get("summary", {})
            print(
                "Synced live FUNDz memory: "
                f"{summary.get('clients', 0)} client profile(s), "
                f"{summary.get('active_clients', 0)} active."
            )


if __name__ == "__main__":
    main()
