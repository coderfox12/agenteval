"""
Führt alle promptfoo Security- und Compliance-Evals für jeden Agenten
in agents.yaml durch und erzeugt pro Agent separate Ergebnisdateien.

Ausgabe-Dateien pro Agent:
  security_results_{agent_id}.json
  security_finance_results_{agent_id}.json
  compliance_results_{agent_id}.json
  compliance_scorecard_{agent_id}.json

Aufruf:
  python scripts/run_promptfoo_multi_agent.py
"""

import os
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).parent.parent

EVALS = [
    ("evals/security/security_eval.yaml",         "security_results"),
    ("evals/security/security_eval_finance.yaml",  "security_finance_results"),
    ("evals/compliance/compliance_eval.yaml",       "compliance_results"),
]


def load_agents() -> list[dict]:
    with open(ROOT / "agents.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)["agents"]


def run_promptfoo(agent: dict, config: str, output_prefix: str) -> bool:
    """Führt einen promptfoo-Eval für einen Agenten durch."""
    agent_id = agent["id"]
    api_key  = os.environ.get(agent["api_key_env"], "")
    api_base = agent.get("api_base") or ""
    model    = agent["model"]
    output   = f"{output_prefix}_{agent_id}.json"

    env = os.environ.copy()
    env["OPENAI_API_KEY"] = api_key
    env["MODEL_NAME"]     = model
    if api_base:
        env["OPENAI_BASE_URL"] = api_base
    else:
        env.pop("OPENAI_BASE_URL", None)

    cmd = [
        "npx", "promptfoo@latest", "eval", "--no-cache",
        "--config", str(ROOT / config),
        "--output", output,
    ]

    print(f"\n▶  Agent: {agent['label']!r} | {Path(config).name} → {output}")
    result = subprocess.run(cmd, env=env)
    return result.returncode == 0


def run_scorecard(agent_id: str) -> None:
    """Erzeugt compliance_scorecard_{agent_id}.json."""
    compliance_file = f"compliance_results_{agent_id}.json"
    if not Path(compliance_file).exists():
        print(f"⚠  Scorecard übersprungen – {compliance_file} nicht gefunden")
        return
    subprocess.run(["agenteval-scorecard", compliance_file])


def main() -> None:
    agents = load_agents()
    failed: list[str] = []

    for agent in agents:
        for config, prefix in EVALS:
            ok = run_promptfoo(agent, config, prefix)
            if not ok:
                failed.append(f"{agent['id']} / {prefix}")

        run_scorecard(agent["id"])

    if failed:
        print(f"\n⚠  Fehlgeschlagen: {', '.join(failed)}")
        sys.exit(1)

    print("\n✅  Alle promptfoo-Evals abgeschlossen.")


if __name__ == "__main__":
    main()
