"""Paso 1 - Preproceso local (sin IA): parseo, enmascarado, firmas, IDs E001..

Modulos:
  parser      -- lectura, timestamps, nivel, stack traces, JSON logs
  masking     -- JWT, Bearer, passwords, emails, tarjetas Luhn, IPv4, custom
  signatures  -- agrupacion, normalizacion, duraciones, ejemplo
  ids         -- IDs globales E001.. en orden cronologico
  merge       -- fusion de resultados de ingesta + rechazo de IDs
  digest      -- texto <logs>, limite INFO, estimacion de tokens
"""
from app.preprocess.parser import LogLine, parse_file, parse_text
from app.preprocess.masking import mask_text, mask_lines, load_masking_rules
from app.preprocess.signatures import Signature, build_signatures, normalize_for_signature
from app.preprocess.ids import assign_ids, known_ids
from app.preprocess.merge import MergeResult, merge_ingest_results
from app.preprocess.digest import build_digest, estimate_tokens, compute_token_reduction

__all__ = [
    "LogLine",
    "Signature",
    "parse_file",
    "parse_text",
    "mask_text",
    "mask_lines",
    "load_masking_rules",
    "build_signatures",
    "normalize_for_signature",
    "assign_ids",
    "known_ids",
    "MergeResult",
    "merge_ingest_results",
    "build_digest",
    "estimate_tokens",
    "compute_token_reduction",
]
