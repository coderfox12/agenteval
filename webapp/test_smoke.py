"""Leichter Smoke-Test für die Web-App – lokal und in CI nutzbar.

Führt webapp/app.py in einer simulierten Streamlit-Session aus (alle
Bereiche außer "Hilfe & Dokumentation", die nur README.md rendert) und
prüft auf unbehandelte Exceptions. Startet KEINE echten Subprozesse/
API-Calls – die laufen nur bei einem echten Klick auf "Evaluierung
starten", der hier nicht simuliert wird. Keine Kosten, keine Secrets nötig.

Aufruf:
  pip install -r webapp/requirements.txt
  python webapp/test_smoke.py
"""

from pathlib import Path

from streamlit.testing.v1 import AppTest

APP_PATH = Path(__file__).parent / "app.py"

# Reihenfolge der Sidebar-Radio-Optionen in app.py.
SECTIONS = ["Agenten", "Use Case & Evaluierung"]


def main() -> None:
    at = AppTest.from_file(str(APP_PATH))
    at.run(timeout=30)
    assert not at.exception, f"API & Modelle: {list(at.exception)}"

    for section in SECTIONS:
        at.sidebar.radio[0].set_value(section).run(timeout=30)
        assert not at.exception, f"{section}: {list(at.exception)}"

    print("OK – webapp/app.py lädt alle Bereiche fehlerfrei.")


if __name__ == "__main__":
    main()
