"""Comando: python -m app.preprocess <directorio>

Procesa todos los *.log del directorio: parseo, enmascarado, firmas, IDs.
Imprime el resumen por fuente, los contadores de enmascarado y la
reduccion de tokens.
"""
from __future__ import annotations

import sys
from pathlib import Path

from app.preprocess.digest import build_digest, compute_token_reduction, estimate_tokens
from app.preprocess.ids import assign_ids
from app.preprocess.masking import load_masking_rules, mask_lines
from app.preprocess.parser import parse_file
from app.preprocess.signatures import build_signatures


def source_name_for_file(filename: str) -> str:
    """Deriva el nombre de fuente: nginx-access y nginx-error -> 'nginx'."""
    name = Path(filename).name
    if name.startswith("nginx"):
        return "nginx"
    return Path(filename).stem


def run_preprocess(directory: str) -> None:
    dir_path = Path(directory)
    if not dir_path.is_dir():
        print(f"ERROR: no existe el directorio {directory}")
        sys.exit(1)

    log_files = sorted(dir_path.glob("*.log"))
    if not log_files:
        print(f"ERROR: no hay archivos .log en {directory}")
        sys.exit(1)

    custom_rules = load_masking_rules()

    # Agrupar archivos por fuente
    files_by_source: dict[str, list[Path]] = {}
    for f in log_files:
        src = source_name_for_file(f.name)
        files_by_source.setdefault(src, []).append(f)

    # Procesar cada fuente
    all_signatures = []
    source_data: list[dict] = []
    total_counters: dict[str, int] = {}

    for src in sorted(files_by_source):
        files = files_by_source[src]
        all_lines = []
        raw_text = ""
        for f in files:
            text = f.read_text(encoding="utf-8", errors="replace")
            raw_text += text
            all_lines.extend(parse_file(f, source=src))

        masked_lines, counters = mask_lines(all_lines, custom_rules=custom_rules)
        sigs = build_signatures(masked_lines, src)

        all_signatures.extend(sigs)
        source_data.append({"source": src, "signatures": sigs, "raw_text": raw_text})
        for k, v in counters.items():
            total_counters[k] = total_counters.get(k, 0) + v

    # Asignar IDs globales
    all_signatures = assign_ids(all_signatures)

    # Resumen por fuente
    print("=" * 70)
    print("PREPROCESO DE LOGS - RESUMEN")
    print("=" * 70)

    total_orig_tokens = 0
    total_digest_tokens = 0

    for sd in source_data:
        src = sd["source"]
        sigs = [s for s in all_signatures if s.source == src]
        digest_text = build_digest(sigs, src)
        reduction = compute_token_reduction(sd["raw_text"], digest_text)

        total_orig_tokens += reduction["original_tokens"]
        total_digest_tokens += reduction["digest_tokens"]

        print(f"\n--- Fuente: {src} ({len(sigs)} firmas) ---")
        for sig in sigs:
            stack_info = f" +{len(sig.example_stack)} stack" if sig.example_stack else ""
            dur = ""
            if sig.duration_first is not None:
                dur = f" dur={int(sig.duration_first)}ms"
            print(
                f"  {sig.evidence_id} | {sig.level:5s} | x{sig.count:<3d} | "
                f"{sig.example[:70]}{stack_info}{dur}"
            )
        print(f"  Tokens: {reduction['original_tokens']} -> "
              f"{reduction['digest_tokens']} "
              f"(-{reduction['reduction']} {reduction['reduction_pct']}%)")

    # Contadores de enmascarado
    print("\n" + "=" * 70)
    print("CONTADORES DE ENMASCARADO")
    print("=" * 70)
    if total_counters:
        for k, v in sorted(total_counters.items()):
            print(f"  {k:12s}: {v}")
    else:
        print("  (sin datos sensibles detectados)")

    # Totales
    print("\n" + "=" * 70)
    print("TOTALES")
    print("=" * 70)
    print(f"  Fuentes: {len(source_data)}")
    print(f"  Firmas:  {len(all_signatures)}")
    total_reduction = total_orig_tokens - total_digest_tokens
    pct = (total_reduction / total_orig_tokens * 100) if total_orig_tokens else 0.0
    print(f"  Tokens:  {total_orig_tokens} -> {total_digest_tokens} "
          f"(-{total_reduction} {round(pct, 1)}%)")


def main(argv: list[str] | None = None) -> None:
    args = argv if argv is not None else sys.argv[1:]
    directory = args[0] if args else "samples/checkout-incident"
    run_preprocess(directory)


if __name__ == "__main__":
    main()
