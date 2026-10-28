"""Paso 7 - Generacion de reportes (HTML / JSON / ticket)."""

from app.report.html import generate_html_report, generate_json_export

__all__ = ["generate_html_report", "generate_json_export"]
