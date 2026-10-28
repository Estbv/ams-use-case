"""Pruebas del preproceso (seccion 4.0 de la especificacion)."""
from __future__ import annotations

from pathlib import Path

import pytest

from app.preprocess.parser import parse_file, parse_text
from app.preprocess.masking import load_masking_rules, mask_lines
from app.preprocess.signatures import build_signatures
from app.preprocess.ids import assign_ids
from app.preprocess.digest import build_digest

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


def _source_name(filename: str) -> str:
    name = Path(filename).name
    return "nginx" if name.startswith("nginx") else Path(filename).stem


def run_pipeline(sample_dir: Path):
    """Ejecuta el pipeline completo y devuelve (firmas_con_ids, datos_por_fuente)."""
    custom_rules = load_masking_rules()
    log_files = sorted(sample_dir.glob("*.log"))

    files_by_source: dict[str, list[Path]] = {}
    for f in log_files:
        src = _source_name(f.name)
        files_by_source.setdefault(src, []).append(f)

    all_signatures = []
    source_data = []
    for src in sorted(files_by_source):
        all_lines = []
        for f in files_by_source[src]:
            all_lines.extend(parse_file(f, source=src))
        masked_lines, counters = mask_lines(all_lines, custom_rules=custom_rules)
        sigs = build_signatures(masked_lines, src)
        all_signatures.extend(sigs)
        source_data.append((src, sigs, masked_lines))

    all_signatures = assign_ids(all_signatures)
    return all_signatures, source_data


# ---------------------------------------------------------------------------
# 1. Datos sensibles no aparecen en ninguna salida
# ---------------------------------------------------------------------------

def test_no_sensitive_data_in_output():
    all_signatures, source_data = run_pipeline(SAMPLE_DIR)

    all_text: list[str] = []
    for sig in all_signatures:
        all_text.append(sig.example)
        all_text.extend(sig.example_stack)

    for src, sigs, masked_lines in source_data:
        all_text.append(build_digest(sigs, src))
        for line in masked_lines:
            all_text.append(line.message)
            all_text.extend(line.stack_trace)

    for secret in SENSITIVE_STRINGS:
        for text in all_text:
            assert secret not in text, f"Dato sensible en salida: {secret!r}"


# ---------------------------------------------------------------------------
# 2. Stack trace unido a la linea de ERROR
# ---------------------------------------------------------------------------

def test_stack_trace_joined_to_error():
    lines = parse_file(SAMPLE_DIR / "checkout-service.log")
    error_lines = [
        l for l in lines
        if l.level == "ERROR" and "Checkout failed" in l.message
    ]
    assert len(error_lines) >= 1, "debe haber lineas ERROR de Checkout failed"
    # El primer ERROR tiene stack trace
    assert len(error_lines[0].stack_trace) >= 3, (
        f"el stack trace debe tener >=3 lineas, tiene {len(error_lines[0].stack_trace)}"
    )
    stack_text = "\n".join(error_lines[0].stack_trace)
    assert "DataAccessResourceFailureException" in stack_text
    assert "Caused by" in stack_text


# ---------------------------------------------------------------------------
# 3. Los 3 errores en una sola firma con count = 3
# ---------------------------------------------------------------------------

def test_three_checkout_errors_one_signature():
    lines = parse_file(SAMPLE_DIR / "checkout-service.log", source="checkout-service")
    masked, _ = mask_lines(lines)
    sigs = build_signatures(masked, "checkout-service")

    matching = [
        s for s in sigs
        if "Checkout failed" in s.template
        and "Unable to acquire JDBC Connection" in s.template
    ]
    assert len(matching) == 1, f"debe haber 1 firma, hay {len(matching)}"
    assert matching[0].count == 3, f"count debe ser 3, es {matching[0].count}"


# ---------------------------------------------------------------------------
# 4. IDs unicos, consecutivos y en orden cronologico
# ---------------------------------------------------------------------------

def test_ids_unique_consecutive_chronological():
    all_signatures, _ = run_pipeline(SAMPLE_DIR)
    ids = [s.evidence_id for s in all_signatures]

    # Unicos
    assert len(ids) == len(set(ids)), "IDs duplicados"

    # Consecutivos: E001, E002, ...
    expected = [f"E{i:03d}" for i in range(1, len(ids) + 1)]
    assert ids == expected, "IDs no consecutivos"

    # Orden cronologico (no decreciente)
    for i in range(len(all_signatures) - 1):
        curr = all_signatures[i].time_first
        nxt = all_signatures[i + 1].time_first
        if curr is not None and nxt is not None:
            assert curr <= nxt, f"orden cronologico roto en posicion {i}"


# ---------------------------------------------------------------------------
# 5. Archivo vacio y sin marcas de tiempo no provocan errores
# ---------------------------------------------------------------------------

def test_empty_file_no_errors():
    assert parse_text("") == []
    assert parse_text("\n\n\n") == []


def test_no_timestamp_file_no_errors(tmp_path):
    log_file = tmp_path / "no-ts.log"
    log_file.write_text(
        "linea sin timestamp\notra linea sin hora\n",
        encoding="utf-8",
    )
    lines = parse_file(log_file, source="no-ts")
    assert len(lines) == 2
    assert all(l.timestamp is None for l in lines)

    masked, _ = mask_lines(lines)
    sigs = build_signatures(masked, "no-ts")
    sigs = assign_ids(sigs)
    digest = build_digest(sigs, "no-ts")
    assert isinstance(digest, str)
