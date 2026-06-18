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

Ausgabe-Dateien pro (Use Case, Agent):
  security_results_{uc}_{agent_id}.json      (generic + uc_specific gemerged)
  compliance_results_{uc}_{agent_id}.json    (generic + uc_specific gemerged)
  compliance_scorecard_{uc}_{agent_id}.json

Aufruf:
  USE_CASE=uc2 python scripts/run_promptfoo_multi_agent.py
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).parent.parent

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


def load_agents() -> list[dict]:
    with open(ROOT / "agents.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)["agents"]


def _agent_env(agent: dict) -> dict:
    env = os.environ.copy()
    env["OPENAI_API_KEY"] = os.environ.get(agent["api_key_env"], "")
    env["MODEL_NAME"]     = agent["model"]
    api_base = agent.get("api_base") or ""
    if api_base:
        env["OPENAI_BASE_URL"] = api_base
    else:
        env.pop("OPENAI_BASE_URL", None)
    return env


def _promptfoo_results(data: dict) -> list[dict]:
    return data.get("results", {}).get("results", data.get("results", []))


def run_one(agent: dict, config: str, scope: str) -> tuple[list[dict], bool]:
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
    tmp_out  = ROOT / f"_tmp_{Path(config).stem}_{agent_id}.json"

    cmd = [
        "npx", "promptfoo@latest", "eval", "--no-cache",
        "--config", str(config_path),
        "--output", str(tmp_out),
    ]
    print(f"\n▶  {USE_CASE} | {agent['label']!r} | {Path(config).name}  (scope={scope})")
    result = subprocess.run(cmd, env=_agent_env(agent))

    results: list[dict] = []
    if tmp_out.exists():
        try:
            data = json.loads(tmp_out.read_text(encoding="utf-8"))
            for r in _promptfoo_results(data):
                if not r:
                    continue
                meta = r.setdefault("testCase", {}).setdefault("metadata", {})
                meta.setdefault("scope", scope)
                results.append(r)
        finally:
            tmp_out.unlink(missing_ok=True)

    return results, result.returncode == 0


def write_merged(results: list[dict], output: str) -> None:
    """Schreibt zusammengeführte Ergebnisse im promptfoo-Schema (results.results)."""
    payload = {"results": {"results": results}}
    (ROOT / output).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    n_gen = sum(1 for r in results if r.get("testCase", {}).get("metadata", {}).get("scope") == "generic")
    n_uc  = len(results) - n_gen
    print(f"   → {output}: {len(results)} Tests gemerged (generic={n_gen}, uc_specific={n_uc})")


def run_scorecard(agent_id: str) -> None:
    """Erzeugt compliance_scorecard_{uc}_{agent_id}.json aus der gemergten Datei."""
    compliance_file = f"compliance_results_{USE_CASE}_{agent_id}.json"
    if not (ROOT / compliance_file).exists():
        print(f"⚠  Scorecard übersprungen – {compliance_file} nicht gefunden")
        return
    subprocess.run(["agenteval-scorecard", str(ROOT / compliance_file), "--use-case", USE_CASE])


def main() -> None:
    agents = load_agents()
    failed: list[str] = []

    print(f"\n🎯  Use Case: {USE_CASE}  ({_UC_DIR})")

    for agent in agents:
        for prefix in ("security_results", "compliance_results"):
            merged: list[dict] = []
            # 1) Generische Baseline (scope: generic)
            for cfg in BASELINE[prefix]:
                res, ok = run_one(agent, cfg, "generic")
                merged += res
                if not ok:
                    failed.append(f"{agent['id']} / {Path(cfg).name}")
            # 2) UC-spezifische Suite (scope: uc_specific)
            uc_cfg = UC_SUITES[prefix]
            res, ok = run_one(agent, uc_cfg, "uc_specific")
            merged += res
            if not ok:
                failed.append(f"{agent['id']} / {Path(uc_cfg).name}")

            write_merged(merged, f"{prefix}_{USE_CASE}_{agent['id']}.json")

        run_scorecard(agent["id"])

    if failed:
        print(f"\n⚠  Fehlgeschlagen: {', '.join(failed)}")
        sys.exit(1)

    print(f"\n✅  Alle promptfoo-Evals für {USE_CASE} abgeschlossen.")


if __name__ == "__main__":
    main()
