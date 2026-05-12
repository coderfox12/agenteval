"""
Zentrale Preistabelle für OpenAI-Modelle (Preise per 1 Million Tokens in USD).

Quellen:
  - https://platform.openai.com/docs/pricing  (Stand: Mai 2026)
  - gpt-4o-mini / gpt-4o: letzter bekannter Preis (Modell nicht mehr auf
    der Hauptpreisseite gelistet, aber weiterhin in Verwendung)

Pflege: Preise hier manuell aktualisieren, wenn OpenAI sie ändert.
"""

# ---------------------------------------------------------------------------
# Preise in USD pro 1 Million Tokens
# ---------------------------------------------------------------------------

PRICES_PER_1M: dict[str, dict[str, float]] = {
    # ── Aktuelle Flagship-Modelle (Stand Mai 2026) ──────────────────────────
    "gpt-5.5":          {"input": 5.00,   "output": 30.00},
    "gpt-5.5-pro":      {"input": 30.00,  "output": 180.00},
    "gpt-5.4":          {"input": 2.50,   "output": 15.00},
    "gpt-5.4-mini":     {"input": 0.75,   "output": 4.50},
    "gpt-5.4-nano":     {"input": 0.20,   "output": 1.25},
    "gpt-5.4-pro":      {"input": 30.00,  "output": 180.00},

    # ── Ältere Modelle (nicht mehr auf Hauptpreisseite, Preis bekannt) ──────
    "gpt-4o-mini":      {"input": 0.150,  "output": 0.600},
    "gpt-4o":           {"input": 2.50,   "output": 10.00},
    "gpt-3.5-turbo":    {"input": 0.50,   "output": 1.50},

    # ── Fallback ─────────────────────────────────────────────────────────────
    "default":          {"input": 0.75,   "output": 4.50},
}

# Versionsaliase: OpenAI gibt im Dashboard oft den versionierten Namen zurück
# (z. B. "gpt-4o-mini-2024-07-18"). Diese Tabelle mappt sie auf den Basisnamen.
VERSION_ALIASES: dict[str, str] = {
    "gpt-4o-mini-2024-07-18":  "gpt-4o-mini",
    "gpt-4o-2024-08-06":       "gpt-4o",
    "gpt-4o-2024-05-13":       "gpt-4o",
    "gpt-3.5-turbo-instruct":  "gpt-3.5-turbo",
    "gpt-3.5-turbo-0125":      "gpt-3.5-turbo",
    # interne OpenAI-Versionsbezeichnungen aus dem Dashboard
    "gpt-5_4-2026-03-05":      "gpt-5.4",
    "gpt-5_5-2026-04-23":      "gpt-5.5",
}


def _resolve(model: str) -> dict[str, float]:
    """Gibt das Preisdict für ein Modell zurück (Aliase werden aufgelöst)."""
    name = VERSION_ALIASES.get(model, model)
    # Prefix-Matching als Fallback (z. B. "gpt-5.4-2026-xx-xx" → "gpt-5.4")
    if name not in PRICES_PER_1M:
        for key in PRICES_PER_1M:
            if name.startswith(key):
                return PRICES_PER_1M[key]
    return PRICES_PER_1M.get(name, PRICES_PER_1M["default"])


def calc_cost_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    """Berechnet die API-Kosten in USD aus Token-Zahlen und eigener Preistabelle."""
    p = _resolve(model)
    return (input_tokens * p["input"] + output_tokens * p["output"]) / 1_000_000
