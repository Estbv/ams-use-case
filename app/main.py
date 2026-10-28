"""Punto de entrada FastAPI de AMS Agentes.

Endpoints:
  GET  /health              sonda de salud
  GET  /                    interfaz web
  POST /cases               crear caso (multipart: logs + ticket)
  POST /cases/{id}/run      ejecutar flujo en segundo plano
  GET  /cases/{id}          estado del caso
  GET  /cases/{id}/events   SSE progreso en tiempo real
  POST /cases/{id}/review   revision humana
  GET  /cases/{id}/report   reporte HTML
  GET  /cases/{id}/export   expediente JSON
  GET  /cases               lista de casos
"""
from __future__ import annotations

import json
import queue
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.logging_config import setup_logging, get_logger
from app.llm.fake_client import FakeClient
from app.models.case import Case
from app.models.ticket import Ticket
from app.orchestrator.pipeline import Pipeline, ProgressEvent
from app.orchestrator.store import (
    case_dir,
    case_exists,
    load_case,
    save_case,
    save_raw_logs,
    logs_dir,
)
from app.report.html import generate_html_report, generate_json_export

setup_logging()
logger = get_logger(__name__)

MAX_FILE_SIZE = 50 * 1024 * 1024
LOG_EXTENSIONS = {".log", ".txt"}

_event_queues: dict[str, queue.Queue] = {}
_running_threads: dict[str, threading.Thread] = {}
_stop_requested: set[str] = set()
_client_override: Any = None

_WEB_DIR = Path(__file__).parent / "web"
_STATIC_DIR = _WEB_DIR / "static"
_TEMPLATES_DIR = _WEB_DIR / "templates"

app = FastAPI(
    title="AMS Agentes",
    description="Analisis de logs de incidentes con agentes LLM (Huawei MaaS / GLM).",
    version="0.7.0",
)

if _STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _err(code: int, error: str, detail: str = "") -> JSONResponse:
    return JSONResponse(status_code=code, content={"error": error, "detail": detail})


def _make_client() -> Any:
    if _client_override is not None:
        return _client_override
    if settings.LLM_MODE == "fake":
        return FakeClient(fixtures_dir="tests/fixtures/fake_responses")
    return None


def _new_case_id() -> str:
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    cid = f"CASE-{ts}"
    while case_exists(cid):
        ts = datetime.now().strftime("%Y%m%d-%H%M%S%f")
        cid = f"CASE-{ts}"
    return cid


def _sse(data: dict) -> str:
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


def _case_summary(case_id: str) -> dict | None:
    try:
        case = load_case(case_id)
    except Exception:
        return None
    return {
        "case_id": case.id,
        "status": case.status,
        "created_at": case.created_at.isoformat() if case.created_at else "",
        "ticket_id": case.ticket.ticket_id if case.ticket else "",
        "application": case.ticket.application if case.ticket else "",
        "severity": case.triage.severity if case.triage else "",
        "sources": case.sources,
        "evidence_count": len(case.evidence),
    }


# ---------------------------------------------------------------------------
# Background execution
# ---------------------------------------------------------------------------

def _run_pipeline_thread(case_id: str, log_files: list[Path], ticket: Ticket) -> None:
    q = _event_queues.setdefault(case_id, queue.Queue())
    try:
        client = _make_client()

        def cb(ev: ProgressEvent) -> None:
            if case_id not in _stop_requested:
                q.put({"phase": ev.phase, "status": ev.status, "message": ev.message, "percent": ev.percent})

        pipeline = Pipeline(client=client, progress_cb=cb)
        case = pipeline.run(case_id, log_files, ticket)
        if case_id in _stop_requested:
            case = load_case(case_id)
            case.status = "failed"
            case.set_phase("triage" if case.phases.get("triage") and case.phases["triage"].status == "running" else "preprocess", "failed", error="detenido por el usuario")
            save_case(case)
            q.put({"phase": "stopped", "status": "failed", "message": "Detenido por el usuario", "percent": 0.0})
        else:
            q.put({"phase": "done", "status": case.status, "message": "Flujo completado", "percent": 100.0})
    except Exception as exc:
        if case_id not in _stop_requested:
            logger.error("Pipeline error %s: %s", case_id, exc)
            try:
                case = load_case(case_id)
                case.status = "failed"
                save_case(case)
            except Exception:
                pass
            q.put({"phase": "error", "status": "failed", "message": str(exc), "percent": 0.0})
    finally:
        _running_threads.pop(case_id, None)
        _stop_requested.discard(case_id)


def _run_resume_failure_thread(case_id: str) -> None:
    q = _event_queues.setdefault(case_id, queue.Queue())
    try:
        client = _make_client()

        def cb(ev: ProgressEvent) -> None:
            if case_id not in _stop_requested:
                q.put({"phase": ev.phase, "status": ev.status, "message": ev.message, "percent": ev.percent})

        pipeline = Pipeline(client=client, progress_cb=cb)
        case = pipeline.resume_from_failure(case_id)
        if case_id in _stop_requested:
            case = load_case(case_id)
            case.status = "failed"
            save_case(case)
            q.put({"phase": "stopped", "status": "failed", "message": "Detenido por el usuario", "percent": 0.0})
        else:
            q.put({"phase": "done", "status": case.status, "message": "Flujo reanudado", "percent": 100.0})
    except Exception as exc:
        if case_id not in _stop_requested:
            logger.error("Resume error %s: %s", case_id, exc)
            try:
                case = load_case(case_id)
                case.status = "failed"
                save_case(case)
            except Exception:
                pass
            q.put({"phase": "error", "status": "failed", "message": str(exc), "percent": 0.0})
    finally:
        _running_threads.pop(case_id, None)
        _stop_requested.discard(case_id)


def _run_resume_thread(case_id: str, approved: bool, comment: str) -> None:
    q = _event_queues.setdefault(case_id, queue.Queue())
    try:
        client = _make_client()

        def cb(ev: ProgressEvent) -> None:
            q.put({"phase": ev.phase, "status": ev.status, "message": ev.message, "percent": ev.percent})

        pipeline = Pipeline(client=client, progress_cb=cb)
        case = pipeline.resume(case_id, approved=approved, comment=comment)
        q.put({"phase": "done", "status": case.status, "message": "Completado tras revision", "percent": 100.0})
    except Exception as exc:
        logger.error("Resume error %s: %s", case_id, exc)
        q.put({"phase": "error", "status": "failed", "message": str(exc), "percent": 0.0})
    finally:
        _running_threads.pop(case_id, None)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/")
def index() -> HTMLResponse:
    p = _TEMPLATES_DIR / "index.html"
    if p.exists():
        return HTMLResponse(p.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>AMS Agentes</h1><p>Interfaz web no encontrada.</p>")


@app.post("/cases")
async def create_case(
    files: list[UploadFile] = File(...),
    ticket_file: UploadFile | None = File(None),
    ticket_id: str | None = Form(None),
    application: str | None = Form(None),
    description: str | None = Form(None),
    recent_changes: str | None = Form(None),
    environment: str | None = Form(None),
    business_rules: str | None = Form(None),
):
    if not files:
        return _err(400, "faltan archivos", "sube al menos un archivo de log (.log o .txt)")

    # Parse ticket
    ticket: Ticket
    if ticket_file is not None:
        raw = await ticket_file.read()
        try:
            tdata = json.loads(raw.decode("utf-8"))
        except Exception as exc:
            return _err(400, "ticket JSON invalido", str(exc))
        try:
            ticket = Ticket.model_validate(tdata)
        except Exception as exc:
            return _err(400, "ticket invalido", str(exc))
    else:
        if not ticket_id or not application:
            return _err(400, "ticket incompleto", "provee ticket_file o ticket_id+application")
        ticket = Ticket(
            ticket_id=ticket_id,
            application=application,
            description=description or "",
            recent_changes=recent_changes,
            environment=environment,
            business_rules=business_rules,
        )

    # Validate and save log files
    case_id = _new_case_id()
    cdir = case_dir(case_id)
    ldir = logs_dir(case_id)
    ldir.mkdir(parents=True, exist_ok=True)

    saved_logs: list[Path] = []
    for f in files:
        content = await f.read()
        ext = Path(f.filename or "").suffix.lower()
        if ext not in LOG_EXTENSIONS:
            return _err(400, "extension no permitida", f"{f.filename}: usa .log o .txt")
        if len(content) > MAX_FILE_SIZE:
            return _err(413, "archivo demasiado grande", f"{f.filename}: max {MAX_FILE_SIZE} bytes")
        dst = ldir / (f.filename or "unnamed.log")
        dst.write_bytes(content)
        saved_logs.append(dst)

    # Create case
    case = Case(id=case_id, ticket=ticket, status="created")
    case.init_phases()
    save_case(case)

    return JSONResponse(status_code=201, content={"case_id": case_id, "status": "created", "log_count": len(saved_logs)})


@app.post("/cases/{case_id}/run")
def run_case(case_id: str):
    if not case_exists(case_id):
        return _err(404, "caso no encontrado", case_id)
    if case_id in _running_threads:
        return _err(409, "ya en ejecucion", case_id)

    try:
        case = load_case(case_id)
    except Exception as exc:
        return _err(500, "error al cargar", str(exc))

    if case.status not in ("created", "failed"):
        return _err(409, "estado no permite run", f"estado actual: {case.status}")

    if not case.ticket:
        return _err(400, "sin ticket", "el caso no tiene ticket")

    # Detectar si se puede reanudar (algunas fases OK y la primera no-OK es triage o posterior)
    _PHASES = ["preprocess", "ingest", "triage", "rca", "resolution", "communication"]
    ok_phases = [name for name in _PHASES if case.phases.get(name) and case.phases[name].status == "ok"]
    can_resume = (
        case.status == "failed"
        and "preprocess" in ok_phases
        and "ingest" in ok_phases
    )

    _event_queues[case_id] = queue.Queue()

    if can_resume:
        t = threading.Thread(target=_run_resume_failure_thread, args=(case_id,), daemon=True)
        _running_threads[case_id] = t
        t.start()
        return JSONResponse(status_code=202, content={"case_id": case_id, "status": "resuming", "resumed_from": ok_phases[-1]})

    ldir = logs_dir(case_id)
    log_files = sorted(ldir.glob("*.log")) + sorted(ldir.glob("*.txt"))
    if not log_files:
        return _err(400, "sin logs", "no hay archivos de log para este caso")

    t = threading.Thread(target=_run_pipeline_thread, args=(case_id, log_files, case.ticket), daemon=True)
    _running_threads[case_id] = t
    t.start()

    return JSONResponse(status_code=202, content={"case_id": case_id, "status": "running"})


@app.post("/cases/{case_id}/stop")
def stop_case(case_id: str):
    if not case_exists(case_id):
        return _err(404, "caso no encontrado", case_id)
    if case_id not in _running_threads:
        return _err(409, "no esta en ejecucion", case_id)

    _stop_requested.add(case_id)
    _running_threads.pop(case_id, None)

    try:
        case = load_case(case_id)
        case.status = "failed"
        for name, ph in case.phases.items():
            if ph.status == "running":
                ph.status = "failed"
                ph.error = "detenido por el usuario"
        save_case(case)
    except Exception:
        pass

    return JSONResponse(content={"case_id": case_id, "status": "stopped"})


@app.get("/cases/{case_id}")
def get_case(case_id: str):
    if not case_exists(case_id):
        return _err(404, "caso no encontrado", case_id)
    try:
        case = load_case(case_id)
    except Exception as exc:
        return _err(500, "error al cargar", str(exc))

    result = {
        "case_id": case.id,
        "status": case.status,
        "created_at": case.created_at.isoformat() if case.created_at else "",
        "ticket": case.ticket.model_dump(mode="json") if case.ticket else None,
        "sources": case.sources,
        "evidence_count": len(case.evidence),
        "phases": {name: ph.model_dump(mode="json") for name, ph in case.phases.items()},
        "severity": case.triage.severity if case.triage else "",
        "needs_review": case.status == "waiting_review",
        "has_report": case.status in ("completed", "degraded"),
    }
    if case.rca and case.rca.hypotheses:
        result["top_hypothesis"] = {
            "title": case.rca.hypotheses[0].title,
            "confidence": case.rca.hypotheses[0].confidence,
            "root_cause": case.rca.most_likely_root_cause,
        }
    return JSONResponse(content=result)


@app.get("/cases/{case_id}/events")
def case_events(case_id: str):
    if not case_exists(case_id):
        return _err(404, "caso no encontrado", case_id)

    def event_stream():
        q = _event_queues.get(case_id)
        if q is None:
            try:
                case = load_case(case_id)
                yield _sse({"phase": "done", "status": case.status, "message": "sin eventos", "percent": 100.0 if case.status == "completed" else 0.0})
            except Exception:
                yield _sse({"phase": "error", "status": "failed", "message": "no se pudo cargar el caso", "percent": 0.0})
            return

        while True:
            try:
                ev = q.get(timeout=30)
                yield _sse(ev)
                if ev.get("phase") in ("done", "error"):
                    break
            except queue.Empty:
                yield ": keepalive\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "Connection": "keep-alive"})


@app.post("/cases/{case_id}/review")
def review_case(case_id: str, approved: bool = Form(...), comment: str = Form("")):
    if not case_exists(case_id):
        return _err(404, "caso no encontrado", case_id)
    try:
        case = load_case(case_id)
    except Exception as exc:
        return _err(500, "error al cargar", str(exc))

    if case.status != "waiting_review":
        return _err(409, "no espera revision", f"estado actual: {case.status}")

    _event_queues[case_id] = queue.Queue()
    t = threading.Thread(target=_run_resume_thread, args=(case_id, approved, comment), daemon=True)
    _running_threads[case_id] = t
    t.start()

    return JSONResponse(status_code=202, content={"case_id": case_id, "status": "resuming"})


@app.get("/cases/{case_id}/report")
def case_report(case_id: str):
    if not case_exists(case_id):
        return _err(404, "caso no encontrado", case_id)
    try:
        case = load_case(case_id)
    except Exception as exc:
        return _err(500, "error al cargar", str(exc))
    html = generate_html_report(case)
    return HTMLResponse(content=html)


@app.get("/cases/{case_id}/export")
def case_export(case_id: str):
    if not case_exists(case_id):
        return _err(404, "caso no encontrado", case_id)
    try:
        case = load_case(case_id)
    except Exception as exc:
        return _err(500, "error al cargar", str(exc))
    data = generate_json_export(case)
    return JSONResponse(content=json.loads(data))


@app.get("/cases")
def list_cases():
    root = Path(settings.CASES_DIR)
    if not root.exists():
        return JSONResponse(content={"cases": []})
    cases = []
    for d in sorted(root.iterdir(), reverse=True):
        if not d.is_dir():
            continue
        summary = _case_summary(d.name)
        if summary:
            cases.append(summary)
    return JSONResponse(content={"cases": cases})
