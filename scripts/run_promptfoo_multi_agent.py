"""
Führt alle promptfoo Security- und Compliance-Evals für jeden Agenten
in agents.yaml durch – für den gewählten Use Case (USE_CASE env, Default uc1).

Verwendet die UC-spezifischen YAML-Configs:
  evals/security/usecases/{uc}/security_eval.yaml
  evals/security/usecases/{uc}/security_eval_finance.yaml   (falls vorhanden)
  evals/compliance/usecases/{uc}/compliance_eval.yaml

Ausgabe-Dateien pro (Use Case, Agent):
  security_results_{uc}_{agent_id}.json
  security_finance_results_{uc}_{agent_id}.json
  compliance_results_{uc}_{agent_id}.json
  compliance_scorecard_{uc}_{agent_id}.json

Aufruf:
  USE_CASE=uc2 python scripts/run_promptfoo_multi_agent.py
"""

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
    "uc1": "uc1_suitability",
    "uc2": "uc2_onboarding",
    "uc3": "uc3_compliance_triage",
    "uc4": "uc4_beratungsdoku",
}
_UC_DIR = _UC_DIR_MAP.get(USE_CASE, "uc1_suitability")

# (config-Pfad, output-Prefix) – UC-spezifisch
EVALS = [
    (f"evals/security/usecases/{_UC_DIR}/security_eval.yaml",          "security_results"),
    (f"evals/security/usecases/{_UC_DIR}/security_eval_finance.yaml",  "security_finance_results"),
    (f"evals/compliance/usecases/{_UC_DIR}/compliance_eval.yaml",      "compliance_results"),
]


def load_agents() -> list[dict]:
    with open(ROOT / "agents.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)["agents"]


def run_promptfoo(agent: dict, config: str, output_prefix: str) -> bool:
    """Führt einen promptfoo-Eval für einen Agenten durch."""
    config_path = ROOT / config
    if not config_path.exists():
        print(f"ℹ  Übersprungen – {config} existiert nicht für {USE_CASE}")
        return True  # nicht als Fehler werten (z.B. fehlendes security_finance)

    agent_id = agent["id"]
    api_key  = os.environ.get(agent["api_key_env"], "")
    api_base = agent.get("api_base") or ""
    model    = agent["model"]
    output   = f"{output_prefix}_{USE_CASE}_{agent_id}.json"

    env = os.environ.copy()
    env["OPENAI_API_KEY"] = api_key
    env["MODEL_NAME"]     = model
    if api_base:
        env["OPENAI_BASE_URL"] = api_base
    else:
        env.pop("OPENAI_BASE_URL", None)

    cmd = [
        "npx", "promptfoo@latest", "eval", "--no-cache",
        "--config", str(config_path),
        "--output", output,
    ]

    print(f"\n▶  {USE_CASE} | Agent: {agent['label']!r} | {Path(config).name} → {output}")
    result = subprocess.run(cmd, env=env)
    return result.returncode == 0


def run_scorecard(agent_id: str) -> None:
    """Erzeugt compliance_scorecard_{uc}_{agent_id}.json."""
    compliance_file = f"compliance_results_{USE_CASE}_{agent_id}.json"
    if not Path(compliance_file).exists():
        print(f"⚠  Scorecard übersprungen – {compliance_file} nicht gefunden")
        return
    subprocess.run(["agenteval-scorecard", compliance_file, "--use-case", USE_CASE])


def main() -> None:
    agents = load_agents()
    failed: list[str] = []

    print(f"\n🎯  Use Case: {USE_CASE}  ({_UC_DIR})")

    for agent in agents:
        for config, prefix in EVALS:
            ok = run_promptfoo(agent, config, prefix)
            if not ok:
                failed.append(f"{agent['id']} / {prefix}")

        run_scorecard(agent["id"])

    if failed:
        print(f"\n⚠  Fehlgeschlagen: {', '.join(failed)}")
        sys.exit(1)

    print(f"\n✅  Alle promptfoo-Evals für {USE_CASE} abgeschlossen.")


if __name__ == "__main__":
    main()
