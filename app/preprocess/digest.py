"""Generacion del digest: texto que va en la etiqueta <logs> del Agente de Ingesta.

Una linea por firma. Limita las firmas INFO rutinarias de gran volumen.
Estima tokens (caracteres / 4).
"""
from __future__ import annotations

from datetime import datetime

from app.preprocess.signatures import Signature

INFO_HIGH_VOLUME_THRESHOLD = 5  # count a partir del cual se resume INFO
MAX_INFO_LINES = 10  # maximo de lineas INFO en el digest


def _fmt_time(ts: datetime | None) -> str:
    return ts.strftime("%H:%M:%S") if ts is not None else "Desconocido"


def _fmt_range(first: datetime | None, last: datetime | None) -> str:
    if first is None and last is None:
        return "Desconocido"
    return f"{_fmt_time(first)}→{_fmt_time(last)}"


def _fmt_duration(sig: Signature) -> str:
    if sig.duration_first is None:
        return ""
    base = f"dur={int(sig.duration_first)}ms"
    if sig.duration_max is not None and sig.duration_max != sig.duration_first:
        base += f"(max={int(sig.duration_max)}ms)"
    return base


def _truncate(text: str, limit: int = 120) -> str:
    return text if len(text) <= limit else text[:limit] + "..."


def build_digest(signatures: list[Signature], source: str) -> str:
    """Construye el texto del digest para una fuente.

    Conserva todas las WARN y ERROR. Limita las INFO rutinarias.
    """
    lines: list[str] = []
    info_count = 0

    for sig in signatures:
        if sig.source != source:
            continue

        # Limitar INFO rutinarias
        if sig.level == "INFO":
            if sig.count > INFO_HIGH_VOLUME_THRESHOLD:
                info_count += 1
                if info_count > MAX_INFO_LINES:
                    continue
                example = f"[rutina x{sig.count}] {_truncate(sig.example, 80)}"
            else:
                example = _truncate(sig.example)
        else:
            example = _truncate(sig.example)

        parts = [
            sig.evidence_id or "???",
            _fmt_range(sig.time_first, sig.time_last),
            sig.level,
            f"x{sig.count}",
            _fmt_duration(sig),
            example,
        ]
        line = " | ".join(p for p in parts if p or p == "")
        lines.append(line)

    return "\n".join(lines)


def estimate_tokens(text: str) -> int:
    """Estima tokens como caracteres / 4."""
    return len(text) // 4


def compute_token_reduction(original_text: str, digest_text: str) -> dict:
    """Calcula tokens originales, del digest y reduccion."""
    orig = estimate_tokens(original_text)
    dig = estimate_tokens(digest_text)
    reduction = orig - dig
    pct = (reduction / orig * 100) if orig > 0 else 0.0
    return {
        "original_tokens": orig,
        "digest_tokens": dig,
        "reduction": reduction,
        "reduction_pct": round(pct, 1),
    }
