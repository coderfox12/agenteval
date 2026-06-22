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

    # ── Drittanbieter-Modelle über OpenRouter (Preise von openrouter.ai) ────
    "openai/gpt-oss-120b":                    {"input": 0.039, "output": 0.18},
    "google/gemini-2.5-flash-lite":           {"input": 0.10,  "output": 0.40},
    "deepseek/deepseek-v4-flash":              {"input": 0.09,  "output": 0.18},
    "meta-llama/llama-3.1-8b-instruct:free":  {"input": 0.0,   "output": 0.0},
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


class UnknownModelPriceError(ValueError):
    """Für ein Modell ist kein Preis in PRICES_PER_1M hinterlegt."""


# OpenRouter-Routing-Suffixe (steuern NUR den Provider, kein Bestandteil des
# Preis-Tiers). Andere Suffixe wie ":free" gehören zum Modellnamen selbst und
# dürfen nicht abgeschnitten werden – sonst findet _resolve() keinen Preis
# mehr (z. B. "meta-llama/llama-3.1-8b-instruct:free" != "...instruct").
_OPENROUTER_ROUTING_SUFFIXES = (":floor", ":nitro")


def _strip_routing_suffix(model: str) -> str:
    """Entfernt nur bekannte OpenRouter-Routing-Suffixe vom Modellnamen."""
    for suffix in _OPENROUTER_ROUTING_SUFFIXES:
        if model.endswith(suffix):
            return model[: -len(suffix)]
    return model


def is_known(model: str) -> bool:
    """Prüft, ob für ein Modell ein Preis hinterlegt ist (exakt oder per Prefix)."""
    name = VERSION_ALIASES.get(_strip_routing_suffix(model), model)
    return name in PRICES_PER_1M or any(name.startswith(key) for key in PRICES_PER_1M)


def _resolve(model: str) -> dict[str, float]:
    """Gibt das Preisdict für ein Modell zurück (Routing-Suffixe entfernt,
    Aliase aufgelöst).

    Wirft UnknownModelPriceError statt stillschweigend einen Default-Preis zu
    verwenden – ein fehlender Preis soll sofort auffallen, nicht erst als
    falsche Wirtschaftlichkeits-Zahl im Report.
    """
    stripped = _strip_routing_suffix(model)
    name = VERSION_ALIASES.get(stripped, stripped)
    if name in PRICES_PER_1M:
        return PRICES_PER_1M[name]
    for key in PRICES_PER_1M:
        if name.startswith(key):
            return PRICES_PER_1M[key]
    raise UnknownModelPriceError(
        f"Kein Preis für Modell '{model}' in agenteval_ovb/pricing.py "
        f"(PRICES_PER_1M) hinterlegt. Bitte Input-/Output-Preis pro 1M Tokens "
        f"ergänzen – sonst sind die Wirtschaftlichkeits-Zahlen im Report falsch."
    )


def calc_cost_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    """Berechnet die API-Kosten in USD aus Token-Zahlen und eigener Preistabelle."""
    p = _resolve(model)
    return (input_tokens * p["input"] + output_tokens * p["output"]) / 1_000_000


def price_per_token(model: str) -> tuple[float, float]:
    """Gibt (input_price, output_price) in USD PRO TOKEN zurück (nicht pro 1M) –
    für Bibliotheken wie DeepEval, die Kosten selbst aus Rohpreisen pro Token
    berechnen (z. B. via OPENAI_COST_PER_INPUT_TOKEN/...OUTPUT_TOKEN)."""
    p = _resolve(model)
    return p["input"] / 1_000_000, p["output"] / 1_000_000


def validate_agents_config(config: dict) -> None:
    """Prüft Judge- und alle Agenten-Modelle aus agents.yaml gegen PRICES_PER_1M.

    Von jedem unabhängigen Einstiegspunkt (D1-Pytest, D2/D3-Runner) selbst
    aufzurufen, da beide auch einzeln gestartet werden können – es gibt
    keinen gemeinsamen Startpunkt, der das einmalig für beide erledigt.
    """
    judge_model = (config.get("judge") or {}).get("model")
    if judge_model and not is_known(judge_model):
        raise UnknownModelPriceError(
            f"Kein Preis für Judge-Modell '{judge_model}' in "
            f"agenteval_ovb/pricing.py hinterlegt. Bitte PRICES_PER_1M ergänzen."
        )
    for agent in config.get("agents", []):
        if not is_known(agent["model"]):
            raise UnknownModelPriceError(
                f"Kein Preis für Agent '{agent['id']}' (Modell "
                f"'{agent['model']}') in agenteval_ovb/pricing.py hinterlegt. "
                f"Bitte PRICES_PER_1M ergänzen."
            )
