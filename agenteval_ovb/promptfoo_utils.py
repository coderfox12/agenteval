"""Gemeinsame Hilfsfunktion zum Parsen von promptfoo-Eval-Ausgaben + gemeinsame
Konstanten für CLI-Aufrufe (Version, Concurrency)."""

# Feste Version statt "@latest": vermeidet, dass npx bei JEDEM Aufruf erst die
# npm-Registry nach der aktuellen "latest"-Version abfragt (bei vielen
# parallelen Aufrufen spürbarer Overhead), und schützt vor einem stillen
# Verhaltens-/Format-Wechsel durch ein npm-Update mitten in der Entwicklung.
# Bei Bedarf bewusst aktualisieren (z. B. `npx promptfoo@latest --version`).
PROMPTFOO_VERSION = "0.121.17"

# promptfoo's Default ist 4 gleichzeitige API-Calls pro eval-Aufruf. OpenRouter
# verträgt deutlich mehr gleichzeitige Requests, daher hier angehoben.
DEFAULT_MAX_CONCURRENCY = 8


def extract_promptfoo_results(data: dict | None) -> list[dict]:
    """promptfoo schreibt Ergebnisse je nach Aufruf-Kontext unter
    results.results ODER direkt unter results – beide Formen abdecken."""
    if not data:
        return []
    return data.get("results", {}).get("results", data.get("results", []))
