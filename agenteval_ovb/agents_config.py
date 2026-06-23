"""
Gemeinsames Laden/Validieren von agents.yaml.

Vermeidet, dass jeder Einstiegspunkt (R0-Smoke-Test, D1-Pytest, D2/D3-
Runner, Report) das Einlesen der Datei und die api_base-Pflichtfeld-
Prüfung eigenständig dupliziert.
"""

from pathlib import Path

import yaml

# agents.yaml liegt im Repo-Root, ein Verzeichnis über diesem Package.
_PACKAGE_ROOT = Path(__file__).resolve().parent.parent


def find_agents_yaml() -> Path | None:
    """Sucht agents.yaml an den üblichen Stellen. Verschiedene Einstiegspunkte
    laufen mit unterschiedlichem Arbeitsverzeichnis (Skripte vom Repo-Root,
    pytest aus evals/functionality/), daher beide Kandidaten prüfen."""
    for candidate in (Path("agents.yaml"), _PACKAGE_ROOT / "agents.yaml"):
        if candidate.exists():
            return candidate
    return None


def load_agents_config(path: Path | None = None) -> dict:
    """Lädt und parsed agents.yaml. Wirft FileNotFoundError statt eines
    stillen Fallbacks, falls die Datei fehlt – das soll sofort auffallen."""
    config_path = path or find_agents_yaml()
    if config_path is None or not config_path.exists():
        raise FileNotFoundError(
            "agents.yaml nicht gefunden (weder im aktuellen Verzeichnis noch im Repo-Root)."
        )
    with open(config_path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def require_api_base(cfg: dict, label: str) -> str:
    """Gibt api_base zurück oder bricht mit klarer Fehlermeldung ab –
    Pflichtfeld, auch für OpenAI (https://api.openai.com/v1)."""
    api_base = cfg.get("api_base")
    if not api_base:
        raise ValueError(
            f"{label}: api_base fehlt in agents.yaml – Pflichtfeld, auch für "
            f"OpenAI (https://api.openai.com/v1)."
        )
    return api_base


def provider_pin_extra_body(cfg: dict) -> dict:
    """Baut den extra_body/passthrough-Block für OpenRouters provider.only-
    Parameter, falls cfg["provider_pin"] gesetzt ist – sonst leeres dict
    (No-op, z. B. bei direktem Zugriff auf eine Provider-API ohne OpenRouter).

    OpenRouter routet denselben Modellnamen je nach Verfügbarkeit an viele
    verschiedene Hosts mit teils stark unterschiedlichen Preisen für
    dasselbe Modell (real gemessen: bis Faktor 3,4 Unterschied) – ohne
    Pinning sind die Kosten in pricing.py daher nur ein Näherungswert.
    Wird in run_promptfoo_multi_agent.py/run_smoke_test.py (als JSON für
    Nunjucks-Templates in den promptfoo-YAMLs) und in graph.py/
    test_functionality.py (direkt als extra_body/generation_kwargs für
    LangChain bzw. DeepEval) verwendet – jeweils dasselbe openai-python-
    SDK-Feature extra_body, das OpenRouter-spezifische Zusatzparameter
    direkt in den Request-Body durchreicht.
    """
    pin = cfg.get("provider_pin")
    return {"provider": {"only": [pin]}} if pin else {}
