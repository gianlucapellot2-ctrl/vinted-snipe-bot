"""
storage.py — Persistente Datenspeicherung (JSON-basiert)
Verwaltet filters.json und user_tokens.json
"""

import json
import os
from pathlib import Path

# Dateipfade (relativ zum Bot-Verzeichnis)
BASE_DIR      = Path(__file__).parent
FILTERS_FILE  = BASE_DIR / "filters.json"
TOKENS_FILE   = BASE_DIR / "user_tokens.json"


# ─── Hilfsfunktionen ──────────────────────────────────────────────────────────

def _read_json(filepath: Path) -> dict:
    """Liest eine JSON-Datei. Gibt leeres Dict zurück falls nicht vorhanden."""
    if not filepath.exists():
        return {}
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def _write_json(filepath: Path, data: dict):
    """Schreibt ein Dict als JSON-Datei (mit Einrückung für Lesbarkeit)."""
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ─── Filter-Funktionen ────────────────────────────────────────────────────────

def load_filters() -> dict:
    """
    Lädt alle gespeicherten Filter.
    Rückgabe: {filter_id: filter_config_dict, ...}
    """
    return _read_json(FILTERS_FILE)


def save_filter(filter_id: str, filter_config: dict):
    """Speichert oder aktualisiert einen einzelnen Filter."""
    filters = load_filters()
    filters[filter_id] = filter_config
    _write_json(FILTERS_FILE, filters)


def remove_filter(filter_id: str):
    """Entfernt einen Filter aus der Datei."""
    filters = load_filters()
    if filter_id in filters:
        del filters[filter_id]
        _write_json(FILTERS_FILE, filters)


def get_filter(filter_id: str) -> dict | None:
    """Gibt einen einzelnen Filter zurück oder None."""
    return load_filters().get(filter_id)


# ─── User-Token-Funktionen ────────────────────────────────────────────────────

def load_user_tokens() -> dict:
    """
    Lädt alle gespeicherten User-Tokens.
    Rückgabe: {user_id_str: cookie_string, ...}
    """
    return _read_json(TOKENS_FILE)


def save_user_token(user_id: int, cookie: str):
    """Speichert oder überschreibt den Vinted Cookie eines Users."""
    tokens = load_user_tokens()
    tokens[str(user_id)] = cookie
    _write_json(TOKENS_FILE, tokens)


def get_user_token(user_id: int) -> str | None:
    """
    Gibt den gespeicherten Cookie eines Users zurück.
    Gibt None zurück falls der User kein /setup gemacht hat.
    """
    tokens = load_user_tokens()
    return tokens.get(str(user_id))


def remove_user_token(user_id: int):
    """Löscht den gespeicherten Cookie eines Users."""
    tokens = load_user_tokens()
    if str(user_id) in tokens:
        del tokens[str(user_id)]
        _write_json(TOKENS_FILE, tokens)


def has_user_token(user_id: int) -> bool:
    """Prüft ob ein User einen Vinted Cookie gespeichert hat."""
    return get_user_token(user_id) is not None
