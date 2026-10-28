"""Orquestador: flujo secuencial en codigo con paralelismo solo en la ingesta.

Fase 0  Preproceso local
Fase 1  Ingesta en paralelo + merge
Fase 2  Triage
Fase 3  Causa Raiz (posible revision humana)
Fase 4a Resolucion
Fase 4b Comunicacion
"""
from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from app.agents.communication import CommunicationAgent
from app.agents.ingest import IngestAgent
from app.agents.rca import RcaAgent
from app.agents.resolution import ResolutionAgent
from app.agents.triage import TriageAgent
from app.config import settings, validate_llm_settings
from app.logging_config import bind_context, get_logger
from app.models.case import AuditRecord, Case
from app.models.ticket import Ticket
from app.orchestrator.store import save_case, save_raw_logs
from app.preprocess.digest import build_digest
from app.preprocess.ids import assign_ids, known_ids
from app.preprocess.masking import load_masking_rules, mask_lines
from app.preprocess.merge import merge_ingest_results
from app.preprocess.parser import parse_file
from app.preprocess.signatures import build_signatures

logger = get_logger(__name__)

PHASES = ["preprocess", "ingest", "triage", "rca", "resolution", "communication"]


@dataclass
class ProgressEvent:
    phase: str
    status: str
    message: str
    percent: float


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

class Pipeline:
    def __init__(
        self,
        client: Any = None,
        progress_cb: Callable[[ProgressEvent], None] | None = None,
    ) -> None:
        self._client = client
        self._progress_cb = progress_cb or _default_progress

    def _emit(self, phase: str, status: str, message: str, percent: float) -> None:
        self._progress_cb(ProgressEvent(phase, status, message, percent))

    # -- run ----------------------------------------------------------------

    def run(
        self,
        case_id: str,
        log_files: list[Path],
        ticket: Ticket,
    ) -> Case:
        errors = validate_llm_settings()
        if errors:
            raise RuntimeError("Configuracion LLM invalida: " + "; ".join(errors))

        case = Case(id=case_id, ticket=ticket, status="running")
        case.init_phases()
        save_raw_logs(case_id, log_files)
        save_case(case)

        with bind_context(case_id, "preprocess"):
            self._fase0_preprocess(case, log_files)
        with bind_context(case_id, "ingest"):
            self._fase1_ingest(case)
        with bind_context(case_id, "triage"):
            self._fase2_triage(case)
        if case.status == "failed":
            save_case(case)
            return case
        with bind_context(case_id, "rca"):
            self._fase3_rca(case)
        if case.status in ("failed", "waiting_review"):
            save_case(case)
            return case
        with bind_context(case_id, "resolution"):
            self._fase4a_resolution(case)
        if case.status == "failed":
            save_case(case)
            return case
        with bind_context(case_id, "communication"):
            self._fase4b_communication(case)

        case.status = "completed"
        save_case(case)
        self._emit("done", "ok", "Flujo completado", 100.0)
        return case

    # -- resume -------------------------------------------------------------

    def resume(self, case_id: str, approved: bool, comment: str = "") -> Case:
        from app.orchestrator.store import load_case

        case = load_case(case_id)
        if case.status != "waiting_review":
            raise RuntimeError(f"el caso no esta en waiting_review (estado: {case.status})")

        if comment:
            existing = case.ticket.business_rules or ""
            case.ticket.business_rules = f"{existing}\n[Revision humana]: {comment}".strip()

        if not approved:
            case.status = "failed"
            case.set_phase("rca", "failed", error="revision humana rechazo la hipotesis")
            save_case(case)
            return case

        case.status = "running"
        with bind_context(case_id, "resolution"):
            self._fase4a_resolution(case)
        if case.status == "failed":
            save_case(case)
            return case
        with bind_context(case_id, "communication"):
            self._fase4b_communication(case)

        case.status = "completed"
        save_case(case)
        self._emit("done", "ok", "Flujo completado tras revision", 100.0)
        return case

    # -- resume_from_failure -------------------------------------------------

    _PHASE_ORDER = ["preprocess", "ingest", "triage", "rca", "resolution", "communication"]

    def resume_from_failure(self, case_id: str) -> Case:
        """Reanuda un caso fallido desde la ultima fase exitosa.

        Si preprocess o ingest fallaron, reinicia desde cero (necesita logs).
        Si triage o posterior fallaron, reanuda desde ahi sin repetir lo anterior.
        """
        from app.orchestrator.store import load_case, logs_dir

        case = load_case(case_id)

        # Encontrar la primera fase que no esta OK
        first_non_ok = None
        for name in self._PHASE_ORDER:
            ph = case.phases.get(name)
            if not ph or ph.status != "ok":
                first_non_ok = name
                break

        if first_non_ok is None:
            case.status = "completed"
            save_case(case)
            return case

        # Si cayo en preprocess o ingest, hay que reiniciar (ingest necesita _source_data)
        if first_non_ok in ("preprocess", "ingest"):
            ldir = logs_dir(case_id)
            log_files = sorted(ldir.glob("*.log")) + sorted(ldir.glob("*.txt"))
            if not log_files:
                raise RuntimeError("no hay logs para reiniciar desde cero")
            return self.run(case_id, log_files, case.ticket)

        # Reanudar desde la primera fase no-OK (triage o posterior)
        case.status = "running"
        save_case(case)

        remaining = self._PHASE_ORDER[self._PHASE_ORDER.index(first_non_ok):]
        for phase_name in remaining:
            if case.status in ("failed", "waiting_review"):
                save_case(case)
                return case
            with bind_context(case_id, phase_name):
                if phase_name == "triage":
                    self._fase2_triage(case)
                elif phase_name == "rca":
                    self._fase3_rca(case)
                elif phase_name == "resolution":
                    self._fase4a_resolution(case)
                elif phase_name == "communication":
                    self._fase4b_communication(case)

        case.status = "completed"
        save_case(case)
        self._emit("done", "ok", "Flujo completado (reanudado)", 100.0)
        return case

    # -- Fase 0: Preproceso -------------------------------------------------

    def _fase0_preprocess(self, case: Case, log_files: list[Path]) -> None:
        self._emit("preprocess", "running", "Parseo, enmascarado y firmas", 5.0)
        case.set_phase("preprocess", "running")
        t0 = time.time()

        custom_rules = load_masking_rules()
        all_signatures = []
        source_data: dict[str, dict] = {}

        for f in log_files:
            source = _source_name(f.name)
            lines = parse_file(f, source=source)
            masked, counters = mask_lines(lines, custom_rules=custom_rules)
            sigs = build_signatures(masked, source)
            all_signatures.extend(sigs)
            source_data[source] = {
                "file": f.name,
                "lines": len(lines),
                "signatures": sigs,
                "masked_lines": masked,
            }
            case.masking_stats = {k: case.masking_stats.get(k, 0) + v for k, v in counters.items()}

        all_signatures = assign_ids(all_signatures)
        case.sources = sorted(source_data.keys())
        case.evidence = [s.__dict__ for s in all_signatures]
        case._source_data = source_data  # type: ignore[attr-defined]
        case._known_ids = known_ids(all_signatures)  # type: ignore[attr-defined]

        case.set_phase("preprocess", "ok", duration=time.time() - t0)
        save_case(case)
        self._emit("preprocess", "ok", f"{len(all_signatures)} firmas, {len(case.sources)} fuentes", 15.0)

    # -- Fase 1: Ingesta en paralelo + merge --------------------------------

    def _fase1_ingest(self, case: Case) -> None:
        self._emit("ingest", "running", "Ingesta por fuente en paralelo", 15.0)
        case.set_phase("ingest", "running")
        t0 = time.time()

        source_data: dict[str, dict] = getattr(case, "_source_data", {})
        known = getattr(case, "_known_ids", set())
        results: list[dict] = []
        failed_sources: list[str] = []

        def _run_ingest(source: str, data: dict) -> tuple[str, Any]:
            sigs = data["signatures"]
            digest_text = build_digest(sigs, source)
            agent = IngestAgent(client=self._client)
            result = agent.run(
                case,
                source_name=source,
                source_file=data["file"],
                total_lines=data["lines"],
                digest_text=digest_text,
            )
            return source, result

        with ThreadPoolExecutor(max_workers=settings.INGEST_CONCURRENCY) as pool:
            futures = {
                pool.submit(_run_ingest, src, data): src
                for src, data in source_data.items()
            }
            for fut in as_completed(futures):
                source = futures[fut]
                try:
                    src, result = fut.result()
                    if result.status == "ok" and result.data:
                        results.append(result.data.model_dump())
                        case.add_audit(_audit_from(result, "ingest", src))
                    elif result.status == "degraded":
                        results.append({"source": src, "degraded": True, "raw": result.raw_text})
                        case.add_audit(_audit_from(result, "ingest", src))
                        logger.warning("Ingesta degradada para %s", src)
                    else:
                        failed_sources.append(source)
                        case.add_audit(_audit_from(result, "ingest", src))
                except Exception as exc:
                    failed_sources.append(source)
                    logger.error("Ingesta fallo para %s: %s", source, exc)

        if failed_sources and not results:
            case.status = "failed"
            case.set_phase("ingest", "failed", error=f"todas las fuentes fallaron: {failed_sources}")
            self._emit("ingest", "failed", f"Fallo: {failed_sources}", 15.0)
            return

        merged = merge_ingest_results(results, known_ids=known or None)
        case.evidence = merged.evidence if merged.evidence else case.evidence
        case.trends = merged.trends
        if merged.warnings:
            logger.warning("Merge: %s", merged.warnings)

        phase_status = "degraded" if failed_sources else "ok"
        case.set_phase("ingest", phase_status, duration=time.time() - t0)
        save_case(case)
        self._emit("ingest", phase_status, f"{len(results)} fuentes ok", 30.0)

    # -- Fase 2: Triage -----------------------------------------------------

    def _fase2_triage(self, case: Case) -> None:
        self._emit("triage", "running", "Triage del incidente", 30.0)
        case.set_phase("triage", "running")
        t0 = time.time()

        agent = TriageAgent(client=self._client)
        result = agent.run(case)

        if result.status == "ok" and result.data:
            case.triage = result.data
            case.set_phase("triage", "ok", duration=time.time() - t0, tokens=result.audit.get("tokens", {}))
        elif result.status == "degraded":
            case.set_phase("triage", "degraded", duration=time.time() - t0, error="; ".join(result.errors))
        else:
            case.status = "failed"
            case.set_phase("triage", "failed", error="; ".join(result.errors))

        case.add_audit(_audit_from(result, "triage"))
        save_case(case)
        self._emit("triage", case.phases["triage"].status, "Triage completado", 45.0)

    # -- Fase 3: Causa Raiz -------------------------------------------------

    def _fase3_rca(self, case: Case) -> None:
        self._emit("rca", "running", "Causa Raiz (puede tardar 1-3 min)", 45.0)
        case.set_phase("rca", "running")
        t0 = time.time()

        agent = RcaAgent(client=self._client)
        result = agent.run(case)

        if result.status == "ok" and result.data:
            case.rca = result.data
            case.set_phase("rca", "ok", duration=time.time() - t0, tokens=result.audit.get("tokens", {}))
            if result.data.needs_human_review and settings.HUMAN_REVIEW == "pause":
                case.status = "waiting_review"
                case.set_phase("rca", "ok", error="esperando revision humana")
                case.add_audit(_audit_from(result, "rca"))
                save_case(case)
                self._emit("rca", "waiting", "Revision humana requerida", 45.0)
                return
        elif result.status == "degraded":
            case.set_phase("rca", "degraded", duration=time.time() - t0, error="; ".join(result.errors))
        else:
            case.status = "failed"
            case.set_phase("rca", "failed", error="; ".join(result.errors))

        case.add_audit(_audit_from(result, "rca"))
        save_case(case)
        self._emit("rca", case.phases["rca"].status, "Causa raiz completada", 60.0)

    # -- Fase 4a: Resolucion ------------------------------------------------

    def _fase4a_resolution(self, case: Case) -> None:
        self._emit("resolution", "running", "Plan de accion", 60.0)
        case.set_phase("resolution", "running")
        t0 = time.time()

        agent = ResolutionAgent(client=self._client)
        result = agent.run(case)

        if result.status == "ok" and result.data:
            case.plan = result.data
            case.set_phase("resolution", "ok", duration=time.time() - t0, tokens=result.audit.get("tokens", {}))
        elif result.status == "degraded":
            case.set_phase("resolution", "degraded", duration=time.time() - t0, error="; ".join(result.errors))
        else:
            case.status = "failed"
            case.set_phase("resolution", "failed", error="; ".join(result.errors))

        case.add_audit(_audit_from(result, "resolution"))
        save_case(case)
        self._emit("resolution", case.phases["resolution"].status, "Resolucion completada", 80.0)

    # -- Fase 4b: Comunicacion ---------------------------------------------

    def _fase4b_communication(self, case: Case) -> None:
        self._emit("communication", "running", "Redactando comunicaciones", 80.0)
        case.set_phase("communication", "running")
        t0 = time.time()

        agent = CommunicationAgent(client=self._client)
        result = agent.run(case)

        if result.status == "ok" and result.data:
            case.communications = result.data
            case.set_phase("communication", "ok", duration=time.time() - t0, tokens=result.audit.get("tokens", {}))
        elif result.status == "degraded":
            case.set_phase("communication", "degraded", duration=time.time() - t0, error="; ".join(result.errors))
        else:
            case.set_phase("communication", "failed", error="; ".join(result.errors))

        case.add_audit(_audit_from(result, "communication"))
        save_case(case)
        self._emit("communication", case.phases["communication"].status, "Comunicacion completada", 95.0)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _source_name(filename: str) -> str:
    name = Path(filename).name
    return "nginx" if name.startswith("nginx") else Path(filename).stem


def _audit_from(result: Any, phase: str, source: str = "") -> AuditRecord:
    return AuditRecord(
        agent=result.audit.get("agent", ""),
        phase=phase,
        messages_sent=result.audit.get("messages_sent", []),
        responses=result.audit.get("responses", []),
        attempts=result.audit.get("attempts", 0),
        tokens=result.audit.get("tokens", {}),
        duration=result.audit.get("duration", 0.0),
        warnings=result.audit.get("warnings", []),
        timestamp=datetime.now().isoformat(),
    )


def _default_progress(ev: ProgressEvent) -> None:
    logger.info("[%s] %s: %s (%.0f%%)", ev.phase, ev.status, ev.message, ev.percent)
