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

# Navigation läuft über den URL-Query-Parameter "page" (siehe PAGE_SLUGS in
# app.py), nicht mehr über ein st.radio-Widget – die Sidebar besteht seit der
# Umstellung auf frei einfärbbare Status-Punkte aus reinen HTML-Links.
PAGE_SLUGS = ["agenten", "usecase"]


def main() -> None:
    at = AppTest.from_file(str(APP_PATH))
    at.run(timeout=30)
    assert not at.exception, f"API-Keys: {list(at.exception)}"

    for slug in PAGE_SLUGS:
        at.query_params["page"] = slug
        at.run(timeout=30)
        assert not at.exception, f"page={slug}: {list(at.exception)}"

    print("OK – webapp/app.py lädt alle Bereiche fehlerfrei.")


if __name__ == "__main__":
    main()
