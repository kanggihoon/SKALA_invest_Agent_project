import os
from typing import Optional, Dict, Any
from datetime import datetime

try:
    from sqlalchemy import create_engine, text
    from sqlalchemy.engine import Engine
except Exception:  # pragma: no cover - optional at scaffold time
    create_engine = None  # type: ignore
    Engine = object  # type: ignore
    text = None  # type: ignore


def _clean_env(val: Optional[str]) -> Optional[str]:
    if val is None:
        return None
    v = val.strip()
    # Strip surrounding single or double quotes often used in .env
    if (v.startswith("'") and v.endswith("'")) or (v.startswith('"') and v.endswith('"')):
        v = v[1:-1]
    return v


def _get_any(*keys: str) -> Optional[str]:
    for k in keys:
        v = os.getenv(k)
        if v is not None and v != "":
            return _clean_env(v)
    return None


def _dsn_from_env() -> Optional[str]:
    # Prefer full DSN if provided
    dsn = _get_any("POSTGRES_DSN", "DB_DSN")
    if dsn:
        return dsn
    # Accept both POSTGRES_* and DB_* aliases
    host = _get_any("POSTGRES_HOST", "DB_HOST")
    db = _get_any("POSTGRES_DB", "DB_NAME")
    user = _get_any("POSTGRES_USER", "DB_USER")
    pwd = _get_any("POSTGRES_PASSWORD", "DB_PASSWORD")
    port = _get_any("POSTGRES_PORT", "DB_PORT") or "5432"
    if host and db and user and pwd:
        return f"postgresql+psycopg2://{user}:{pwd}@{host}:{port}/{db}"
    return None


def get_engine() -> Optional["Engine"]:
    if create_engine is None:
        return None
    dsn = _dsn_from_env()
    if not dsn:
        return None
    return create_engine(dsn, pool_pre_ping=True)


def ensure_schema(engine: "Engine") -> None:
    if text is None:
        return
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS invest_runs (
                    id SERIAL PRIMARY KEY,
                    ts TIMESTAMP NOT NULL,
                    domain TEXT,
                    query TEXT,
                    target TEXT,
                    verdict TEXT,
                    score INT,
                    rationale TEXT,
                    report_path TEXT
                );
                """
            )
        )

        # Per-startup info store
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS startups (
                    id SERIAL PRIMARY KEY,
                    created_at TIMESTAMP NOT NULL,
                    updated_at TIMESTAMP NOT NULL,
                    domain TEXT,
                    query TEXT,
                    name TEXT UNIQUE,
                    tech_raw TEXT,
                    tech_summary TEXT,
                    market_eval TEXT,
                    competitor_analysis TEXT,
                    decision TEXT,
                    score INT,
                    rationale TEXT
                );
                """
            )
        )

        # Optional: sources linked to startups
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS startup_sources (
                    id SERIAL PRIMARY KEY,
                    startup_name TEXT REFERENCES startups(name) ON DELETE CASCADE,
                    source TEXT
                );
                """
            )
        )
        # Ensure deduplication on (startup_name, source)
        conn.execute(
            text(
                """
                DO $$ BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM pg_indexes WHERE indexname = 'startup_sources_uniq'
                    ) THEN
                        CREATE UNIQUE INDEX startup_sources_uniq ON startup_sources (startup_name, source);
                    END IF;
                END $$;
                """
            )
        )


def log_run(engine: Optional["Engine"], s: Dict[str, Any]) -> None:
    if not engine or text is None:
        return
    ensure_schema(engine)
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO invest_runs (ts, domain, query, target, verdict, score, rationale, report_path)
                VALUES (:ts, :domain, :query, :target, :verdict, :score, :rationale, :report_path)
                """
            ),
            {
                "ts": datetime.utcnow(),
                "domain": s.get("domain"),
                "query": s.get("query"),
                "target": s.get("target"),
                "verdict": s.get("decision"),
                "score": s.get("score"),
                "rationale": s.get("rationale"),
                "report_path": s.get("report_path"),
            },
        )


def upsert_startup(engine: Optional["Engine"], *, domain: str, query: str, name: str, tech_raw: Optional[str]) -> None:
    if not engine or text is None:
        return
    ensure_schema(engine)
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO startups (created_at, updated_at, domain, query, name, tech_raw)
                VALUES (:now, :now, :domain, :query, :name, :tech_raw)
                ON CONFLICT (name) DO UPDATE SET
                    updated_at = EXCLUDED.updated_at,
                    domain = EXCLUDED.domain,
                    query = EXCLUDED.query,
                    tech_raw = COALESCE(EXCLUDED.tech_raw, startups.tech_raw)
                """
            ),
            {
                "now": datetime.utcnow(),
                "domain": domain,
                "query": query,
                "name": name,
                "tech_raw": tech_raw,
            },
        )


def update_startup_columns(engine: Optional["Engine"], name: str, updates: Dict[str, Any]) -> None:
    if not engine or text is None or not updates:
        return
    ensure_schema(engine)
    sets = ", ".join(f"{k} = :{k}" for k in updates.keys())
    params = {**updates, "name": name, "updated_at": datetime.utcnow()}
    with engine.begin() as conn:
        conn.execute(text(f"UPDATE startups SET {sets}, updated_at = :updated_at WHERE name = :name"), params)


def get_startup_by_name(engine: Optional["Engine"], name: str) -> Optional[Dict[str, Any]]:
    if not engine or text is None:
        return None
    ensure_schema(engine)
    with engine.begin() as conn:
        row = conn.execute(text("SELECT * FROM startups WHERE name = :name"), {"name": name}).mappings().first()
        return dict(row) if row else None


def add_startup_sources(engine: Optional["Engine"], name: str, sources: list[str]) -> None:
    if not engine or text is None or not sources:
        return
    ensure_schema(engine)
    with engine.begin() as conn:
        # Insert with ON CONFLICT DO NOTHING to deduplicate
        values_clause = ",".join([f"(:name, :s{i})" for i in range(len(sources))])
        params = {"name": name}
        params.update({f"s{i}": src for i, src in enumerate(sources)})
        conn.execute(
            text(
                f"INSERT INTO startup_sources (startup_name, source) VALUES {values_clause} "
                "ON CONFLICT (startup_name, source) DO NOTHING"
            ),
            params,
        )
