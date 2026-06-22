"""
R0 – Smoke-Test für Judge + alle Agenten aus agents.yaml.

Prüft mit einem einzigen Hello-World-Prompt (promptfooconfig.yaml), ob jeder
konfigurierte Endpunkt erreichbar ist und einen gültigen API-Key hat – bevor
die teuren D1/D2/D3-Evals starten. Schlägt der Smoke-Test für irgendeinen
Eintrag fehl (falscher Key, kein Guthaben, falscher Endpunkt), bricht das
Skript mit Exit-Code 1 ab. In CI führt das dazu, dass R2/R3, D1 und der
Report (außer dem finalen Report-Schritt mit `if: always()`) nicht mehr
laufen – ein kaputter Agent soll den Rest der Pipeline nicht verschleiern.

Aufruf:
  python scripts/run_smoke_test.py
"""

import os
import subprocess
import sys
from pathlib import Path

import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).parent.parent

# .env laden (lokal nötig – in CI kommen die Secrets bereits als Env-Variablen).
load_dotenv(ROOT / ".env")


def load_config() -> dict:
    with open(ROOT / "agents.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _entry_env(model: str, api_key_env: str, api_base: str) -> dict:
    env = os.environ.copy()
    env["OPENAI_API_KEY"]  = os.environ.get(api_key_env, "")
    env["MODEL_NAME"]      = model
    env["OPENAI_BASE_URL"] = api_base
    return env


def run_smoke(label: str, model: str, api_key_env: str, api_base: str) -> bool:
    print(f"\n▶  Smoke-Test: {label}  (Modell: {model}, Endpunkt: {api_base})")
    env = _entry_env(model, api_key_env, api_base)
    result = subprocess.run(
        ["npx", "promptfoo@latest", "eval", "--no-cache", "--config", "promptfooconfig.yaml"],
        env=env, cwd=ROOT,
    )
    return result.returncode == 0


def main() -> None:
    config = load_config()
    failed: list[str] = []

    judge = config.get("judge") or {}
    if judge:
        ok = run_smoke("Judge", judge["model"], judge["api_key_env"], judge["api_base"])
        if not ok:
            failed.append("Judge")

    for agent in config.get("agents", []):
        ok = run_smoke(agent["label"], agent["model"], agent["api_key_env"], agent["api_base"])
        if not ok:
            failed.append(agent["label"])

    if failed:
        print(f"\n❌  Smoke-Test fehlgeschlagen für: {', '.join(failed)}")
        sys.exit(1)

    print("\n✅  Alle Smoke-Tests erfolgreich (Judge + alle Agenten erreichbar).")


if __name__ == "__main__":
    main()
