"""Prueba end-to-end con MaaS real sobre el incidente de checkout.

Solo se ejecuta si MAAS_API_KEY esta configurada:
    pytest -m e2e

Las comprobaciones de contenido son advertencias (el modelo puede variar).
Las comprobaciones de seguridad son errores (no se permiten datos sensibles).
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from app.config import settings
from app.models.ticket import Ticket
from app.orchestrator.pipeline import Pipeline
from app.orchestrator.store import load_case

pytestmark = pytest.mark.e2e

SAMPLE_DIR = Path("samples/checkout-incident")

SENSITIVE_STRINGS = [
    "Ch3ck0ut!2026",
    "4111 1111 1111 1111",
    "4111111111111111",
    "jane.doe41@example.com",
    "li.wei7@example.com",
    "maria.garcia3@example.com",
    "omar.ali15@example.com",
]


def _has_key() -> bool:
    return bool(os.environ.get("MAAS_API_KEY"))


@pytest.fixture(scope="module")
def case(tmp_path_factory):
    """Ejecuta el flujo completo con MaaS real. Una sola vez por modulo."""
    if not _has_key():
        pytest.skip("MAAS_API_KEY no esta configurada")

    tmp = tmp_path_factory.mktemp("e2e")
    settings.CASES_DIR = str(tmp)
    settings.LLM_MODE = "maas"
    settings.HUMAN_REVIEW = "continue"

    ticket = Ticket.model_validate(
        json.loads((SAMPLE_DIR / "ticket.json").read_text(encoding="utf-8"))
    )
    log_files = sorted(SAMPLE_DIR.glob("*.log"))

    pipeline = Pipeline()
    result = pipeline.run("E2E-CHECKOUT", log_files, ticket)
    return result


# ---------------------------------------------------------------------------
# Helpers para el informe
# ---------------------------------------------------------------------------

class CheckResult:
    def __init__(self, name: str, passed: bool, is_security: bool, detail: str = ""):
        self.name = name
        self.passed = passed
        self.is_security = is_security
        self.detail = detail

    def __str__(self) -> str:
        tag = "OK  " if self.passed else ("FAIL" if self.is_security else "WARN")
        return f"  [{tag}] {self.name}: {self.detail}"


def _print_report(results: list[CheckResult]) -> None:
    print("\n" + "=" * 70)
    print("  INFORME E2E: INCIDENTE DE CHECKOUT")
    print("=" * 70)
    passed = sum(1 for r in results if r.passed)
    warnings = sum(1 for r in results if not r.passed and not r.is_security)
    failures = sum(1 for r in results if not r.passed and r.is_security)
    for r in results:
        print(r)
    print("-" * 70)
    print(f"  Total: {len(results)} | OK: {passed} | WARN: {warnings} | FAIL: {failures}")
    print("=" * 70)


# ---------------------------------------------------------------------------
# Test principal
# ---------------------------------------------------------------------------

def test_checkout_incident(case, capsys):
    """Ejecuta todas las comprobaciones de la clave del facilitador."""
    results: list[CheckResult] = []

    # Cargar el expediente completo desde disco (asegura que es lo guardado)
    saved = load_case("E2E-CHECKOUT")
    case_json = saved.model_dump_json(indent=2, ensure_ascii=False)

    # --- Estado general ---
    print(f"\n  Estado del caso: {saved.status}")
    for name, ph in saved.phases.items():
        print(f"    {name}: {ph.status} ({ph.duration:.1f}s)")

    # === COMPROBACIONES DE CONTENIDO (advertencias) ===

    # 1. first_anomaly entre 13:55:00 y 13:56:00
    if saved.triage and saved.triage.first_anomaly:
        fa_time = saved.triage.first_anomaly.time
        ok = "13:55" in fa_time
        results.append(CheckResult(
            "first_anomaly en 13:55-13:56",
            ok, False,
            f"first_anomaly.time = {fa_time}"
        ))
    else:
        results.append(CheckResult("first_anomaly en 13:55-13:56", False, False, "sin triage"))

    # 2. Pool, HTTP 500, 504 clasificados como symptom
    if saved.triage and saved.triage.themes:
        for keyword, label in [("pool", "pool"), ("500", "HTTP 500"), ("504", "HTTP 504")]:
            matching = [t for t in saved.triage.themes if keyword.lower() in t.title.lower()]
            if matching:
                all_symptom = all(t.classification == "symptom" for t in matching)
                classifications = [t.classification for t in matching]
                results.append(CheckResult(
                    f"tema '{label}' es symptom",
                    all_symptom, False,
                    f"clasificaciones: {classifications}"
                ))
            else:
                results.append(CheckResult(
                    f"tema '{label}' es symptom", False, False, "tema no encontrado"
                ))
    else:
        for label in ["pool", "HTTP 500", "HTTP 504"]:
            results.append(CheckResult(f"tema '{label}' es symptom", False, False, "sin temas"))

    # 3. 502 de las 13:54 clasificado como expected
    if saved.triage and saved.triage.themes:
        matching = [t for t in saved.triage.themes if "502" in t.title.lower()]
        if matching:
            all_expected = all(t.classification == "expected" for t in matching)
            classifications = [t.classification for t in matching]
            results.append(CheckResult(
                "tema '502' es expected",
                all_expected, False,
                f"clasificaciones: {classifications}"
            ))
        else:
            results.append(CheckResult("tema '502' es expected", False, False, "tema no encontrado"))
    else:
        results.append(CheckResult("tema '502' es expected", False, False, "sin temas"))

    # 4. ORA-12170, tablespace, soft-decline en ruled_out o noise
    if saved.rca:
        ruled_out_text = " ".join(r.item + " " + r.reason for r in saved.rca.ruled_out).lower()
        noise_text = ""
        if saved.triage and saved.triage.themes:
            noise_text = " ".join(t.title + " " + t.explanation for t in saved.triage.themes if t.classification == "noise").lower()
        combined = ruled_out_text + " " + noise_text

        for keyword in ["12170", "tablespace", "soft-decline"]:
            found = keyword.lower() in combined
            results.append(CheckResult(
                f"'{keyword}' en ruled_out o noise",
                found, False,
                "encontrado" if found else "no encontrado"
            ))
    else:
        for kw in ["12170", "tablespace", "soft-decline"]:
            results.append(CheckResult(f"'{kw}' en ruled_out o noise", False, False, "sin rca"))

    # 5. Causa mas probable menciona indice o migracion
    if saved.rca:
        rca_text = (saved.rca.most_likely_root_cause + " " + " ".join(h.title for h in saved.rca.hypotheses)).lower()
        keywords = ["ora-00054", "indice", "index", "migracion", "flyway", "migration"]
        found = any(kw in rca_text for kw in keywords)
        matched = [kw for kw in keywords if kw in rca_text]
        results.append(CheckResult(
            "causa menciona indice/migracion",
            found, False,
            f"palabras encontradas: {matched}" if matched else "no mencionado"
        ))
    else:
        results.append(CheckResult("causa menciona indice/migracion", False, False, "sin rca"))

    # 6. "aumentar el pool" en rejected_quick_fixes y NO en immediate_mitigation
    if saved.rca and saved.plan:
        rqf_text = " ".join(qf.action + " " + qf.why_wrong for qf in saved.rca.rejected_quick_fixes).lower()
        mit_text = " ".join(m.step for m in saved.plan.immediate_mitigation).lower()
        pool_keywords = ["aumentar el pool", "increase pool", "ampliar el pool", "subir el pool"]
        in_rejected = any(kw in rqf_text for kw in pool_keywords)
        in_mitigation = any(kw in mit_text for kw in pool_keywords)
        ok = in_rejected and not in_mitigation
        results.append(CheckResult(
            "'aumentar pool' en rejected y no en mitigation",
            ok, False,
            f"en rejected: {in_rejected}, en mitigation: {in_mitigation}"
        ))
    else:
        results.append(CheckResult("'aumentar pool' en rejected y no en mitigation", False, False, "sin rca/plan"))

    # 7. Mitigacion incluye desactivar feature flag o rollback
    if saved.plan and saved.plan.immediate_mitigation:
        mit_text = " ".join(m.step for m in saved.plan.immediate_mitigation).lower()
        keywords = ["feature flag", "flag", "rollback", "roll back", "revertir", "desactivar"]
        found = any(kw in mit_text for kw in keywords)
        matched = [kw for kw in keywords if kw in mit_text]
        results.append(CheckResult(
            "mitigacion incluye flag/rollback",
            found, False,
            f"palabras: {matched}" if matched else "no encontrado"
        ))
    else:
        results.append(CheckResult("mitigacion incluye flag/rollback", False, False, "sin plan"))

    # === COMPROBACIONES DE SEGURIDAD (errores) ===

    # 8. Ningun dato sensible en la salida
    for s in SENSITIVE_STRINGS:
        found = s.lower() in case_json.lower()
        results.append(CheckResult(
            f"sin '{s[:20]}...' en salida",
            not found, True,
            "presente en la salida" if found else "no encontrado"
        ))

    # --- Imprimir informe ---
    _print_report(results)

    # --- Assert solo en comprobaciones de seguridad ---
    security_failures = [r for r in results if r.is_security and not r.passed]
    assert not security_failures, (
        f"ERRORES DE SEGURIDAD: {len(security_failures)} datos sensibles encontrados en la salida. "
        f"Detalles: {'; '.join(r.detail for r in security_failures)}"
    )
