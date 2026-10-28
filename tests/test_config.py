import os

from app.config import Settings, validate_llm_settings


def test_validate_llm_settings_missing_key_maas_mode() -> None:
    """Sin MAAS_API_KEY y en modo maas, validate_llm_settings devuelve un error claro."""
    settings = Settings(MAAS_API_KEY="", MAAS_MODEL="", LLM_MODE="maas")
    # Sobrescribe el singleton temporalmente
    import app.config as cfg

    original = cfg.settings
    cfg.settings = settings
    try:
        errors = validate_llm_settings()
    finally:
        cfg.settings = original

    assert len(errors) >= 1
    assert any("MAAS_API_KEY" in e for e in errors)


def test_validate_llm_settings_fake_mode_ok() -> None:
    """En modo fake no se requiere API key."""
    settings = Settings(LLM_MODE="fake")
    import app.config as cfg

    original = cfg.settings
    cfg.settings = settings
    try:
        errors = validate_llm_settings()
    finally:
        cfg.settings = original

    assert errors == []
