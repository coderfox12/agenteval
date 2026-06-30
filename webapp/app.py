"""Agent-Eval@OVB – Web-Oberfläche zur Konfiguration und Ausführung der Evals.

Bündelt bisher manuelle Schritte in einem Formular:
  1. API-Keys (.env)
  2. Zu testende Agenten + Judge (agents.yaml)
  3. Auswahl des Use Case (UC0-UC4) + Eval-Suiten + Start mit Live-Log

Start lokal:  streamlit run webapp/app.py   (oder start.bat im Projekt-Root)

Ruft im Hintergrund exakt dieselben Skripte auf wie `make eval` auch
(scripts/run_smoke_test.py, scripts/run_promptfoo_multi_agent.py,
pytest test_functionality.py, agenteval-report) – die Web-App ersetzt das
Terminal nicht, sie ist nur eine zusätzliche Oberfläche davor.

Konfiguration läuft bewusst über Umgebungsvariablen/Dateien im Projekt-Root
und nicht über lokal hartcodierte Pfade, damit die App später unverändert
in einem Container/Hosting-Ziel mit vorgeschaltetem Login laufen kann.
"""

from __future__ import annotations

import base64
import os
import queue
import re
import subprocess
import sys
import threading
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components
import yaml
from streamlit.runtime.scriptrunner import add_script_run_ctx
from dotenv import dotenv_values

# ─── Pfade ─────────────────────────────────────────────────────────────────

ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = ROOT / ".env"
AGENTS_PATH = ROOT / "agents.yaml"
README_PATH = ROOT / "README.md"
ASSETS_DIR = Path(__file__).resolve().parent / "assets"
FAVICON_PATH = ASSETS_DIR / "favicon.svg"

st.set_page_config(
    page_title="Agent-Eval @ OVB",
    page_icon=str(FAVICON_PATH) if FAVICON_PATH.exists() else None,
    layout="wide",
)


# ─── OVB-Design-Tokens (1:1 aus den :root-CSS-Variablen von ovb.de) ────────
# --primary:#036  --ovb-sky:#00b7e5  --secondary:#6c757d
# --ovb-lightGrey:#f2f2f2  --success:#28a745  --danger:#EC312B
# Schrift dort: "Stag Sans LCG Web" (lizenziert, nicht einbettbar) -> Fallback.

OVB_NAVY = "#003366"
OVB_SKY = "#00b7e5"
OVB_GREY = "#6c757d"
OVB_LIGHTGREY = "#f2f2f2"
OVB_RADIUS = "0.25rem"

st.markdown(
    f"""
    <style>
    html, body, [class*="css"] {{
        font-family: "Segoe UI", "Stag Sans LCG Web", Arial, sans-serif;
    }}
    h1, h2, h3 {{
        color: {OVB_NAVY};
        font-weight: 700;
    }}
    section[data-testid="stSidebar"] {{
        background-color: #ffffff;
        border-right: 1px solid #e5e5e5;
    }}
    div[data-testid="stVerticalBlockBorderWrapper"] {{
        border-radius: 0.5rem !important;
        border-color: #e5e5e5 !important;
        box-shadow: 0 0.125rem 0.35rem rgba(0,0,0,0.08);
    }}
    div.stButton > button, div.stFormSubmitButton > button, div.stDownloadButton > button {{
        border-radius: {OVB_RADIUS};
        border: 1px solid {OVB_NAVY};
        color: {OVB_NAVY};
    }}
    div.stButton > button[kind="primary"], div.stFormSubmitButton > button[kind="primary"] {{
        background-color: {OVB_SKY};
        border-color: {OVB_SKY};
        color: #ffffff;
        box-shadow: 0 0.125rem 0.25rem rgba(0,0,0,0.1);
    }}
    div.stButton > button[kind="primary"]:hover, div.stFormSubmitButton > button[kind="primary"]:hover {{
        background-color: {OVB_NAVY};
        border-color: {OVB_NAVY};
    }}
    .stTextInput input, .stTextArea textarea, .stSelectbox div[data-baseweb="select"] > div {{
        border-radius: {OVB_RADIUS} !important;
    }}
    /* Dropdowns sind reine Auswahlfelder (kein Freitext) -> Hand-Cursor statt
       Text-Cursor, der durch BaseWebs eingebautes Tipp-zum-Filtern entsteht. */
    .stSelectbox div[data-baseweb="select"], .stSelectbox div[data-baseweb="select"] * {{
        cursor: pointer !important;
    }}
    a.sidebar-logo-link {{
        display: inline-block;
        cursor: pointer;
    }}
    /* Bewusst leichter als die drei Radio-Punkte oben: Hilfe ist ein
       sekundärer Verweis, kein gleichrangiger vierter Workflow-Schritt. */
    a.sidebar-help-link {{
        display: block;
        padding: 0.3rem 0;
        color: {OVB_GREY};
        font-size: 0.85rem;
        text-decoration: none;
    }}
    a.sidebar-help-link:hover {{
        color: {OVB_NAVY};
        text-decoration: underline;
    }}
    </style>
    """,
    unsafe_allow_html=True,
)


def _find_logo_file() -> Path:
    """Eigenes Logo (logo.png) > heruntergeladenes OVB+agenteval-Logo (logo.svg) > Platzhalter."""
    for name in ("logo.png", "logo.svg"):
        candidate = ASSETS_DIR / name
        if candidate.exists():
            return candidate
    return ASSETS_DIR / "logo_placeholder.svg"


def _logo_data_uri(path: Path) -> str:
    mime = "image/svg+xml" if path.suffix == ".svg" else "image/png"
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{encoded}"


logo_file = _find_logo_file()
logo_uri = _logo_data_uri(logo_file)

# ─── Sidebar: Logo + Navigation (einmalig, kein zweites Logo im Hauptbereich) ─
# Navigation hängt am URL-Query-Parameter "page" -> jede Unterseite (inkl.
# Hilfe) hat eine eigene, teil- und bookmarkbare URL (?page=...), Browser-
# Zurück/Vor funktioniert, und das Logo verlinkt per <a href="?page=api"> auf
# die Startseite ("API & Modelle"), ganz ohne eigene Multipage-App-Struktur.

PAGES = ["API & Modelle", "Agenten", "Use Case & Evaluierung"]
PAGE_SLUGS = {"API & Modelle": "api", "Agenten": "agenten", "Use Case & Evaluierung": "usecase"}
SLUG_TO_PAGE = {slug: name for name, slug in PAGE_SLUGS.items()}

current_slug = st.query_params.get("page", "api")
show_help = current_slug == "hilfe"
# None auf der Hilfe-Seite statt eines Fallback-Werts: sonst zeigt das Radio
# unten fälschlich einen der drei Arbeitsschritte als "ausgewählt" an, obwohl
# eigentlich Hilfe & Dokumentation aktiv ist.
active_section = None if show_help else SLUG_TO_PAGE.get(current_slug, "API & Modelle")


def _sync_query_param() -> None:
    st.query_params["page"] = PAGE_SLUGS[st.session_state["nav_section"]]


with st.sidebar:
    st.markdown(
        f'<a class="sidebar-logo-link" href="?page=api" target="_self">'
        f'<img src="{logo_uri}" alt="agenteval Logo – zur Startseite" width="220"/></a>',
        unsafe_allow_html=True,
    )
    if logo_file.name == "logo_placeholder.svg":
        st.caption(
            "Platzhalter-Logo. Eigenes Logo als `webapp/assets/logo.png` "
            "ablegen, um es automatisch zu verwenden."
        )
    st.markdown(
        f'<div style="color:{OVB_GREY};font-size:0.85rem;margin:0.6rem 0 1.6rem;line-height:1.4;">'
        "Konfiguration &amp; Ausführung der Agenten-Evaluierung</div>"
        '<hr style="margin:0 0 1.4rem;border:none;border-top:1px solid #e5e5e5;"/>',
        unsafe_allow_html=True,
    )
    section = st.radio(
        "Navigation",
        PAGES,
        index=PAGES.index(active_section) if active_section else None,
        label_visibility="collapsed",
        on_change=_sync_query_param,
        key="nav_section",
    )
    # Deutlich abgesetzt von den drei Arbeitsschritten oben, damit man dort
    # nicht versehentlich hinklickt statt auf den nächsten Workflow-Schritt.
    st.markdown("<div style='margin-top:3.5rem'></div>", unsafe_allow_html=True)
    st.markdown(
        '<hr style="margin:0 0 0.6rem;border:none;border-top:1px solid #e5e5e5;"/>'
        '<a class="sidebar-help-link" href="?page=hilfe" target="_self">Hilfe &amp; Dokumentation</a>',
        unsafe_allow_html=True,
    )


# ─── Hilfsfunktionen: .env ───────────────────────────────────────────────────
# Agent-Keys folgen einer festen, anbieterunabhängigen Namensprozedur:
# AGENT_API_KEY_1, AGENT_API_KEY_2, ... – beliebig viele, in der Web-App
# verwaltet. Kein Anbietername (z. B. "OpenRouter") im Variablennamen, damit
# weder .env noch agents.yaml an einen Anbieter binden. agents.yaml selbst
# akzeptiert ohnehin jeden frei gewählten Variablennamen für api_key_env.

AGENT_KEY_PREFIX = "AGENT_API_KEY_"

# Judge-Modell, -api_base und -provider_pin werden NICHT hier, sondern im
# judge-Block in agents.yaml gesetzt (Tab "Agenten") – dort ist api_base
# ohnehin ein Pflichtfeld. Hier nur der rohe Key, sonst gäbe es zwei Stellen
# für denselben Wert.
JUDGE_ENV_FIELDS = [
    ("JUDGE_API_KEY", "Judge API-Key", "password", True),
]


def load_env_values() -> dict[str, str]:
    if ENV_PATH.exists():
        return {k: (v or "") for k, v in dotenv_values(ENV_PATH).items()}
    return {}


def list_agent_key_slots(env_values: dict[str, str]) -> list[str]:
    """Alle AGENT_API_KEY_N-Namen aus .env, numerisch sortiert."""
    slots = [k for k in env_values if k.startswith(AGENT_KEY_PREFIX) and k[len(AGENT_KEY_PREFIX):].isdigit()]
    return sorted(slots, key=lambda k: int(k[len(AGENT_KEY_PREFIX):]))


def next_agent_key_slot(existing: list[str]) -> str:
    used = {int(name[len(AGENT_KEY_PREFIX):]) for name in existing}
    n = 1
    while n in used:
        n += 1
    return f"{AGENT_KEY_PREFIX}{n}"


def write_env_values(agent_keys: dict[str, str], judge_values: dict[str, str]) -> None:
    lines = [
        "# agenteval-ovb – Umgebungsvariablen",
        "# Erzeugt/aktualisiert über die Web-App (webapp/app.py)",
        "",
        "# ── Agent API-Keys (generisch, beliebig viele, anbieterunabhängig) ──────────",
        '# Zuordnung zu Agenten erfolgt im Tab "Agenten".',
    ]
    for name in sorted(agent_keys, key=lambda k: int(k[len(AGENT_KEY_PREFIX):])):
        lines.append(f"{name}={agent_keys[name]}")
    lines += [
        "",
        "# ── Judge (LLM-as-Judge für Evaluation) ──────────────────────────────────────",
        "# Modell/api_base/provider_pin stehen im judge-Block in agents.yaml.",
        f"JUDGE_API_KEY={judge_values.get('JUDGE_API_KEY', '')}",
        "",
    ]
    ENV_PATH.write_text("\n".join(lines), encoding="utf-8")


# ─── Hilfsfunktionen: agents.yaml ────────────────────────────────────────────

def load_agents_config() -> dict:
    if AGENTS_PATH.exists():
        with open(AGENTS_PATH, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    return {"judge": {}, "agents": []}


def save_agents_config(judge: dict, agents: list[dict]) -> None:
    header = (
        "# Agent-Konfigurationen für Agent-Eval@OVB\n"
        "# Erzeugt/aktualisiert über die Web-App (webapp/app.py)\n"
        "#\n"
        "# api_key_env: Name der Umgebungsvariable in .env, die den API-Key enthält.\n"
        "# api_base:    Pflichtfeld für jeden Agenten und den Judge – auch für OpenAI.\n"
        "# provider_pin: optional, nur für OpenRouter – fixiert den Hosting-Anbieter.\n\n"
    )
    body = yaml.safe_dump(
        {"judge": judge, "agents": agents},
        allow_unicode=True,
        sort_keys=False,
    )
    AGENTS_PATH.write_text(header + body, encoding="utf-8")


# ─── Hilfsfunktion: Befehl live ausführen und Output streamen ──────────────

ANSI_RE = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]")


def strip_ansi(text: str) -> str:
    """Entfernt ANSI-Farbcodes (z. B. von promptfoo/npm), die in st.code() nur
    als rohe "[90m"-Zeichenfolgen statt als Farbe sichtbar wären."""
    return ANSI_RE.sub("", text)


class EvalState:
    """Geteilter Zustand zwischen Hintergrund-Thread und Hauptthread.

    BEWUSST kein st.session_state[...]-Zugriff aus dem Hintergrund-Thread:
    Streamlit unterbricht einen per add_script_run_ctx() angehängten Thread
    mit einer (nicht von except Exception fangbaren) StopException, sobald
    für dieselbe Session ein NEUER Skriptlauf begonnen hat – z. B. durch den
    Stop-Button-Klick selbst, der einen vollen Rerun auslöst. Der Thread starb
    dadurch mitten im Lauf, OHNE dass eval_running je zurückgesetzt wurde
    ("Evaluierung starten" blieb dauerhaft deaktiviert). Dieses Objekt liegt
    zwar selbst (einmalig) in st.session_state, der Thread bekommt aber nur
    die nackte Python-Referenz übergeben und mutiert direkt deren Attribute –
    keine SafeSessionState-Methode wird dafür je aus dem Thread aufgerufen."""

    def __init__(self) -> None:
        self.log_lines: list[str] = []
        self.running = False
        self.stage: str | None = None
        self.stop_requested = False
        self.current_process: subprocess.Popen | None = None
        self.any_failed = False
        self.error: str | None = None
        self.was_running = False


def _kill_process_tree(proc: subprocess.Popen | None) -> None:
    """Beendet proc inkl. aller Kindprozesse (npx startet z. B. node als Kind).
    proc.terminate() allein beendet unter Windows bei shell=True nur die
    cmd.exe-Hülle, nicht den dahinterliegenden Prozessbaum – die eigentlichen,
    kostenpflichtigen API-Aufrufe würden sonst unbemerkt im Hintergrund
    weiterlaufen, obwohl der Log so aussieht, als wäre gestoppt worden."""
    if proc is None or proc.poll() is not None:
        return
    try:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                capture_output=True,
            )
        else:
            proc.terminate()
    except Exception:
        pass


def run_command(cmd: str, eval_state: EvalState, cwd: Path | None = None, extra_env: dict | None = None):
    """Führt cmd im Projekt-Root (oder cwd) aus und liefert Zeilen live (Generator).

    Der laufende Prozess wird in eval_state.current_process hinterlegt, damit
    ein "Stop"-Klick ihn von außen beenden kann (reine Attribut-Mutation,
    siehe EvalState-Docstring – kein st.session_state-Zugriff aus dem Thread).

    Liest NICHT direkt blockierend aus process.stdout: Falls ein gekillter
    Prozess einen Enkel-Prozess (z. B. npx -> node) hinterlässt, der das
    Pipe-Ende offenhält, würde "for line in process.stdout" nie ein EOF sehen
    und ewig blockieren – der Stop-Check käme dann nie zur Ausführung. Ein
    separater Reader-Thread + Queue mit Timeout entkoppelt das: der Konsument
    hier prüft stop_requested mind. alle 0.5s, unabhängig davon, ob/wann
    der Pipe-Read selbst zurückkehrt.
    """
    full_env = os.environ.copy()
    # Ohne echtes Terminal fällt Pythons Stdout auf Windows auf die System-
    # Codepage (meist cp1252) zurück, die Unicode-Zeichen wie "▶"/"✅" in den
    # Skript-Ausgaben nicht kodieren kann (UnicodeEncodeError im Kindprozess).
    # UTF-8 erzwingen, passend zur encoding="utf-8" beim Auslesen unten.
    full_env["PYTHONIOENCODING"] = "utf-8"
    full_env["PYTHONUTF8"] = "1"
    # Farbcodes erst gar nicht erzeugen lassen (von npm/promptfoo respektiert),
    # strip_ansi() unten bleibt als Sicherheitsnetz für Tools, die das ignorieren.
    full_env["NO_COLOR"] = "1"
    full_env["FORCE_COLOR"] = "0"
    if extra_env:
        full_env.update(extra_env)
    process = subprocess.Popen(
        cmd,
        cwd=str(cwd or ROOT),
        env=full_env,
        shell=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        encoding="utf-8",
        errors="replace",
    )
    assert process.stdout is not None
    eval_state.current_process = process

    line_queue: queue.Queue[str | None] = queue.Queue()

    def _reader() -> None:
        try:
            for raw_line in process.stdout:
                line_queue.put(raw_line)
        except Exception:
            pass
        finally:
            line_queue.put(None)  # Sentinel: Stream zu Ende (oder Fehler)

    reader = threading.Thread(target=_reader, daemon=True)
    reader.start()

    while True:
        if eval_state.stop_requested:
            _kill_process_tree(process)
            break
        try:
            raw_line = line_queue.get(timeout=0.5)
        except queue.Empty:
            continue
        if raw_line is None:
            break
        yield strip_ansi(raw_line.rstrip("\n"))

    try:
        process.stdout.close()
    except Exception:
        pass
    try:
        returncode = process.wait(timeout=5)
    except Exception:
        returncode = -1
    eval_state.current_process = None
    yield f"__EXIT__:{returncode}"


def run_to_log(cmd: str, log, eval_state: EvalState, cwd: Path | None = None, extra_env: dict | None = None) -> int:
    """run_command, aber Zeilen direkt ins Log schreiben. Gibt den Exit-Code zurück."""
    exit_code = 0
    for line in run_command(cmd, eval_state, cwd=cwd, extra_env=extra_env):
        if line.startswith("__EXIT__:"):
            exit_code = int(line.split(":", 1)[1])
            break
        log(line)
    return exit_code


# ─── Use Cases (siehe evals/functionality/usecases/registry.py) ───────────
# Hier bewusst als einfache Liste gepflegt statt zur Laufzeit importiert,
# damit die Web-App nicht das komplette Eval-Package (LangGraph, DeepEval,
# ...) laden muss, nur um die Auswahl anzuzeigen.

USE_CASES = [
    ("uc0", "UC0 – Generische Baseline", "Allgemeine Finanzberatung, kein fachlicher Use Case"),
    ("uc1", "UC1 – Suitability-Check", "Anlageeignungsprüfung (IDD Art. 30 / §7 VersVermV)"),
    ("uc2", "UC2 – Onboarding", "KYC / Kundendaten (GwG §10 / AMLA)"),
    ("uc3", "UC3 – Compliance-Triage", "Regulatorische Einordnung (EU AI Act / OVB-Governance)"),
    ("uc4", "UC4 – Beratungsdokumentation", "Protokollerstellung (§61 VVG)"),
]
DEFAULT_USE_CASE = "uc1"


# ─── Eval-Stufen ─────────────────────────────────────────────────────────────
# Smoke/Security/Compliance/Funktionalität rufen exakt die Skripte auf, die
# auch `make eval` aufruft (siehe Makefile) – keine eigene Re-Implementierung
# der Agenten-/Provider-Pin-/.env-Logik, die liegt bereits korrekt in den
# Skripten selbst (inkl. .env laden, provider_pin, isolierte promptfoo-Configs).

SMOKE_LABEL = "R0 · Smoke-Test"
SMOKE_HELP = "Pflicht, läuft immer zuerst: prüft Judge + jeden Agenten mit einem günstigen Test-Call, bevor teure Suiten starten."

FUNCTIONALITY_STAGE = {
    "id": "functionality",
    "label": "Funktionalität (D1)",
    "help": "LangGraph-Agent gegen die Multi-Step-Tasks des gewählten Use Case – läuft parallel über alle Agenten.",
    "default": True,
}

SECURITY_STAGE = {
    "id": "security",
    "label": "Sicherheit (D2)",
    "help": (
        "Generische Baseline (40 Sicherheits- + 60 Finance-Sicherheitstests, läuft immer) "
        "plus die UC-spezifische Sicherheits-Suite des gewählten Use Case, pro Agent."
    ),
    "default": True,
}

COMPLIANCE_STAGE = {
    "id": "compliance",
    "label": "Compliance (D3)",
    "help": (
        "Generische Baseline (14 EU-AI-Act-Tests, läuft immer) plus die UC-spezifische "
        "Compliance-Suite des gewählten Use Case, pro Agent. Erzeugt automatisch auch die "
        "EU-AI-Act-Scorecard."
    ),
    "default": True,
}

# Security und Compliance laufen technisch in EINEM Skript-Aufruf
# (scripts/run_promptfoo_multi_agent.py), das beide Dimensionen pro Agent in
# einem Rutsch abarbeitet – RUN_SECURITY/RUN_COMPLIANCE steuern, welche davon
# tatsächlich ausgeführt werden (siehe Skript-Kommentar dort).


def _run_evaluation(
    eval_state: EvalState,
    selected_uc: str,
    func_checked: bool,
    security_checked: bool,
    compliance_checked: bool,
) -> None:
    """Läuft in einem Hintergrund-Thread (siehe add_script_run_ctx beim Start).
    Mutiert NUR Attribute von eval_state (siehe Klassen-Docstring) – nie
    st.session_state[...] direkt und nie st.*-Render-Funktionen. Das Rendern
    übernimmt _render_eval_status im Hauptthread, getriggert durch das
    auto-refreshende Fragment, das denselben eval_state liest.

    Reihenfolge D1 -> D2/D3 -> Report. Sicherheit (D2) und Compliance (D3)
    laufen technisch in EINEM Skript-Aufruf (run_promptfoo_multi_agent.py),
    der intern beide Dimensionen pro Agent abarbeitet – RUN_SECURITY/
    RUN_COMPLIANCE steuern darin, welche der beiden tatsächlich laufen.

    Das try/finally ist die Garantie, dass eval_state.running IMMER
    zurückgesetzt wird, selbst bei einem unerwarteten Fehler hier drin –
    sonst bliebe der "Evaluierung starten"-Button für immer deaktiviert."""
    uc_env = {"USE_CASE": selected_uc}
    py = f'"{sys.executable}"'

    def log(msg: str) -> None:
        eval_state.log_lines.append(msg)

    def stopped() -> bool:
        return eval_state.stop_requested

    try:
        eval_state.stage = SMOKE_LABEL
        log(f"\n=== {SMOKE_LABEL} ===")
        smoke_exit = run_to_log(f"{py} scripts/run_smoke_test.py", log, eval_state)

        any_failed = False
        error_msg = None

        if not stopped():
            if smoke_exit != 0:
                error_msg = (
                    "Smoke-Test fehlgeschlagen – Lauf abgebrochen, bevor kostenpflichtige Suiten "
                    "gestartet wurden. Siehe Log oben; meist falscher API-Key oder Modellname."
                )
            else:
                if func_checked and not stopped():
                    eval_state.stage = FUNCTIONALITY_STAGE["label"]
                    log(f"\n=== {FUNCTIONALITY_STAGE['label']} (Use Case {selected_uc}) ===")
                    exit_code = run_to_log(
                        f"{py} -m pytest test_functionality.py -v",
                        log,
                        eval_state,
                        cwd=ROOT / "evals" / "functionality",
                        extra_env=uc_env,
                    )
                    if exit_code != 0:
                        any_failed = True

                if (security_checked or compliance_checked) and not stopped():
                    stage_label = " + ".join(
                        s["label"] for s, on in ((SECURITY_STAGE, security_checked), (COMPLIANCE_STAGE, compliance_checked)) if on
                    )
                    eval_state.stage = stage_label
                    log(f"\n=== {stage_label} (Use Case {selected_uc}) ===")
                    scope_env = {
                        **uc_env,
                        "RUN_SECURITY": "1" if security_checked else "0",
                        "RUN_COMPLIANCE": "1" if compliance_checked else "0",
                    }
                    exit_code = run_to_log(f"{py} scripts/run_promptfoo_multi_agent.py", log, eval_state, extra_env=scope_env)
                    if exit_code != 0:
                        any_failed = True

                if not stopped():
                    eval_state.stage = "Report"
                    log("\n=== Report ===")
                    run_to_log(f"agenteval-report --use-case {selected_uc} --out results/report.html", log, eval_state)

        if stopped():
            log("\n⏹ Abgebrochen.")

        eval_state.any_failed = any_failed
        eval_state.error = error_msg
    except Exception as exc:
        log(f"\n❌ Unerwarteter Fehler in der Web-App: {exc!r}")
        eval_state.error = f"Unerwarteter Fehler: {exc}"
    finally:
        _kill_process_tree(eval_state.current_process)
        eval_state.current_process = None
        eval_state.running = False
        eval_state.stage = None


# run_every wird HIER, bei jedem vollen Skript-Durchlauf, neu aus dem
# aktuellen eval_state.running-Wert berechnet (Streamlit führt app.py bei
# jedem Rerun komplett neu aus – auch diese Decorator-Zeile). Nur während
# eines laufenden Evals tickt das Fragment automatisch (fragment-scoped,
# kein Seiten-Rerun); danach ist run_every=None und es passiert nichts mehr
# von selbst. Vorher lief das per Dauer-run_every=1, das auch im Leerlauf
# jede Sekunde den ganzen Block (inkl. Report-iframe) neu aufgebaut hat –
# das hat jeden manuellen Auf-/Zuklapp-Klick sofort zurückgesetzt (Status/
# Report klappten von selbst zu) und sorgte beim Scrollen für Ruckeln.
_eval_state_for_fragment: EvalState = st.session_state.setdefault("eval_state", EvalState())
_eval_run_every = 1 if _eval_state_for_fragment.running else None


@st.fragment(run_every=_eval_run_every)
def _render_eval_status(selected_uc: str, eval_state: EvalState) -> None:
    running = eval_state.running

    # "Evaluierung starten" & Co. liegen AUSSERHALB dieses Fragments – ein
    # Fragment-Tick aktualisiert nur seinen eigenen Bereich (diese Funktion),
    # nicht die restliche Seite. Ohne diesen Schritt bliebe der Start-Button
    # dauerhaft deaktiviert, weil sein disabled=eval_state.running nur bei
    # einem VOLLEN Seiten-Rerun neu ausgewertet wird. st.rerun() (ohne
    # scope="fragment") erzwingt genau das, sobald der Hintergrund-Thread
    # fertig ist. Diese Prüfung läuft im Hauptthread (Fragment-Tick) und
    # liest hier nur eval_state-Attribute, kein st.session_state[...] – sicher.
    if eval_state.was_running and not running:
        eval_state.was_running = False
        st.rerun()
    eval_state.was_running = running

    has_output = bool(eval_state.log_lines)
    stopped_flag = eval_state.stop_requested

    if running:
        label = f"{eval_state.stage or 'Evaluierung'} läuft ..."
        state = "running"
    elif eval_state.error:
        label = "Smoke-Test fehlgeschlagen"
        state = "error"
    elif stopped_flag and has_output:
        label = "Abgebrochen"
        state = "error"
    elif eval_state.any_failed:
        label = "Abgeschlossen – einzelne Schritte hatten Fehler"
        state = "error"
    elif has_output:
        label = "Evaluierung abgeschlossen"
        state = "complete"
    else:
        label = "Noch keine Evaluierung gestartet"
        state = "complete"

    st.markdown("**Live-Ausführungslog** (Rohausgabe der Skripte/Tests während des Laufs – auf-/zuklappbar, bleibt nach Abschluss erhalten)")
    # expanded nur EINMALIG beim Start/Ende sinnvoll vorbelegen (laufend bzw.
    # bei Fehler offen) – danach steuert ausschließlich der Nutzer per Klick,
    # da dieser Block ohne run_every nicht mehr fortlaufend neu gebaut wird.
    with st.status(label, state=state, expanded=running or state == "error"):
        st.code("\n".join(eval_state.log_lines) or "(noch keine Ausgabe)", language="bash")

    if not running and has_output:
        if eval_state.error:
            st.error(eval_state.error)
        elif stopped_flag:
            st.warning("Evaluierung abgebrochen.")
        elif eval_state.any_failed:
            st.warning("Evaluierung abgeschlossen – einzelne Schritte hatten Fehler. Siehe Log.")
        else:
            st.success("Evaluierung abgeschlossen.")

        report_path = ROOT / "results" / "report.html"
        if report_path.exists():
            report_html = report_path.read_text(encoding="utf-8")
            st.markdown(
                f"**Report** (`results/{report_path.name}`): Vergleichsübersicht aller Agenten "
                "inkl. Radar-Chart, darunter Detailauswertung je Agent."
            )
            st.download_button(
                "Report herunterladen (HTML)",
                data=report_html,
                file_name=f"report_{selected_uc}.html",
                mime="text/html",
                key="download_report_btn",
            )
            with st.expander("Report anzeigen", expanded=False):
                components.html(report_html, height=800, scrolling=True)


# ─── Hauptbereich: Inhalt je nach Sidebar-Auswahl ──────────────────────────

if show_help:
    st.subheader("Hilfe & Dokumentation")
    st.caption("Identisch zur README.md im Projekt-Root – keine doppelt gepflegte Dokumentation.")
    if README_PATH.exists():
        st.markdown(README_PATH.read_text(encoding="utf-8"))
    else:
        st.warning("`README.md` nicht gefunden.")

elif section == "API & Modelle":
    st.subheader("API-Keys & Modelle")
    st.caption("Wird in `.env` im Projekt-Root gespeichert. Felder mit * sind für den Standardlauf nötig.")
    current_env = load_env_values()

    if "agent_key_names" not in st.session_state:
        slots = list_agent_key_slots(current_env)
        st.session_state["agent_key_names"] = slots or ["AGENT_API_KEY_1"]

    st.markdown("**Agent API-Keys**")
    st.caption(
        "Beliebig viele, anbieterunabhängige Keys (egal ob OpenAI, OpenRouter, Azure, ...). "
        'Welcher Key zu welchem Agenten gehört, legst du im Tab "Agenten" fest.'
    )

    agent_key_values: dict[str, str] = {}
    for i, name in enumerate(st.session_state["agent_key_names"]):
        with st.container(border=True):
            kcol, bcol = st.columns([5, 1])
            agent_key_values[name] = kcol.text_input(
                f"Agent API-Key {i + 1}",
                value=current_env.get(name, ""),
                type="password",
                key=f"envfield_{name}",
            )
            bcol.markdown("<div style='margin-top:1.85rem'></div>", unsafe_allow_html=True)
            if bcol.button(
                "Entfernen",
                key=f"remove_{name}",
                disabled=len(st.session_state["agent_key_names"]) <= 1,
            ):
                st.session_state["agent_key_names"].remove(name)
                st.rerun()

    if st.button("+ Weiteren Agent API-Key hinzufügen"):
        st.session_state["agent_key_names"].append(next_agent_key_slot(st.session_state["agent_key_names"]))
        st.rerun()

    st.markdown("")
    with st.container(border=True):
        st.markdown("**Judge** (bewertet alle Evals)")
        judge_values: dict[str, str] = {}
        for key, label, kind, required in JUDGE_ENV_FIELDS:
            display_label = f"{label}{' *' if required else ''}"
            if kind == "password":
                judge_values[key] = st.text_input(display_label, value=current_env.get(key, ""), type="password")
            else:
                judge_values[key] = st.text_input(display_label, value=current_env.get(key, ""))

    if st.button(".env speichern", type="primary"):
        write_env_values(agent_key_values, judge_values)
        st.success("`.env` wurde gespeichert.")

elif section == "Agenten":
    st.subheader("Judge & zu testende Agenten")
    st.caption("Wird in `agents.yaml` im Projekt-Root gespeichert.")
    agents_cfg = load_agents_config()
    judge_cfg = agents_cfg.get("judge", {}) or {}

    with st.container(border=True):
        st.markdown("**Judge-Konfiguration** (bewertet alle Evals)")
        st.caption('Verwendet immer den Judge API-Key aus dem Bereich „API & Modelle" (`JUDGE_API_KEY`).')
        jc1, jc2, jc3 = st.columns(3)
        judge_model = jc1.text_input(
            "Judge-Modell *",
            value=judge_cfg.get("model", ""),
            help='Exakter Modellname für den Endpunkt. Über OpenRouter IMMER mit Anbieter-Präfix, '
                 'z. B. "openai/gpt-oss-120b" – siehe Hinweis zu "Modell" unten bei den Agenten.',
        )
        judge_api_base = jc2.text_input(
            "Judge api_base *",
            value=judge_cfg.get("api_base", "") or "",
            help='Endpunkt-URL. Direkt OpenAI: "https://api.openai.com/v1". '
                 'Über OpenRouter (fast alle anderen Anbieter): "https://openrouter.ai/api/v1".',
        )
        judge_provider_pin = jc3.text_input(
            "Judge provider_pin (optional)",
            value=judge_cfg.get("provider_pin", "") or "",
            help="Nur bei OpenRouter relevant – fixiert den Hosting-Anbieter (z. B. DeepInfra, Google).",
        )
        if not judge_api_base:
            st.caption("⚠ api_base ist Pflicht – auch bei OpenAI (z. B. `https://api.openai.com/v1`).")

    with st.container(border=True):
        st.markdown("**Agenten** (jede Zeile = ein zu testender Agent)")
        agent_key_sources = list_agent_key_slots(load_env_values()) or ["AGENT_API_KEY_1"]
        st.caption(
            'Die API-Key-Quelle wird aus dem Bereich „API & Modelle" ausgewählt – '
            "kein manuelles Eintippen von Variablennamen nötig. "
            f"Verfügbar: {', '.join(agent_key_sources)}. "
            "**api_base ist Pflicht** (auch bei OpenAI). "
            "Bei Unklarheiten: auf das **?** im jeweiligen Spaltenkopf hovern – "
            'Beispielzeile: id=`deepseek-v4-flash`, Anzeigename=`DeepSeek V4 Flash (OpenRouter)`, '
            "Modell=`deepseek/deepseek-v4-flash`, api_base=`https://openrouter.ai/api/v1`."
        )
        agents_list = agents_cfg.get("agents", []) or []
        rows = [
            {
                "id": a.get("id", ""),
                "label": a.get("label", ""),
                "model": a.get("model", ""),
                "api_key_env": a.get("api_key_env") if a.get("api_key_env") in agent_key_sources else agent_key_sources[0],
                "api_base": a.get("api_base", "") or "",
                "provider_pin": a.get("provider_pin", "") or "",
            }
            for a in agents_list
        ]
        edited_rows = st.data_editor(
            rows,
            num_rows="dynamic",
            width="stretch",
            column_config={
                "id": st.column_config.TextColumn(
                    "id",
                    help='Frei wählbare, eindeutige Kurzkennung ohne Leerzeichen, z. B. "deepseek-v4-flash". '
                         "Taucht in den Namen der erzeugten Ergebnis-Dateien auf (z. B. "
                         "results/compliance_results_uc1_deepseek-v4-flash.json) – hat sonst keine technische "
                         "Bedeutung und muss nicht zum Modellnamen passen.",
                ),
                "label": st.column_config.TextColumn(
                    "Anzeigename",
                    help='Frei wählbarer Anzeigename für Report und Vergleichstabelle, z. B. '
                         '"DeepSeek V4 Flash (OpenRouter)". Rein kosmetisch, ändert nichts an der Ausführung. '
                         "Leer lassen -> es wird automatisch die id verwendet.",
                ),
                "model": st.column_config.TextColumn(
                    "Modell",
                    help='Exakter Modellname, wie ihn der Endpunkt erwartet. Läuft der Agent über OpenRouter '
                         '(api_base = openrouter.ai/...), steht IMMER ein Anbieter-Präfix davor, z. B. '
                         '"deepseek/deepseek-v4-flash" oder "google/gemini-2.5-flash-lite" – das ist KEIN '
                         "Ordner, sondern Teil des Modellnamens in OpenRouters Katalog (Anbieter/Modell). "
                         'Bei direktem OpenAI-Zugriff entfällt das Präfix, z. B. nur "gpt-5.4-mini".',
                ),
                "api_key_env": st.column_config.SelectboxColumn(
                    "API-Key-Quelle",
                    help="Welcher in '.env' hinterlegte Key für diesen Agenten verwendet wird.",
                    options=agent_key_sources,
                    default=agent_key_sources[0],
                    required=True,
                ),
                "api_base": st.column_config.TextColumn(
                    "api_base *",
                    help="Der Endpunkt, an den die Anfragen für diesen Agenten geschickt werden. "
                         'Direkt zu OpenAI: "https://api.openai.com/v1". Über OpenRouter (deckt fast alle '
                         'anderen Anbieter ab, z. B. Anthropic/Google/DeepSeek/Llama): '
                         '"https://openrouter.ai/api/v1". Pflichtfeld (auch bei OpenAI), damit nie '
                         "versehentlich ein falscher Standard-Endpunkt verwendet wird.",
                ),
                "provider_pin": st.column_config.TextColumn(
                    "provider_pin (optional)",
                    help="Nur bei OpenRouter relevant (api_base = openrouter.ai/...) – fixiert, welcher "
                         "tatsächliche Hosting-Anbieter hinter dem Modellnamen bedient (z. B. \"DeepInfra\", "
                         '"Google"). Ohne Pin routet OpenRouter je nach Verfügbarkeit an wechselnde Hosts mit '
                         "teils stark unterschiedlichen Preisen für dasselbe Modell.",
                ),
            },
            key="agents_editor",
        )

        # Zusätzlich zu den "?"-Tooltips in den Spaltenköpfen (oben) auch
        # fest sichtbar als Text, ohne dass man dafür hovern muss.
        st.markdown(
            "**Spalten-Erklärung**\n"
            "- **id** – frei wählbare, eindeutige Kurzkennung ohne Leerzeichen, z. B. `deepseek-v4-flash`. "
            "Taucht in den Namen der erzeugten Ergebnis-Dateien auf, hat sonst keine technische Bedeutung "
            "und muss nicht zum Modellnamen passen.\n"
            "- **Anzeigename** – frei wählbarer Name für Report und Vergleichstabelle, z. B. "
            "`DeepSeek V4 Flash (OpenRouter)`. Rein kosmetisch. Leer lassen → es wird automatisch die id verwendet.\n"
            "- **Modell** – exakter Modellname, wie ihn der Endpunkt erwartet. Läuft der Agent über OpenRouter "
            "(api_base = openrouter.ai/...), steht immer ein Anbieter-Präfix davor, z. B. "
            "`deepseek/deepseek-v4-flash` oder `google/gemini-2.5-flash-lite` – das ist **kein Ordner**, "
            "sondern Teil des Modellnamens in OpenRouters Katalog (Anbieter/Modell). Bei direktem "
            "OpenAI-Zugriff entfällt das Präfix, z. B. nur `gpt-5.4-mini`.\n"
            "- **API-Key-Quelle** – welcher der im Bereich „API & Modelle“ hinterlegten Keys für diesen "
            "Agenten verwendet wird (Dropdown, kein Eintippen nötig).\n"
            "- **api_base** *(Pflicht)* – der Endpunkt, an den die Anfragen geschickt werden. Direkt zu "
            "OpenAI: `https://api.openai.com/v1`. Über OpenRouter (deckt fast alle anderen Anbieter ab, "
            "z. B. Anthropic/Google/DeepSeek/Llama): `https://openrouter.ai/api/v1`.\n"
            "- **provider_pin** *(optional)* – nur bei OpenRouter relevant: fixiert, welcher tatsächliche "
            "Hosting-Anbieter hinter dem Modellnamen bedient (z. B. `DeepInfra`, `Google`). Ohne Pin routet "
            "OpenRouter je nach Verfügbarkeit an wechselnde Hosts mit teils stark unterschiedlichen Preisen "
            "für dasselbe Modell."
        )

        if st.button("agents.yaml speichern", type="primary"):
            missing_api_base = [r["id"] for r in edited_rows if r.get("id") and r.get("model") and not r.get("api_base")]
            if not judge_api_base:
                st.error("Judge api_base fehlt – Pflichtfeld, Speichern abgebrochen.")
            elif missing_api_base:
                st.error(f"api_base fehlt bei: {', '.join(missing_api_base)} – Pflichtfeld, Speichern abgebrochen.")
            else:
                judge_out = {"model": judge_model, "api_key_env": "JUDGE_API_KEY", "api_base": judge_api_base}
                if judge_provider_pin:
                    judge_out["provider_pin"] = judge_provider_pin
                agents_out = []
                for row in edited_rows:
                    if not row.get("id") or not row.get("model"):
                        continue
                    entry = {
                        "id": row["id"],
                        "label": row.get("label") or row["id"],
                        "model": row["model"],
                        "api_key_env": row.get("api_key_env") or agent_key_sources[0],
                        "api_base": row["api_base"],
                    }
                    if row.get("provider_pin"):
                        entry["provider_pin"] = row["provider_pin"]
                    agents_out.append(entry)
                save_agents_config(judge_out, agents_out)
                st.success(f"`agents.yaml` gespeichert ({len(agents_out)} Agent(en)).")

elif section == "Use Case & Evaluierung":
    agents_for_run = load_agents_config().get("agents", []) or []
    eval_state: EvalState = st.session_state.setdefault("eval_state", EvalState())

    st.subheader("Use Case auswählen")
    with st.container(border=True):
        uc_index = next((i for i, uc in enumerate(USE_CASES) if uc[0] == DEFAULT_USE_CASE), 0)
        uc_choice = st.selectbox(
            "Use Case",
            options=USE_CASES,
            index=uc_index,
            format_func=lambda uc: uc[1],
            help="Bestimmt Tools/Tasks für Funktionalität sowie die UC-spezifische Security-/Compliance-Suite.",
            disabled=eval_state.running,
        )
        selected_uc, _, uc_description = uc_choice
        st.caption(uc_description)

    st.subheader("Evaluierung")
    with st.container(border=True):
        if not agents_for_run:
            st.warning('Keine Agenten konfiguriert. Im Tab "Agenten" mindestens einen anlegen.')

        st.markdown(f"✓ **{SMOKE_LABEL}**  — *Pflicht, läuft immer zuerst, nicht abwählbar*")
        st.caption(SMOKE_HELP)

        st.markdown("**Weitere Eval-Suiten** (D1, D2, D3 – unabhängig voneinander an-/abwählbar)")
        col1, col2, col3 = st.columns(3)
        with col1:
            func_checked = st.checkbox(
                FUNCTIONALITY_STAGE["label"], value=FUNCTIONALITY_STAGE["default"], help=FUNCTIONALITY_STAGE["help"],
                key="chk_functionality", disabled=eval_state.running,
            )
        with col2:
            security_checked = st.checkbox(
                SECURITY_STAGE["label"], value=SECURITY_STAGE["default"], help=SECURITY_STAGE["help"],
                key="chk_security", disabled=eval_state.running,
            )
        with col3:
            compliance_checked = st.checkbox(
                COMPLIANCE_STAGE["label"], value=COMPLIANCE_STAGE["default"], help=COMPLIANCE_STAGE["help"],
                key="chk_compliance", disabled=eval_state.running,
            )

        # Feste Spalten-Reihe (Start/Stop/Log leeren): bleibt an derselben
        # Stelle, unabhängig davon, wie viele Log-Zeilen dazukommen – anders
        # als zuvor, wo "Stop" INNERHALB der wachsenden Log-Box stand und sich
        # bei jeder neuen Zeile weiter nach unten verschoben hat. Start/Stop
        # bekommen schmale, an den Button-Text angepasste Spalten statt
        # gleich breiter Drittel, damit Stop optisch direkt an Start andockt
        # statt mit großem Leerraum in der Mitte zu stehen.
        # Buttons sind standardmäßig content-breit (width="content"), aber
        # JEDE Spalte beansprucht trotzdem ihren vollen zugewiesenen Anteil –
        # bei zu breiten Spalten bleibt also sichtbarer Leerraum VOR dem
        # nächsten Button stehen. Spalten daher knapp an die Button-Breite
        # angepasst statt grob gleich verteilt, plus minimaler "xxsmall"-Gap.
        run_col, stop_col, _spacer_col, clear_col = st.columns([0.12, 0.07, 0.61, 0.2], gap="xxsmall")
        any_suite_checked = func_checked or security_checked or compliance_checked
        start_clicked = run_col.button(
            "Evaluierung starten",
            type="primary",
            disabled=not agents_for_run or eval_state.running,
            help="Der Smoke-Test läuft immer, auch wenn alle drei Suiten unten abgewählt sind." if not any_suite_checked else None,
        )
        if eval_state.running:
            if stop_col.button("⏹ Stop", key="stop_eval_btn"):
                eval_state.stop_requested = True
                _kill_process_tree(eval_state.current_process)
        if clear_col.button("Log leeren", disabled=eval_state.running):
            eval_state.log_lines = []
            st.rerun()

        if start_clicked:
            eval_state.log_lines = []
            eval_state.stop_requested = False
            eval_state.any_failed = False
            eval_state.error = None
            eval_state.running = True
            thread = threading.Thread(
                target=_run_evaluation,
                args=(eval_state, selected_uc, func_checked, security_checked, compliance_checked),
                daemon=True,
            )
            add_script_run_ctx(thread)
            thread.start()
            st.session_state["eval_thread"] = thread
            st.rerun()

        _render_eval_status(selected_uc, eval_state)
