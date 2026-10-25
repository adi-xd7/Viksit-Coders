"""FastAPI app: cases, live events (SSE), evidence reads, pack ingest, evidence feed.

Run: .venv/Scripts/python -m uvicorn ragnarok.api:app --app-dir backend --port 8000

Endpoints (the API's whole surface):
    POST /cases                      {question, as_of} -> {case_id}
    GET  /cases/{case_id}            status (running | complete | partial | failed) + results
    GET  /cases/{case_id}/events     Server-Sent Events of the real audit log (?after=seq&follow=true)
    GET  /docs/{doc_id}[/{para}]     a document / one paragraph, as_of-gated (?as_of= or ?case_id=)
    GET  /trade/{table_id}[/{row}]   a trade table / one row, as_of-gated (?as_of= or ?case_id=)
    POST /ingest                     form: pack_dir (inside PACKS_DIR) or file (pack .zip)
    GET  /feed?as_of=                evidence feed by publication date with badges
    GET  /api/health                 config check (no secrets)
OpenAPI docs are served at /api/docs (so /docs/{doc_id} stays free for documents).

Every evidence path goes through RetrievalService and its as_of gate; out-of-window
requests return 403 and are logged as CLOCK_VIOLATION_BLOCKED. Cases run through
the same core functions as the CLI (ragnarok.trial.runner).
"""

from __future__ import annotations

import io
import re
import shutil
import threading
import time
import zipfile
from datetime import date, datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Callable

from fastapi import FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from ragnarok import __version__
from ragnarok.config import Settings, get_settings
from ragnarok.llm.client import Backend
from ragnarok.models import DAMAGE_KINDS, AgentName, LogEventType, RelationType
from ragnarok.retrieval.service import RetrievalService
from ragnarok.retrieval.types import TradeQuery
from ragnarok.store.db import Store
from ragnarok.trial.runner import CaseRunner, case_dir, case_results, case_status

DOC_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
REF = re.compile(r"^[A-Za-z0-9]{1,16}$")
API_CASE = "api"  # audit-log case for evidence reads made outside a case
PACK_EXTENSIONS = {".txt", ".pdf", ".docx", ".json", ".sha256", ".md", ".csv", ".png"}


class CaseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question: str = Field(min_length=5, max_length=2000)
    as_of: date


def create_app(settings: Settings | None = None, backend_factory: Callable[[], Backend] | None = None,
               service: RetrievalService | None = None) -> FastAPI:
    settings = settings or get_settings()
    app = FastAPI(title="Trial of the Nine Realms", version=__version__, docs_url="/api/docs", redoc_url=None, swagger_ui_oauth2_redirect_url="/api/docs/oauth2-redirect",
                  openapi_url="/api/openapi.json")
    app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_methods=["GET", "POST"],
                       allow_headers=["*"])
    shared: dict[str, RetrievalService] = {}
    lock = threading.Lock()

    def base_service() -> RetrievalService:
        """One loaded index + embedder for the app; created on first use."""
        with lock:
            if "svc" not in shared:
                shared["svc"] = service or RetrievalService(Store(settings.db_path), settings)
            return shared["svc"]

    runner = CaseRunner(settings, base_service, backend_factory)
    app.state.runner = runner
    app.state.settings = settings

    def request_service() -> RetrievalService:
        return base_service().fork()  # own SQLite connection per request

    def as_of_for(as_of: date | None, case_id: str | None) -> tuple[date, str]:
        if case_id:
            st = _status(case_id)
            if not st.get("as_of"):
                raise HTTPException(409, "case has no as_of yet")
            case_as_of = date.fromisoformat(str(st["as_of"]))
            if as_of and as_of != case_as_of:
                raise HTTPException(400, f"as_of {as_of} differs from the case's as_of {case_as_of}")
            return case_as_of, case_id
        if as_of is None:
            raise HTTPException(400, "as_of (or case_id) is required: every evidence path is date-gated")
        return as_of, API_CASE

    def _status(case_id: str) -> dict:
        try:
            case_dir(settings, case_id)
        except ValueError:
            raise HTTPException(400, "invalid case id")
        st = case_status(settings, case_id, running=runner.is_running(case_id))
        if st is None:
            raise HTTPException(404, "no such case")
        return st

    # ------------------------------------------------------------- health ---

    @app.get("/api/health")
    def health() -> dict[str, object]:
        return {"status": "ok", "version": __version__, "has_api_key": settings.has_api_key,
                "provider": settings.llm_provider, "models": {r: settings.model_for(r) for r in ("fast", "advocate", "judge")},
                "packs_dir_exists": settings.packs_dir.is_dir(), "running_cases": runner.running()}

    # -------------------------------------------------------------- cases ---

    @app.post("/cases", status_code=202)
    def create_case(req: CaseRequest) -> dict:
        if backend_factory is None and not settings.has_api_key:
            raise HTTPException(503, f"{settings.api_key_name} is not set (LLM_PROVIDER={settings.llm_provider})")
        try:
            case_id = runner.start(req.question.strip(), req.as_of)
        except RuntimeError:
            raise HTTPException(409, f"a case is already running (limit {settings.max_concurrent_cases}); try again later")
        return {"case_id": case_id, "status": "running", "events": f"/cases/{case_id}/events"}

    @app.get("/cases/{case_id}")
    def get_case(case_id: str) -> dict:
        st = _status(case_id)
        if st["status"] != "running":
            st["results"] = case_results(settings, case_id)
        return st

    @app.get("/cases/{case_id}/events")
    def case_events(case_id: str, request: Request, after: int = Query(0, ge=0), follow: bool = True) -> StreamingResponse:
        _status(case_id)
        last_id = request.headers.get("last-event-id")
        start = int(last_id) if last_id and last_id.isdigit() else after

        def stream():
            last, idle = start, 0.0
            while True:
                with Store(settings.db_path) as s:
                    evs = s.events(case_id, last)
                for e in evs:
                    last = e.seq or last
                    yield f"id: {e.seq}\nevent: {e.type.value}\ndata: {e.model_dump_json()}\n\n"
                ended = any(e.type == LogEventType.RUN_END for e in evs)
                if ended or not follow or (not evs and not runner.is_running(case_id)):
                    yield "event: end\ndata: {}\n\n"
                    return
                time.sleep(0.5)
                idle = 0.0 if evs else idle + 0.5
                if idle >= 15:
                    idle = 0.0
                    yield ": keep-alive\n\n"

        return StreamingResponse(stream(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    # ---------------------------------------------------------- documents ---

    def doc_view(doc_id: str, refs: list[str] | None, as_of: date | None, case_id: str | None) -> dict:
        if not DOC_ID.match(doc_id) or any(not REF.match(r) for r in refs or []):
            raise HTTPException(400, "invalid document or paragraph id")
        when, cid = as_of_for(as_of, case_id)
        svc = request_service()
        try:
            v = svc.read_doc(doc_id, when, AgentName.USER, refs, case_id=cid)
            if v.status == "not_found":
                raise HTTPException(404, "no such document")
            if v.status == "blocked":
                raise HTTPException(403, f"document {doc_id} is not available as of {when}: {v.reason}")
            if refs and v.missing_refs:
                raise HTTPException(404, f"no such paragraph: {', '.join(v.missing_refs)}")
            doc = svc.store.get_document(doc_id)
            originals = {p.ref: p.text for p in doc.paragraphs}
            paras = [{"ref": p.ref, "anchor": f"{doc_id}-{p.ref}", "text": p.text, "injection_flagged": p.injection_flagged,
                      "original_text": originals.get(p.ref) if originals.get(p.ref) != p.text else None}
                     for p in v.paragraphs]
            return {"doc_id": doc_id, "as_of": when, "title": v.title, "pub_date": v.pub_date, "pub_time": v.pub_time,
                    "reliability_tier": v.reliability_tier, "source_name": v.source_name, "source_type": v.source_type,
                    "country": v.country, "sector": v.sector, "event_id": v.event_id, "format": doc.meta.format,
                    "content_sha256": doc.content_sha256, "damage": v.damage, "relations": v.relations,
                    "injection_flags": [f.model_dump(mode="json") for f in doc.injection_flags],
                    "paragraphs": paras}
        finally:
            svc.store.close()

    @app.get("/docs/{doc_id}")
    def get_doc(doc_id: str, as_of: date | None = None, case_id: str | None = None) -> dict:
        return doc_view(doc_id, None, as_of, case_id)

    @app.get("/docs/{doc_id}/{paragraph_ref}")
    def get_paragraph(doc_id: str, paragraph_ref: str, as_of: date | None = None, case_id: str | None = None) -> dict:
        return doc_view(doc_id, [paragraph_ref], as_of, case_id)

    # -------------------------------------------------------------- trade ---

    def trade_view(table_id: str, row: str | None, as_of: date | None, case_id: str | None) -> dict:
        if not DOC_ID.match(table_id) or (row is not None and not REF.match(row.split("#")[-1])):
            raise HTTPException(400, "invalid table or row id")
        when, cid = as_of_for(as_of, case_id)
        svc = request_service()
        try:
            tab = svc.store.get_trade_table(table_id)
            if tab is None:
                raise HTTPException(404, "no such trade table")
            row_id = None if row is None else (row if "#" in row else f"{table_id}#{row}")
            q = TradeQuery(row_ids=[row_id]) if row_id else TradeQuery(table_ids=[table_id])
            res = svc.get_trade_rows(q, when, AgentName.USER, case_id=cid)
            if res.blocked and not res.rows:
                raise HTTPException(403, f"trade data {row_id or table_id} is not available as of {when}")
            if row_id and not res.rows:
                raise HTTPException(404, "no such row")
            meta = tab.model_dump(mode="json", exclude={"rows"})
            return {"table": meta, "as_of": when, "rows": [r.model_dump(mode="json") for r in res.rows],
                    "withheld_after_as_of": len(res.blocked)}
        finally:
            svc.store.close()

    @app.get("/trade/{table_id}")
    def get_table(table_id: str, as_of: date | None = None, case_id: str | None = None) -> dict:
        return trade_view(table_id, None, as_of, case_id)

    @app.get("/trade/{table_id}/{row}")
    def get_row(table_id: str, row: str, as_of: date | None = None, case_id: str | None = None) -> dict:
        return trade_view(table_id, row, as_of, case_id)

    # ------------------------------------------------------------- ingest ---

    def _summary(rep) -> dict:
        return {"pack_id": rep.pack_id, "documents": len(rep.documents), "tables": len(rep.tables),
                "damaged": sum(1 for d in rep.documents if d.is_damaged),
                "injection_flags": sum(len(d.injection_flags) for d in rep.documents),
                "problems": rep.problems[:50], "errors": rep.errors[:50], "skipped": rep.skipped}

    def _safe_extract(upload: UploadFile) -> Path:
        name = Path(upload.filename or "").name
        if not name.lower().endswith(".zip"):
            raise HTTPException(415, "upload a pack as a .zip file")
        limit = settings.max_upload_bytes
        data = upload.file.read(limit + 1)
        if len(data) > limit:
            raise HTTPException(413, f"upload exceeds {limit} bytes")
        try:
            zf = zipfile.ZipFile(io.BytesIO(data))
        except zipfile.BadZipFile:
            raise HTTPException(400, "not a valid zip file")
        infos = [i for i in zf.infolist() if not i.is_dir()]
        if not infos or len(infos) > settings.max_upload_files:
            raise HTTPException(400, f"a pack must contain 1-{settings.max_upload_files} files")
        if sum(i.file_size for i in infos) > 10 * limit:
            raise HTTPException(413, "uncompressed pack is too large")
        for i in infos:
            p = PurePosixPath(i.filename.replace("\\", "/"))
            if p.is_absolute() or ".." in p.parts or re.match(r"^[A-Za-z]:", i.filename) or (i.external_attr >> 16) & 0o170000 == 0o120000:
                raise HTTPException(400, f"unsafe path in zip: {i.filename}")
            if p.suffix.lower() not in PACK_EXTENSIONS:
                raise HTTPException(415, f"file type not allowed in a pack: {i.filename}")
        stem = re.sub(r"[^A-Za-z0-9_-]", "_", name[:-4])[:40] or "pack"
        dest = (settings.packs_dir / "uploads" / f"{stem}-{datetime.now(timezone.utc):%Y%m%d%H%M%S}").resolve()
        dest.mkdir(parents=True, exist_ok=False)
        for i in infos:
            target = (dest / PurePosixPath(i.filename.replace("\\", "/"))).resolve()
            if not target.is_relative_to(dest):
                shutil.rmtree(dest, ignore_errors=True)
                raise HTTPException(400, f"unsafe path in zip: {i.filename}")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(zf.read(i))
        roots = [p.parent for p in dest.rglob("manifest.json")]
        if len(roots) != 1:
            shutil.rmtree(dest, ignore_errors=True)
            raise HTTPException(400, "the zip must contain exactly one manifest.json")
        return roots[0]

    @app.post("/ingest")
    def ingest(pack_dir: str | None = Form(None), file: UploadFile | None = File(None)) -> dict:
        if (pack_dir is None) == (file is None):
            raise HTTPException(400, "send either pack_dir (a folder inside PACKS_DIR) or file (a pack .zip)")
        if pack_dir is not None:
            root = settings.packs_dir.resolve()
            p = Path(pack_dir)
            target = (p if p.is_absolute() else root / p).resolve()
            if not target.is_relative_to(root):
                raise HTTPException(400, "pack_dir must be inside the approved packs directory")
            if not (target / "manifest.json").is_file():
                raise HTTPException(404, "no pack (manifest.json) in that folder")
        else:
            target = _safe_extract(file)
        svc = request_service()
        try:
            rep = svc.hot_ingest(target)
        except (FileNotFoundError, ValueError) as exc:
            raise HTTPException(400, f"ingest failed: {exc}")
        finally:
            svc.store.close()
        return _summary(rep)

    # --------------------------------------------------------------- feed ---

    @app.get("/feed")
    def feed(as_of: date, limit: int = Query(200, ge=1, le=1000)) -> dict:
        with Store(settings.db_path) as s:
            rows = s.conn.execute("SELECT doc_id FROM documents WHERE pub_date IS NOT NULL AND pub_date <= ? "
                                  "ORDER BY pub_date DESC, pub_time DESC, doc_id LIMIT ?", (as_of.isoformat(), limit)).fetchall()
            later = s.conn.execute("SELECT COUNT(*) AS n FROM documents WHERE pub_date IS NULL OR pub_date > ?",
                                   (as_of.isoformat(),)).fetchone()["n"]
            visible = {r["doc_id"] for r in s.conn.execute(
                "SELECT doc_id FROM documents WHERE pub_date IS NOT NULL AND pub_date <= ?", (as_of.isoformat(),))}
            items = []
            for r in rows:
                d = s.get_document(r["doc_id"])
                m = d.meta
                rel = {t.value: [x.target_doc_id for x in d.relations if x.type == t and x.target_doc_id in visible]
                       for t in RelationType}
                incoming = [(src, t) for src, t, _ in s.incoming_relations(m.doc_id) if src in visible]
                items.append({
                    "doc_id": m.doc_id, "title": m.title, "pub_date": m.pub_date, "pub_time": m.pub_time,
                    "source_name": m.source_name, "source_type": m.source_type, "reliability_tier": m.reliability_tier,
                    "country": m.country, "sector": m.sector, "event_id": m.event_id, "format": m.format,
                    "badges": {
                        "tier": m.reliability_tier,
                        "damaged": sorted({f.kind.value for f in d.damage_flags if f.kind in DAMAGE_KINDS}),
                        "notices": sorted({f.kind.value for f in d.damage_flags if f.kind not in DAMAGE_KINDS}),
                        "injection": sorted({f.severity for f in d.injection_flags}),
                        "corrects": rel["corrects"] + rel["retracts"],
                        "corrected_by": [src for src, t in incoming if t in ("corrects", "retracts")],
                        "duplicate_of": rel["duplicate_of"], "near_duplicate_of": rel["near_duplicate_of"]}})
        return {"as_of": as_of, "count": len(items), "withheld_after_as_of": later, "items": items}

    return app


def __getattr__(name: str):
    """`ragnarok.api:app` for uvicorn, created lazily so importing the module loads nothing heavy."""
    if name == "app":
        globals()["app"] = create_app()
        return globals()["app"]
    raise AttributeError(name)

