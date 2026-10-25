"""Pack ingestion: discover files, parse, flag, store, and log.

Works for any folder with a manifest (dev pack or a live-added pack) with no
code changes. A single file can never stop the run: every failure becomes a
Document with damage flags plus an ERROR/DAMAGED_INPUT audit event.
"""

from __future__ import annotations

import hashlib
import json
import re
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ragnarok.config import Settings, get_settings
from ragnarok.ingest.decoding import sniff_format
from ragnarok.ingest.extract import Extracted, extract
from ragnarok.ingest.injection import evidence_text, hidden_run_flags, scan_text
from ragnarok.ingest.metadata import (
    id_from_filename,
    norm_date,
    merge_metadata,
    normalise_manifest_entry,
    parse_header,
    safe_id,
)
from ragnarok.ingest.paragraphs import looks_cut_off, split_paragraphs
from ragnarok.ingest.relations import apply_relations, body_hash
from ragnarok.ingest.trade import parse_trade_tables
from ragnarok.models import (
    DAMAGE_KINDS,
    AgentName,
    DamageFlag,
    DamageKind,
    DocFormat,
    DocMeta,
    Document,
    InjectionFlag,
    LogEvent,
    LogEventType,
    MetadataConflict,
    ParserInfo,
    TradeTable,
)
from ragnarok.store.db import Store

SUPPORTED_SUFFIXES = {".pdf", ".txt", ".docx"}
# Top-level pack files that are catalogue/instructions for humans, not evidence.
PACK_META_FILES = {"manifest.json", "hashes.sha256", "readme.md", "sample_question.txt"}
_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".bmp"}


# --------------------------------------------------------------------------- #
# Manifest and pack discovery
# --------------------------------------------------------------------------- #


@dataclass
class PackManifest:
    pack_id: str
    root: Path
    top: dict[str, Any]
    entries: list[dict[str, str]]  # normalised entries (canonical keys)
    entry_conflicts: dict[int, list[MetadataConflict]]
    hashes: dict[str, str]  # relative path (posix, lower-case) -> sha256
    problems: list[str] = field(default_factory=list)


def load_manifest(pack_dir: Path) -> PackManifest:
    problems: list[str] = []
    top: dict[str, Any] = {}
    raw_entries: list[dict[str, Any]] = []
    mpath = pack_dir / "manifest.json"
    if mpath.is_file():
        try:
            data = json.loads(mpath.read_text(encoding="utf-8-sig"))
            if isinstance(data, list):
                raw_entries = data
            elif isinstance(data, dict):
                top = {k: v for k, v in data.items() if not isinstance(v, list)}
                for key in ("documents", "docs", "files", "items", "entries"):
                    if isinstance(data.get(key), list):
                        raw_entries = data[key]
                        break
            raw_entries = [e for e in raw_entries if isinstance(e, dict)]
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            problems.append(f"manifest.json unreadable: {exc}")
    else:
        problems.append("no manifest.json; files ingested from the folder only")
    entries: list[dict[str, str]] = []
    conflicts: dict[int, list[MetadataConflict]] = {}
    for i, e in enumerate(raw_entries):
        norm, conf = normalise_manifest_entry(e)
        entries.append(norm)
        if conf:
            conflicts[i] = conf
    hashes: dict[str, str] = {}
    hpath = pack_dir / "hashes.sha256"
    if hpath.is_file():
        for line in hpath.read_text(encoding="utf-8-sig", errors="replace").splitlines():
            parts = line.strip().split(None, 1)
            if len(parts) == 2 and re.fullmatch(r"[0-9a-fA-F]{64}", parts[0]):
                hashes[parts[1].strip().lstrip("*").replace("\\", "/").lower()] = parts[0].lower()
    pack_id = str(top.get("pack") or top.get("pack_id") or pack_dir.name)
    pack_id = safe_id(pack_id) or id_from_filename(pack_dir.name)
    return PackManifest(pack_id=pack_id, root=pack_dir, top=top, entries=entries, entry_conflicts=conflicts,
                        hashes=hashes, problems=problems)


def _inside(root: Path, p: Path) -> bool:
    try:
        p.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _resolve_entry_file(root: Path, name: str) -> Path | None:
    for cand in (root / "docs" / name, root / name):
        if cand.is_file() and _inside(root, cand):
            return cand
    return None


@dataclass
class FileJob:
    path: Path | None  # None => listed in the manifest but missing
    manifest_entry: dict[str, str] | None
    manifest_conflicts: list[MetadataConflict]
    expected_sha256: str | None
    listed_name: str


def discover(pm: PackManifest) -> tuple[list[FileJob], list[str]]:
    jobs: list[FileJob] = []
    problems: list[str] = []
    claimed: set[Path] = set()
    root = pm.root
    for i, e in enumerate(pm.entries):
        name = e.get("FILE") or ""
        if not name:
            did = e.get("DOC_ID") or f"entry {i}"
            # Try <doc_id>.<ext> for manifests that omit the file name.
            name = next((f"{did}{s}" for s in SUPPORTED_SUFFIXES if _resolve_entry_file(root, f"{did}{s}")), "")
            if not name:
                problems.append(f"manifest entry {did} has no file name")
                continue
        if Path(name).is_absolute() or ".." in Path(name).parts:
            problems.append(f"manifest entry {name!r} points outside the pack; refused")
            continue
        path = _resolve_entry_file(root, name)
        rel = None
        if path is not None:
            claimed.add(path.resolve())
            rel = path.relative_to(root).as_posix().lower()
        expected = pm.hashes.get(rel) if rel else None
        expected = expected or pm.hashes.get(f"docs/{name}".lower()) or pm.hashes.get(name.lower())
        jobs.append(FileJob(path=path, manifest_entry=e, manifest_conflicts=pm.entry_conflicts.get(i, []),
                            expected_sha256=expected, listed_name=name))
    # Files present but not listed (e.g. a trade table dropped into the pack).
    for p in sorted(root.rglob("*")):
        if not p.is_file() or p.resolve() in claimed or not _inside(root, p):
            continue
        rel_parts = p.relative_to(root).parts
        if len(rel_parts) == 1 and p.name.lower() in PACK_META_FILES:
            continue
        if p.suffix.lower() in _IMAGE_SUFFIXES or any(part.startswith(".") for part in rel_parts):
            continue
        if len(rel_parts) == 1 and p.suffix.lower() not in SUPPORTED_SUFFIXES:
            continue
        if p.suffix.lower() not in SUPPORTED_SUFFIXES:
            problems.append(f"unsupported file skipped: {p.relative_to(root).as_posix()}")
            continue
        rel = p.relative_to(root).as_posix().lower()
        jobs.append(FileJob(path=p, manifest_entry=None, manifest_conflicts=[], expected_sha256=pm.hashes.get(rel),
                            listed_name=p.name))
    return jobs, problems


# --------------------------------------------------------------------------- #
# Single file
# --------------------------------------------------------------------------- #


@dataclass
class FileResult:
    document: Document
    tables: list[TradeTable]
    header: dict[str, str]
    error: str | None = None


def _scan_document(paragraphs, header_fields: dict[str, str], side_text: dict[str, str], hidden_runs: list[str]):
    flags: list[InjectionFlag] = []
    new_paras = []
    for p in paragraphs:
        pf = scan_text(p.text, paragraph_ref=p.ref) + hidden_run_flags(p.text, p.ref, hidden_runs)
        flags.extend(pf)
        new_paras.append(p.model_copy(update={"evidence_text": evidence_text(p.text, pf)}))
    for key, value in header_fields.items():
        flags.extend(scan_text(value, field=f"header.{key}"))
    for key, value in side_text.items():
        flags.extend(scan_text(value, field=key))
    return new_paras, flags


def ingest_file(job: FileJob, pack_id: str, settings: Settings) -> FileResult:
    damage: list[DamageFlag] = []
    data = b""
    file_sha: str | None = None
    if job.path is None:
        damage.append(DamageFlag(kind=DamageKind.UNPARSEABLE, detail=f"file {job.listed_name!r} is listed in the manifest but missing"))
        ex = Extracted(text="", format=None, parser=ParserInfo(parser="none"))
    else:
        size = job.path.stat().st_size
        if size > settings.max_upload_bytes:
            damage.append(DamageFlag(kind=DamageKind.UNPARSEABLE, detail=f"file is {size} bytes, above the {settings.max_upload_bytes}-byte limit; not read"))
            ex = Extracted(text="", format=None, parser=ParserInfo(parser="none"))
        else:
            data = job.path.read_bytes()
            file_sha = hashlib.sha256(data).hexdigest()
            sniffed = sniff_format(data)
            ex = extract(data, sniffed)
            suffix = job.path.suffix.lower().lstrip(".")
            if ex.format and suffix in {f.value for f in DocFormat} and ex.format.value != suffix:
                ex.parser.warnings.append(f"extension .{suffix} but content is {ex.format.value}; parsed as {ex.format.value}")
        if job.expected_sha256 and file_sha and file_sha != job.expected_sha256:
            damage.append(DamageFlag(kind=DamageKind.HASH_MISMATCH, detail="file content differs from the pack's hashes.sha256"))
    damage.extend(ex.damage)

    header = parse_header(ex.text)
    ex.parser.warnings.extend(header.warnings)
    if ex.text.strip() and not header.found:
        damage.append(DamageFlag(kind=DamageKind.MISSING_HEADER, detail="no metadata header block found"))
    elif header.found and not header.terminated:
        damage.append(DamageFlag(kind=DamageKind.MALFORMED, detail="metadata header not terminated by '---'"))
    if job.manifest_entry is None:
        damage.append(DamageFlag(kind=DamageKind.NOT_IN_MANIFEST, detail="file is not listed in the pack manifest"))

    merged = merge_metadata(header.fields, job.manifest_entry)
    for prob in merged.problems:
        damage.append(DamageFlag(kind=DamageKind.BAD_METADATA, detail=prob))
    v = merged.values
    stem_id = id_from_filename(job.path.stem if job.path else Path(job.listed_name).stem)
    doc_id = safe_id(v.get("doc_id"))
    if doc_id is None:
        if v.get("doc_id"):
            damage.append(DamageFlag(kind=DamageKind.BAD_METADATA, detail=f"DOC_ID {v['doc_id']!r} unusable; file name used"))
        doc_id = stem_id
    conflicts = list(job.manifest_conflicts) + merged.conflicts
    for c in merged.conflicts:
        damage.append(DamageFlag(kind=DamageKind.METADATA_CONFLICT,
                                 detail=f"{c.field}: header {c.header_value!r} vs manifest {c.manifest_value!r} ({c.resolution})"))

    split = split_paragraphs(header.body, v.get("title"))
    ex.parser.warnings.extend(split.warnings)
    damage.extend(split.damage)
    paragraphs = split.paragraphs
    if header.found and not paragraphs and not any(f.kind in {DamageKind.EMPTY, DamageKind.UNPARSEABLE} for f in damage):
        damage.append(DamageFlag(kind=DamageKind.HEADER_ONLY, detail="metadata header present but no body text"))
    paragraphs, inj = _scan_document(paragraphs, header.fields, ex.side_text, ex.hidden_runs)
    # Cut-off check on the last paragraph that is the document's own prose: a
    # planted instruction line without a full stop is not a truncated body.
    injected_refs = {f.paragraph_ref for f in inj if f.severity == "high" and f.paragraph_ref}
    own = [p for p in paragraphs if p.ref not in injected_refs]
    if own and looks_cut_off(own[-1].text):
        damage.append(DamageFlag(kind=DamageKind.TRUNCATED, detail="body ends mid-sentence (document appears cut off)",
                                 paragraph_ref=own[-1].ref))

    meta = DocMeta(
        doc_id=doc_id,
        event_id=v.get("event_id"),
        title=v.get("title") or "",
        source_name=v.get("source_name") or "",
        source_type=v.get("source_type") or "unknown",
        reliability_tier=v.get("reliability_tier"),
        pub_date=v.get("pub_date"),
        pub_time=v.get("pub_time"),
        country=v.get("country"),
        sector=v.get("sector"),
        language=v.get("language"),
        file_name=job.listed_name,
        format=ex.format,
        raw=merged.raw,
        conflicts=conflicts,
    )
    doc = Document(
        meta=meta, paragraphs=paragraphs, text=ex.text, file_sha256=file_sha, parser=ex.parser,
        pack_id=pack_id, damage_flags=damage, injection_flags=inj,
    )
    doc.content_sha256 = body_hash(doc)
    tables: list[TradeTable] = []
    try:
        tables = parse_trade_tables(doc, header.fields)
    except Exception as exc:  # noqa: BLE001 - a broken table must not lose the document
        doc.damage_flags.append(DamageFlag(kind=DamageKind.MALFORMED, detail=f"trade table could not be parsed: {type(exc).__name__}"))
    if any(t.layout == "fixed" for t in tables):
        # A table ends in a number, not a full stop: judge truncation by the table.
        doc.damage_flags = [f for f in doc.damage_flags
                            if not (f.kind == DamageKind.TRUNCATED and f.detail.startswith("body ends mid-sentence"))]
        for t in tables:
            cut = [r.row_id for r in t.rows if r.status.value == "truncated"]
            if cut or any(f.kind == DamageKind.TRUNCATED for f in t.damage_flags):
                doc.damage_flags.append(DamageFlag(kind=DamageKind.TRUNCATED,
                                                   detail=f"trade table {t.table_id} is cut off ({', '.join(cut) or 'rows missing'})"))
    for t in tables:
        for f in t.damage_flags:
            if f.kind == DamageKind.METADATA_CONFLICT:
                doc.meta.conflicts.append(MetadataConflict(
                    field="SECTOR", header_value=doc.meta.raw.get("header.SECTOR"), manifest_value=doc.meta.raw.get("manifest.SECTOR"),
                    resolution=f"content disagrees: {f.detail}",
                ))
    return FileResult(document=doc, tables=tables, header=header.fields)


def _fallback_document(job: FileJob, pack_id: str, exc: BaseException) -> Document:
    """Last-resort record when ingest_file itself failed unexpectedly."""
    name = job.path.name if job.path else job.listed_name
    e = job.manifest_entry or {}
    doc_id = safe_id(e.get("DOC_ID")) or id_from_filename(Path(name).stem)
    file_sha = hashlib.sha256(job.path.read_bytes()).hexdigest() if job.path and job.path.is_file() else None
    meta = DocMeta(doc_id=doc_id, event_id=None, title=e.get("TITLE", ""), source_name=e.get("SOURCE_NAME", ""),
                   source_type=e.get("SOURCE_TYPE") or "unknown", pub_date=norm_date(e.get("PUB_DATE")), file_name=name,
                   raw={f"manifest.{k}": v for k, v in e.items()})
    return Document(meta=meta, file_sha256=file_sha, parser=ParserInfo(parser="none"), pack_id=pack_id,
                    damage_flags=[DamageFlag(kind=DamageKind.UNPARSEABLE, detail=f"ingestion failed: {type(exc).__name__}: {str(exc)[:150]}")])


# --------------------------------------------------------------------------- #
# Pack
# --------------------------------------------------------------------------- #


@dataclass
class IngestReport:
    pack_id: str
    pack_dir: Path
    manifest_count: int | None
    documents: list[Document]
    tables: list[TradeTable]
    problems: list[str]
    errors: list[str]
    skipped: list[str]  # doc IDs not stored (ID collisions with another pack)
    pack_as_of: str | None = None  # informational; the case's own as_of is what retrieval enforces


def _ev(store: Store, pack_id: str, type_: LogEventType, summary: str, payload: dict | None = None, refs: list[str] | None = None) -> None:
    store.append_event(LogEvent(
        case_id=f"ingest:{pack_id}", agent=AgentName.HEIMDALL, type=type_, summary=summary[:500],
        payload=payload or {}, refs=refs or [],
    ))


def ingest_pack(pack_dir: Path | str, store: Store, settings: Settings | None = None) -> IngestReport:
    settings = settings or get_settings()
    pack_dir = Path(pack_dir).resolve()
    if not pack_dir.is_dir():
        raise FileNotFoundError(f"pack folder not found: {pack_dir}")
    pm = load_manifest(pack_dir)
    pack_id = pm.pack_id
    store.upsert_pack(pack_id, pack_dir, pm.top)
    jobs, problems = discover(pm)
    problems = pm.problems + problems
    for prob in problems:
        _ev(store, pack_id, LogEventType.ERROR, f"pack {pack_id}: {prob}")
    count = pm.top.get("count") or pm.top.get("document_count")
    if isinstance(count, int) and count != len(pm.entries):
        problems.append(f"manifest count {count} != {len(pm.entries)} entries")

    docs: list[Document] = []
    tables: list[TradeTable] = []
    errors: list[str] = []
    skipped: list[str] = []
    used_ids: dict[str, str] = {}
    _ev(store, pack_id, LogEventType.INGEST, f"ingest started: pack {pack_id}, {len(jobs)} file(s)", {"pack_dir": str(pack_dir)})
    for job in jobs:
        try:
            res = ingest_file(job, pack_id, settings)
            doc, doc_tables = res.document, res.tables
        except Exception as exc:  # noqa: BLE001
            doc, doc_tables = _fallback_document(job, pack_id, exc), []
            msg = f"{job.listed_name}: {type(exc).__name__}: {exc}"
            errors.append(msg)
            _ev(store, pack_id, LogEventType.ERROR, f"ingestion error in {msg}"[:500],
                {"traceback": traceback.format_exc(limit=5)}, [doc.meta.doc_id])
        did = doc.meta.doc_id
        if did in used_ids:  # two files in one pack claim the same ID: keep both, rename the later one
            new_id = id_from_filename(f"{did}.{Path(job.listed_name).stem}")
            if new_id in used_ids:
                new_id = id_from_filename(f"{did}.{len(used_ids)}")
            doc.damage_flags.append(DamageFlag(kind=DamageKind.METADATA_CONFLICT,
                                               detail=f"DOC_ID {did} already used by {used_ids[did]}; stored as {new_id}"))
            doc.meta = doc.meta.model_copy(update={"doc_id": new_id})
            for t in doc_tables:
                t.source_doc_id = new_id
                for r in t.rows:
                    r.source_doc_id = new_id
            did = new_id
        owner = store.document_owner(did)
        if owner and owner[0] != pack_id:
            if owner[1] == doc.file_sha256:
                _ev(store, pack_id, LogEventType.INGEST, f"{did} already ingested from pack {owner[0]} (same file); skipped", refs=[did])
            else:
                _ev(store, pack_id, LogEventType.ERROR,
                    f"{did} already exists from pack {owner[0]} with different content; new copy not stored", refs=[did])
                errors.append(f"{did}: ID collision with pack {owner[0]}")
            skipped.append(did)
            continue
        used_ids[did] = job.listed_name
        store.save_document(doc, doc_tables, str(job.path) if job.path else None)
        docs.append(doc)
        tables.extend(doc_tables)
        _log_document(store, pack_id, doc, doc_tables)

    # Relations over the whole store (new pack vs everything already ingested).
    all_docs = store.all_documents()
    for d in apply_relations(all_docs):
        store.update_document(d)
    refreshed = {d.meta.doc_id: d for d in all_docs}
    docs = [refreshed.get(d.meta.doc_id, d) for d in docs]
    for d in docs:
        for r in d.relations:
            _ev(store, pack_id, LogEventType.INGEST, f"{d.meta.doc_id} {r.type.value} {r.target_doc_id}: {r.evidence}",
                {"relation": r.type.value}, [d.meta.doc_id, r.target_doc_id])
    _ev(store, pack_id, LogEventType.INGEST, f"ingest finished: pack {pack_id}, {len(docs)} document(s), {len(tables)} trade table(s)",
        {"errors": len(errors)})
    return IngestReport(pack_id=pack_id, pack_dir=pack_dir, manifest_count=count if isinstance(count, int) else None,
                        documents=docs, tables=tables, problems=problems, errors=errors, skipped=skipped,
                        pack_as_of=str(pm.top["as_of"]) if pm.top.get("as_of") else None)


def _log_document(store: Store, pack_id: str, doc: Document, tables: list[TradeTable]) -> None:
    m = doc.meta
    did = m.doc_id
    _ev(store, pack_id, LogEventType.INGEST,
        f"{did} ({m.format.value if m.format else 'unreadable'}, {doc.parser.encoding or doc.parser.parser}): "
        f"{len(doc.paragraphs)} paragraph(s), {sum(len(t.rows) for t in tables)} trade row(s)",
        {"file_sha256": doc.file_sha256, "content_sha256": doc.content_sha256, "pub_date": str(m.pub_date)}, [did])
    real = [f for f in doc.damage_flags if f.kind in DAMAGE_KINDS]
    if real:
        _ev(store, pack_id, LogEventType.DAMAGED_INPUT, f"{did} damaged: " + "; ".join(f"{f.kind.value}: {f.detail}" for f in real),
            {"flags": [f.model_dump() for f in real]}, [did])
    for f in doc.injection_flags:
        if f.severity in {"medium", "high"}:
            where = f.paragraph_ref or f.field or "?"
            _ev(store, pack_id, LogEventType.TRAP_INJECTION,
                f"{did}#{where}: suspected embedded instruction ({f.pattern}, {f.severity}); text kept, marked for agents",
                {"flag": f.model_dump()}, [f"{did}#{f.paragraph_ref}" if f.paragraph_ref else did])
    for t in tables:
        bad = [r for r in t.rows if r.status.value != "valid"]
        if bad or t.damage_flags:
            _ev(store, pack_id, LogEventType.DAMAGED_INPUT,
                f"trade table {t.table_id}: {len(bad)} invalid row(s); " + "; ".join(f.detail for f in t.damage_flags),
                {"invalid_rows": {r.row_id: f"{r.status.value}: {r.damage_reason}" for r in bad}}, [t.table_id] + [r.row_id for r in bad])
