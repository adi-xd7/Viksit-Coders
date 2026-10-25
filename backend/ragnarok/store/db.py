"""SQLite evidence store and append-only audit log.

Tables: packs, documents, paragraphs, doc_flags, doc_relations, trade_tables,
trade_rows, audit_log, agent_memory (read only through ragnarok.memory). Filterable metadata is stored in columns; the full
Pydantic record is stored as JSON so every document and row can be reproduced
exactly. The audit log refuses UPDATE and DELETE (triggers).
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ragnarok.models import DAMAGE_KINDS, Document, LogEvent, Paragraph, TradeRow, TradeTable

SCHEMA = """
CREATE TABLE IF NOT EXISTS packs (
    pack_id TEXT PRIMARY KEY,
    path TEXT NOT NULL,
    event_id TEXT,
    name TEXT,
    as_of TEXT,
    manifest_json TEXT,
    ingested_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS documents (
    doc_id TEXT PRIMARY KEY,
    pack_id TEXT NOT NULL,
    file_path TEXT,
    file_name TEXT,
    format TEXT,
    file_sha256 TEXT,
    content_sha256 TEXT,
    event_id TEXT,
    title TEXT,
    source_name TEXT,
    source_type TEXT,
    reliability_tier INTEGER,
    pub_date TEXT,
    pub_time TEXT,
    country TEXT,
    sector TEXT,
    language TEXT,
    is_damaged INTEGER NOT NULL,
    n_paragraphs INTEGER NOT NULL,
    doc_json TEXT NOT NULL,
    ingested_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_documents_filters ON documents(event_id, country, sector, source_type, reliability_tier, pub_date);
CREATE TABLE IF NOT EXISTS paragraphs (
    doc_id TEXT NOT NULL REFERENCES documents(doc_id) ON DELETE CASCADE,
    ref TEXT NOT NULL,
    ordinal INTEGER NOT NULL,
    text TEXT NOT NULL,
    evidence_text TEXT,
    PRIMARY KEY (doc_id, ref)
);
CREATE TABLE IF NOT EXISTS doc_flags (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    doc_id TEXT NOT NULL REFERENCES documents(doc_id) ON DELETE CASCADE,
    category TEXT NOT NULL,          -- damage | notice | injection
    kind TEXT NOT NULL,              -- DamageKind value or injection pattern
    paragraph_ref TEXT,
    field TEXT,
    span_start INTEGER,
    span_end INTEGER,
    severity TEXT,
    detail TEXT
);
CREATE INDEX IF NOT EXISTS ix_doc_flags_doc ON doc_flags(doc_id);
CREATE TABLE IF NOT EXISTS doc_relations (
    doc_id TEXT NOT NULL REFERENCES documents(doc_id) ON DELETE CASCADE,
    type TEXT NOT NULL,
    target_doc_id TEXT NOT NULL,
    evidence TEXT,
    PRIMARY KEY (doc_id, type, target_doc_id)
);
CREATE TABLE IF NOT EXISTS trade_tables (
    table_id TEXT PRIMARY KEY,
    source_doc_id TEXT NOT NULL REFERENCES documents(doc_id) ON DELETE CASCADE,
    origin TEXT, destination TEXT, sector TEXT, unit TEXT, event_id TEXT, layout TEXT,
    table_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS trade_rows (
    row_id TEXT PRIMARY KEY,
    table_id TEXT NOT NULL REFERENCES trade_tables(table_id) ON DELETE CASCADE,
    source_doc_id TEXT NOT NULL,
    row_number INTEGER NOT NULL,
    paragraph_ref TEXT,
    origin TEXT, destination TEXT, sector TEXT, period TEXT,
    value REAL, currency TEXT, volume REAL, volume_unit TEXT,
    status TEXT NOT NULL,
    damage_reason TEXT,
    raw_text TEXT NOT NULL,
    provenance TEXT NOT NULL,
    warnings_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_trade_rows_filters ON trade_rows(origin, destination, sector, period, status);
CREATE TABLE IF NOT EXISTS audit_log (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id TEXT NOT NULL,
    run_number INTEGER NOT NULL,
    ts TEXT NOT NULL,
    agent TEXT NOT NULL,
    type TEXT NOT NULL,
    summary TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    refs_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_audit_case ON audit_log(case_id, seq);
CREATE TABLE IF NOT EXISTS store_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS embeddings (
    text_sha256 TEXT NOT NULL,
    model TEXT NOT NULL,
    dim INTEGER NOT NULL,
    vector BLOB NOT NULL,
    PRIMARY KEY (text_sha256, model)
);
CREATE TABLE IF NOT EXISTS query_cache (
    cache_key TEXT PRIMARY KEY,
    case_id TEXT NOT NULL,
    agent TEXT NOT NULL,
    query_norm TEXT NOT NULL,
    request_json TEXT NOT NULL,
    result_json TEXT NOT NULL,
    first_seq INTEGER,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS calculations (
    calc_id TEXT PRIMARY KEY,
    case_id TEXT NOT NULL,
    record_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS agent_memory (
    memory_id TEXT PRIMARY KEY,
    agent TEXT NOT NULL,
    lesson_key TEXT NOT NULL,
    lesson TEXT NOT NULL,
    entry_json TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (agent, lesson_key)
);
CREATE INDEX IF NOT EXISTS ix_agent_memory_agent ON agent_memory(agent);
CREATE TRIGGER IF NOT EXISTS audit_log_no_update BEFORE UPDATE ON audit_log
BEGIN SELECT RAISE(ABORT, 'audit_log is append-only'); END;
CREATE TRIGGER IF NOT EXISTS audit_log_no_delete BEFORE DELETE ON audit_log
BEGIN SELECT RAISE(ABORT, 'audit_log is append-only'); END;
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Store:
    def __init__(self, db_path: Path | str) -> None:
        self.path = Path(db_path)
        if str(db_path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        # One connection per agent; an agent may move between worker threads but never
        # shares its connection concurrently, so cross-thread use is safe.
        self.conn = sqlite3.connect(str(db_path), timeout=30, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.executescript(SCHEMA)

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> "Store":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    @contextmanager
    def tx(self) -> Iterator[sqlite3.Connection]:
        with self.conn:
            yield self.conn

    # ----------------------------------------------------------- version ---
    # Bumped on every evidence write so in-memory indexes can detect hot ingests.

    def version(self) -> int:
        r = self.conn.execute("SELECT value FROM store_meta WHERE key='version'").fetchone()
        return int(r["value"]) if r else 0

    @staticmethod
    def _bump(c: sqlite3.Connection) -> None:
        c.execute(
            "INSERT INTO store_meta(key, value) VALUES ('version', '1') "
            "ON CONFLICT(key) DO UPDATE SET value = CAST(value AS INTEGER) + 1"
        )

    # ------------------------------------------------------------- packs ---

    def upsert_pack(self, pack_id: str, path: Path, manifest: dict[str, Any] | None) -> None:
        m = manifest or {}
        with self.tx() as c:
            c.execute(
                "INSERT OR REPLACE INTO packs(pack_id, path, event_id, name, as_of, manifest_json, ingested_at) VALUES (?,?,?,?,?,?,?)",
                (pack_id, str(path), m.get("event_id"), m.get("name"), m.get("as_of"), json.dumps(m, default=str), _now()),
            )

    # --------------------------------------------------------- documents ---

    def document_owner(self, doc_id: str) -> tuple[str, str | None] | None:
        r = self.conn.execute("SELECT pack_id, file_sha256 FROM documents WHERE doc_id=?", (doc_id,)).fetchone()
        return (r["pack_id"], r["file_sha256"]) if r else None

    def save_document(self, doc: Document, tables: Iterable[TradeTable] = (), file_path: str | None = None) -> None:
        """Insert or replace a document with its paragraphs, flags, relations and trade tables."""
        with self.tx() as c:
            c.execute("DELETE FROM documents WHERE doc_id=?", (doc.meta.doc_id,))  # cascades
            self._insert_document(c, doc, file_path)
            for t in tables:
                self._insert_table(c, t)
            self._bump(c)

    def update_document(self, doc: Document) -> None:
        """Rewrite a stored document's record, flags and relations (paragraphs and tables unchanged)."""
        with self.tx() as c:
            m = doc.meta
            c.execute(
                "UPDATE documents SET is_damaged=?, doc_json=? WHERE doc_id=?",
                (int(doc.is_damaged), self._doc_json(doc), m.doc_id),
            )
            c.execute("DELETE FROM doc_flags WHERE doc_id=?", (m.doc_id,))
            c.execute("DELETE FROM doc_relations WHERE doc_id=?", (m.doc_id,))
            self._insert_flags_relations(c, doc)
            self._bump(c)

    @staticmethod
    def _doc_json(doc: Document) -> str:
        return doc.model_dump_json(exclude={"paragraphs"})

    def _insert_document(self, c: sqlite3.Connection, doc: Document, file_path: str | None) -> None:
        m = doc.meta
        c.execute(
            """INSERT INTO documents(doc_id, pack_id, file_path, file_name, format, file_sha256, content_sha256, event_id,
               title, source_name, source_type, reliability_tier, pub_date, pub_time, country, sector, language,
               is_damaged, n_paragraphs, doc_json, ingested_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                m.doc_id, doc.pack_id, file_path, m.file_name, m.format.value if m.format else None, doc.file_sha256,
                doc.content_sha256, m.event_id, m.title, m.source_name, m.source_type, m.reliability_tier,
                m.pub_date.isoformat() if m.pub_date else None, m.pub_time.isoformat(timespec="minutes") if m.pub_time else None,
                m.country, m.sector, m.language, int(doc.is_damaged), len(doc.paragraphs), self._doc_json(doc),
                doc.ingested_at.isoformat(),
            ),
        )
        c.executemany(
            "INSERT INTO paragraphs(doc_id, ref, ordinal, text, evidence_text) VALUES (?,?,?,?,?)",
            [(m.doc_id, p.ref, p.ordinal, p.text, p.evidence_text) for p in doc.paragraphs],
        )
        self._insert_flags_relations(c, doc)

    @staticmethod
    def _insert_flags_relations(c: sqlite3.Connection, doc: Document) -> None:
        did = doc.meta.doc_id
        rows = [
            (did, "damage" if f.kind in DAMAGE_KINDS else "notice", f.kind.value, f.paragraph_ref, None, None, None, None, f.detail)
            for f in doc.damage_flags
        ] + [
            (did, "injection", f.pattern, f.paragraph_ref, f.field, f.start, f.end, f.severity, f.excerpt)
            for f in doc.injection_flags
        ]
        c.executemany(
            "INSERT INTO doc_flags(doc_id, category, kind, paragraph_ref, field, span_start, span_end, severity, detail) VALUES (?,?,?,?,?,?,?,?,?)",
            rows,
        )
        c.executemany(
            "INSERT OR REPLACE INTO doc_relations(doc_id, type, target_doc_id, evidence) VALUES (?,?,?,?)",
            [(did, r.type.value, r.target_doc_id, r.evidence) for r in doc.relations],
        )

    def _insert_table(self, c: sqlite3.Connection, t: TradeTable) -> None:
        c.execute("DELETE FROM trade_tables WHERE table_id=?", (t.table_id,))
        c.execute(
            "INSERT INTO trade_tables(table_id, source_doc_id, origin, destination, sector, unit, event_id, layout, table_json) VALUES (?,?,?,?,?,?,?,?,?)",
            (t.table_id, t.source_doc_id, t.origin, t.destination, t.sector, t.unit, t.event_id, t.layout,
             t.model_dump_json(exclude={"rows"})),
        )
        c.executemany(
            """INSERT INTO trade_rows(row_id, table_id, source_doc_id, row_number, paragraph_ref, origin, destination, sector,
               period, value, currency, volume, volume_unit, status, damage_reason, raw_text, provenance, warnings_json)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            [
                (r.row_id, r.table_id, r.source_doc_id, r.row_number, r.paragraph_ref, r.origin, r.destination, r.sector,
                 r.period, r.value, r.currency, r.volume, r.volume_unit, r.status.value, r.damage_reason, r.raw_text,
                 r.provenance, json.dumps(r.warnings))
                for r in t.rows
            ],
        )

    def _paragraphs(self, doc_id: str) -> list[Paragraph]:
        rows = self.conn.execute(
            "SELECT ref, ordinal, text, evidence_text FROM paragraphs WHERE doc_id=? ORDER BY ordinal", (doc_id,)
        ).fetchall()
        return [Paragraph(ref=r["ref"], ordinal=r["ordinal"], text=r["text"], evidence_text=r["evidence_text"]) for r in rows]

    def get_document(self, doc_id: str) -> Document | None:
        r = self.conn.execute("SELECT doc_json FROM documents WHERE doc_id=?", (doc_id,)).fetchone()
        if not r:
            return None
        data = json.loads(r["doc_json"])
        data["paragraphs"] = [p.model_dump() for p in self._paragraphs(doc_id)]
        return Document.model_validate(data)

    def all_documents(self) -> list[Document]:
        ids = [r["doc_id"] for r in self.conn.execute("SELECT doc_id FROM documents ORDER BY doc_id")]
        return [d for d in (self.get_document(i) for i in ids) if d is not None]

    def get_paragraph(self, doc_id: str, ref: str) -> Paragraph | None:
        r = self.conn.execute(
            "SELECT ref, ordinal, text, evidence_text FROM paragraphs WHERE doc_id=? AND ref=?", (doc_id, ref)
        ).fetchone()
        return Paragraph(ref=r["ref"], ordinal=r["ordinal"], text=r["text"], evidence_text=r["evidence_text"]) if r else None

    def documents_for_pack(self, pack_id: str) -> list[str]:
        return [r["doc_id"] for r in self.conn.execute("SELECT doc_id FROM documents WHERE pack_id=? ORDER BY doc_id", (pack_id,))]

    # -------------------------------------------------------- trade data ---

    @staticmethod
    def _row(r: sqlite3.Row) -> TradeRow:
        return TradeRow(
            row_id=r["row_id"], table_id=r["table_id"], source_doc_id=r["source_doc_id"], row_number=r["row_number"],
            paragraph_ref=r["paragraph_ref"], origin=r["origin"], destination=r["destination"], sector=r["sector"],
            period=r["period"], value=r["value"], currency=r["currency"], volume=r["volume"], volume_unit=r["volume_unit"],
            status=r["status"], damage_reason=r["damage_reason"], raw_text=r["raw_text"], provenance=r["provenance"],
            warnings=json.loads(r["warnings_json"]),
        )

    def get_trade_table(self, table_id: str) -> TradeTable | None:
        r = self.conn.execute("SELECT table_json FROM trade_tables WHERE table_id=?", (table_id,)).fetchone()
        if not r:
            return None
        data = json.loads(r["table_json"])
        # rowid = insertion order = the order rows appear in the source document
        rows = self.conn.execute("SELECT * FROM trade_rows WHERE table_id=? ORDER BY rowid", (table_id,)).fetchall()
        data["rows"] = [self._row(x).model_dump() for x in rows]
        return TradeTable.model_validate(data)

    def get_trade_row(self, row_id: str) -> TradeRow | None:
        r = self.conn.execute("SELECT * FROM trade_rows WHERE row_id=?", (row_id,)).fetchone()
        return self._row(r) if r else None

    def all_trade_tables(self) -> list[TradeTable]:
        ids = [r["table_id"] for r in self.conn.execute("SELECT table_id FROM trade_tables ORDER BY table_id")]
        return [t for t in (self.get_trade_table(i) for i in ids) if t is not None]

    def all_trade_rows(self) -> list[TradeRow]:
        return [self._row(r) for r in self.conn.execute("SELECT * FROM trade_rows ORDER BY table_id, rowid")]

    def table_sectors_by_doc(self) -> dict[str, set[str]]:
        out: dict[str, set[str]] = {}
        for r in self.conn.execute("SELECT source_doc_id, sector FROM trade_tables"):
            if r["sector"]:
                out.setdefault(r["source_doc_id"], set()).add(r["sector"].lower())
        return out

    def incoming_relations(self, target_doc_id: str) -> list[tuple[str, str, str]]:
        """(source doc, relation type, evidence) for relations pointing at a document."""
        return [
            (r["doc_id"], r["type"], r["evidence"])
            for r in self.conn.execute(
                "SELECT doc_id, type, evidence FROM doc_relations WHERE target_doc_id=? ORDER BY doc_id", (target_doc_id,)
            )
        ]

    # -------------------------------------------------------- embeddings ---

    def get_embeddings(self, model: str, hashes: list[str]) -> dict[str, bytes]:
        out: dict[str, bytes] = {}
        for i in range(0, len(hashes), 500):
            part = hashes[i:i + 500]
            q = f"SELECT text_sha256, vector FROM embeddings WHERE model=? AND text_sha256 IN ({','.join('?' * len(part))})"
            for r in self.conn.execute(q, [model, *part]):
                out[r["text_sha256"]] = r["vector"]
        return out

    def put_embeddings(self, model: str, dim: int, items: list[tuple[str, bytes]]) -> None:
        with self.tx() as c:
            c.executemany(
                "INSERT OR REPLACE INTO embeddings(text_sha256, model, dim, vector) VALUES (?,?,?,?)",
                [(h, model, dim, v) for h, v in items],
            )

    # ------------------------------------------------------- query cache ---

    def cache_get(self, key: str) -> tuple[str, int | None] | None:
        r = self.conn.execute("SELECT result_json, first_seq FROM query_cache WHERE cache_key=?", (key,)).fetchone()
        return (r["result_json"], r["first_seq"]) if r else None

    def cache_put(self, key: str, case_id: str, agent: str, query_norm: str, request_json: str, result_json: str,
                  first_seq: int | None) -> None:
        with self.tx() as c:
            c.execute(
                "INSERT OR REPLACE INTO query_cache(cache_key, case_id, agent, query_norm, request_json, result_json, first_seq, created_at)"
                " VALUES (?,?,?,?,?,?,?,?)",
                (key, case_id, agent, query_norm, request_json, result_json, first_seq, _now()),
            )

    # ------------------------------------------------------ calculations ---

    def save_calculation(self, calc_id: str, case_id: str, record_json: str) -> None:
        with self.tx() as c:
            c.execute(
                "INSERT OR REPLACE INTO calculations(calc_id, case_id, record_json, created_at) VALUES (?,?,?,?)",
                (calc_id, case_id, record_json, _now()),
            )

    def get_calculation_json(self, calc_id: str) -> str | None:
        r = self.conn.execute("SELECT record_json FROM calculations WHERE calc_id=?", (calc_id,)).fetchone()
        return r["record_json"] if r else None

    # --------------------------------------------------------- audit log ---

    def append_event(self, ev: LogEvent) -> int:
        with self.tx() as c:
            cur = c.execute(
                "INSERT INTO audit_log(case_id, run_number, ts, agent, type, summary, payload_json, refs_json) VALUES (?,?,?,?,?,?,?,?)",
                (ev.case_id, ev.run_number, ev.ts.isoformat(), ev.agent.value, ev.type.value, ev.summary,
                 json.dumps(ev.payload, default=str), json.dumps(ev.refs)),
            )
            return int(cur.lastrowid)

    def events(self, case_id: str | None = None, after_seq: int = 0) -> list[LogEvent]:
        q = "SELECT * FROM audit_log WHERE seq > ?"
        args: list[Any] = [after_seq]
        if case_id is not None:
            q += " AND case_id = ?"
            args.append(case_id)
        rows = self.conn.execute(q + " ORDER BY seq", args).fetchall()
        return [
            LogEvent(seq=r["seq"], case_id=r["case_id"], run_number=r["run_number"], ts=r["ts"], agent=r["agent"],
                     type=r["type"], summary=r["summary"], payload=json.loads(r["payload_json"]), refs=json.loads(r["refs_json"]))
            for r in rows
        ]

    def export_jsonl(self, path: Path, case_id: str | None = None) -> int:
        evs = self.events(case_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as f:
            for e in evs:
                f.write(e.model_dump_json() + "\n")
        return len(evs)
