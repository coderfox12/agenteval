"""
Führt alle promptfoo Security- und Compliance-Evals für jeden Agenten
in agents.yaml durch – für den gewählten Use Case (USE_CASE env, Default uc1).

Zweischichtige Struktur:
  • GENERISCHE BASELINE (scope: generic) – läuft bei JEDEM Use Case mit und ist
    damit UC-übergreifend vergleichbar:
      evals/security/security_eval.yaml
      evals/security/security_eval_finance.yaml
      evals/compliance/compliance_eval.yaml
  • UC-SPEZIFISCH (scope: uc_specific) – szenariospezifisch:
      evals/security/usecases/{uc}/security_eval.yaml
      evals/compliance/usecases/{uc}/compliance_eval.yaml

Baseline und UC-Suite werden getrennt ausgeführt und anschließend pro Dimension
in EINE Ergebnisdatei zusammengeführt – jeder Test mit metadata.scope. Dadurch
bleiben Report und Scorecard unverändert (sie lesen die Standard-Dateinamen).

Ausgabe-Dateien pro (Use Case, Agent), alle in results/:
  results/security_results_{uc}_{agent_id}.json      (generic + uc_specific gemerged)
  results/compliance_results_{uc}_{agent_id}.json    (generic + uc_specific gemerged)
  results/compliance_scorecard_{uc}_{agent_id}.json

Aufruf:
  USE_CASE=uc2 python scripts/run_promptfoo_multi_agent.py
"""

import concurrent.futures
import json
import os
import shutil
import subprocess
import sys
import tempfile
from collections import defaultdict
from pathlib import Path

from dotenv import load_dotenv

from agenteval_ovb.agents_config import load_agents_config, provider_pin_extra_body, require_api_base
from agenteval_ovb.pricing import validate_agents_config
from agenteval_ovb.promptfoo_utils import (
    DEFAULT_MAX_CONCURRENCY,
    PROMPTFOO_VERSION,
    extract_promptfoo_results,
)

ROOT = Path(__file__).parent.parent
RESULTS_DIR = ROOT / "results"
RESULTS_DIR.mkdir(exist_ok=True)

# .env laden (lokal nötig – in CI kommen die Secrets bereits als Env-Variablen).
load_dotenv(ROOT / ".env")

# subprocess.run(["npx", ...]) ohne shell=True findet unter Windows nur
# "npx.exe", nicht das tatsächlich installierte "npx.cmd" (FileNotFoundError /
# WinError 2) – auf Linux/macOS (z.B. CI) kein Unterschied. shutil.which löst
# das plattformrichtig über PATHEXT auf.
NPX = shutil.which("npx") or "npx"

# Use Case aus Umgebungsvariable (Default uc1)
USE_CASE = os.environ.get("USE_CASE", "uc1")

# UC-Ordner-Mapping (uc1 → uc1_suitability usw.)
_UC_DIR_MAP = {
    "uc0": "uc0_generic",
    "uc1": "uc1_suitability",
    "uc2": "uc2_onboarding",
    "uc3": "uc3_compliance_triage",
    "uc4": "uc4_beratungsdoku",
}
_UC_DIR = _UC_DIR_MAP.get(USE_CASE, "uc1_suitability")

# Generische Baseline – läuft bei jedem UC mit (scope: generic)
BASELINE = {
    "security_results": [
        "evals/security/security_eval.yaml",
        "evals/security/security_eval_finance.yaml",
    ],
    "compliance_results": [
        "evals/compliance/compliance_eval.yaml",
    ],
}

# UC-spezifische Suiten (scope: uc_specific)
UC_SUITES = {
    "security_results":   f"evals/security/usecases/{_UC_DIR}/security_eval.yaml",
    "compliance_results": f"evals/compliance/usecases/{_UC_DIR}/compliance_eval.yaml",
}

# D2 (Sicherheit) und D3 (Compliance) einzeln abwählbar machen, ohne den
# Default zu ändern: RUN_SECURITY/RUN_COMPLIANCE sind in CI und beim
# direkten Terminal-Aufruf nie gesetzt, also bleiben beide an ("1") – nur
# die Web-App setzt sie gezielt auf "0", wenn der Nutzer eine der beiden
# Suiten abwählt.
_PREFIX_ENABLED = {
    "security_results":   os.environ.get("RUN_SECURITY", "1") != "0",
    "compliance_results": os.environ.get("RUN_COMPLIANCE", "1") != "0",
}
ACTIVE_PREFIXES = [p for p in ("security_results", "compliance_results") if _PREFIX_ENABLED[p]]


def _validate_pricing(config: dict) -> None:
    """Bricht vor dem ersten promptfoo-Call ab, statt API-Budget für einen Lauf
    zu verbrauchen, dessen Wirtschaftlichkeits-Zahlen anschließend ohnehin
    nicht berechnet werden könnten (fehlender Preis in pricing.py)."""
    try:
        validate_agents_config(config)
    except ValueError as exc:
        print(f"❌ {exc}")
        sys.exit(1)


def _agent_env(agent: dict, judge: dict) -> dict:
    agent_base = require_api_base(agent, f"Agent '{agent.get('id', '?')}'")
    judge_base = require_api_base(judge, "judge")
    env = os.environ.copy()
    env["OPENAI_API_KEY"]  = os.environ.get(agent["api_key_env"], "")
    env["MODEL_NAME"]      = agent["model"]
    env["OPENAI_BASE_URL"] = agent_base
    # Judge-Credentials separat, eigene Env-Variablen-Namen – die Eval-YAMLs
    # nutzen sie für defaultTest.options.provider, damit das Grading über den
    # konfigurierten Judge läuft statt über den gerade getesteten Agenten.
    env["JUDGE_MODEL_NAME"]      = judge["model"]
    env["JUDGE_OPENAI_API_KEY"]  = os.environ.get(judge["api_key_env"], "")
    env["JUDGE_OPENAI_BASE_URL"] = judge_base
    # provider_pin (falls in agents.yaml gesetzt) als JSON für die
    # passthrough-Config in den Eval-YAMLs – fixiert den OpenRouter-Anbieter,
    # damit die Kosten in pricing.py exakt stimmen (siehe provider_pin_extra_body).
    env["MODEL_PASSTHROUGH_JSON"] = json.dumps(provider_pin_extra_body(agent))
    env["JUDGE_PASSTHROUGH_JSON"] = json.dumps(provider_pin_extra_body(judge))
    return env


def run_one(agent: dict, judge: dict, config: str, scope: str) -> tuple[list[dict], bool]:
    """Führt einen promptfoo-Eval aus und gibt (results, ok) zurück.

    Jeder Ergebnis-Datensatz erhält metadata.scope (nur falls noch nicht gesetzt –
    UC-Tests bzw. kuratierte Baseline-Tests bringen ihren scope selbst mit).
    Fehlt die Config (z. B. keine UC-Suite für diesen UC), wird sie übersprungen.
    """
    config_path = ROOT / config
    if not config_path.exists():
        print(f"ℹ  Übersprungen – {config} existiert nicht für {USE_CASE}")
        return [], True

    agent_id = agent["id"]
    # Voller (sanitierter) Pfad statt nur Path.stem: Baseline- und UC-Suite
    # heißen oft gleich (z.B. beide "security_eval.yaml" in verschiedenen
    # Ordnern) – bei paralleler Ausführung für denselben Agenten würde der
    # reine Stem zu einer Temp-Datei-Kollision führen.
    safe_name = config.replace("/", "_").replace("\\", "_").removesuffix(".yaml")
    tmp_out   = ROOT / f"_tmp_{safe_name}_{agent_id}.json"

    # Eigenes, isoliertes PROMPTFOO_CONFIG_DIR pro Job: promptfoo schreibt
    # JEDEN Testlauf zusätzlich in eine lokale SQLite-DB (promptfoo.db) im
    # Config-Verzeichnis (Default: ~/.promptfoo) – bei mehreren parallelen
    # npx-Prozessen, die alle in dieselbe Datei schreiben, kam es zu echten
    # "Failed query: insert into eval_results" Fehlern (SQLite-Lock unter
    # Nebenläufigkeit), wodurch einzelne Testergebnisse stillschweigend
    # verloren gingen – in der Praxis beobachtet: 102 erwartete Security-
    # Tests wurden zu inkonsistent 57/87 zwischen den beiden Agenten. Mit
    # --no-cache wird nur der API-Response-Cache deaktiviert, NICHT diese
    # History-DB. Eigenes Verzeichnis pro Job umgeht den Konflikt komplett.
    pf_config_dir = Path(tempfile.mkdtemp(prefix=f"promptfoo_{safe_name}_{agent_id}_"))

    cmd = [
        NPX, f"promptfoo@{PROMPTFOO_VERSION}", "eval", "--no-cache",
        "--max-concurrency", str(DEFAULT_MAX_CONCURRENCY),
        "--config", str(config_path),
        "--output", str(tmp_out),
    ]
    print(f"\n▶  {USE_CASE} | {agent['label']!r} | {Path(config).name}  (scope={scope})")
    env = _agent_env(agent, judge)
    env["PROMPTFOO_CONFIG_DIR"] = str(pf_config_dir)
    try:
        result = subprocess.run(cmd, env=env)
    finally:
        shutil.rmtree(pf_config_dir, ignore_errors=True)

    results: list[dict] = []
    if tmp_out.exists():
        try:
            data = json.loads(tmp_out.read_text(encoding="utf-8"))
            for r in extract_promptfoo_results(data):
                if not r:
                    continue
                meta = r.setdefault("testCase", {}).setdefault("metadata", {})
                meta.setdefault("scope", scope)
                results.append(r)
        finally:
            tmp_out.unlink(missing_ok=True)

    # NICHT result.returncode == 0 verwenden: promptfoo gibt bewusst exit
    # code 1 zurück, wenn TESTS fehlschlagen (z.B. ein Security-Test zeigt,
    # dass sich der Agent jailbreaken ließ) – das ist bei uns das ERWARTETE,
    # interessante Auswertungsergebnis, kein Skript-/Infrastrukturfehler.
    # "ok" bedeutet hier: hat der Prozess überhaupt verwertbare Ergebnisse
    # geliefert? Nur ein leeres/fehlendes Output-File (Crash, Auth-Fehler vor
    # dem ersten Call usw.) gilt als echter Fehlschlag.
    ok = len(results) > 0
    return results, ok


def write_merged(results: list[dict], output: str) -> None:
    """Schreibt zusammengeführte Ergebnisse im promptfoo-Schema (results.results)."""
    payload = {"results": {"results": results}}
    (RESULTS_DIR / output).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    n_gen = sum(1 for r in results if r.get("testCase", {}).get("metadata", {}).get("scope") == "generic")
    n_uc  = len(results) - n_gen
    print(f"   → {output}: {len(results)} Tests gemerged (generic={n_gen}, uc_specific={n_uc})")


def run_scorecard(agent_id: str) -> None:
    """Erzeugt compliance_scorecard_{uc}_{agent_id}.json aus der gemergten Datei."""
    compliance_file = f"compliance_results_{USE_CASE}_{agent_id}.json"
    if not (RESULTS_DIR / compliance_file).exists():
        print(f"⚠  Scorecard übersprungen – {compliance_file} nicht gefunden")
        return
    subprocess.run(["agenteval-scorecard", str(RESULTS_DIR / compliance_file), "--use-case", USE_CASE])


def main() -> None:
    config = load_agents_config()
    _validate_pricing(config)
    agents = config["agents"]
    judge  = config["judge"]
    failed: list[str] = []

    print(f"\n🎯  Use Case: {USE_CASE}  ({_UC_DIR})")

    if not ACTIVE_PREFIXES:
        print("ℹ  Weder RUN_SECURITY noch RUN_COMPLIANCE aktiv – nichts zu tun.")
        return

    # Alle (Agent, Config)-Kombinationen sammeln und parallel ausführen. Jeder
    # promptfoo-Aufruf ist ein eigener Subprozess (echte OS-Parallelität, kein
    # GIL-Thema) und schreibt dank des vollen sanitierten Pfads in run_one()
    # in eine eigene Temp-Datei – es gibt weder eine Datenabhängigkeit
    # zwischen den Jobs noch ein Race auf gemeinsame Dateien.
    jobs: list[tuple[dict, str, str, str]] = []  # (agent, prefix, cfg, scope)
    for agent in agents:
        for prefix in ACTIVE_PREFIXES:
            for cfg in BASELINE[prefix]:
                jobs.append((agent, prefix, cfg, "generic"))
            jobs.append((agent, prefix, UC_SUITES[prefix], "uc_specific"))

    merged_by_agent_prefix: dict[tuple[str, str], list[dict]] = defaultdict(list)
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(jobs)) as executor:
        future_to_job = {
            executor.submit(run_one, agent, judge, cfg, scope): (agent, prefix, cfg)
            for agent, prefix, cfg, scope in jobs
        }
        for future in concurrent.futures.as_completed(future_to_job):
            agent, prefix, cfg = future_to_job[future]
            res, ok = future.result()
            merged_by_agent_prefix[(agent["id"], prefix)] += res
            if not ok:
                failed.append(f"{agent['id']} / {Path(cfg).name}")

    for agent in agents:
        for prefix in ACTIVE_PREFIXES:
            write_merged(merged_by_agent_prefix[(agent["id"], prefix)], f"{prefix}_{USE_CASE}_{agent['id']}.json")
        if "compliance_results" in ACTIVE_PREFIXES:
            run_scorecard(agent["id"])

    if failed:
        print(f"\n⚠  Fehlgeschlagen: {', '.join(failed)}")
        sys.exit(1)

    print(f"\n✅  Alle promptfoo-Evals für {USE_CASE} abgeschlossen.")


if __name__ == "__main__":
    main()
