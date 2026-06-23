"""
R0 – Smoke-Test für Judge + alle Agenten aus agents.yaml.

Prüft mit einem einzigen Hello-World-Prompt (promptfooconfig.yaml), ob jeder
konfigurierte Endpunkt erreichbar ist und einen gültigen API-Key hat – bevor
die teuren D1/D2/D3-Evals starten. Schlägt der Smoke-Test für irgendeinen
Eintrag fehl (falscher Key, kein Guthaben, falscher Endpunkt), bricht das
Skript mit Exit-Code 1 ab. In CI führt das dazu, dass R2/R3, D1 und der
Report (außer dem finalen Report-Schritt mit `if: always()`) nicht mehr
laufen – ein kaputter Agent soll den Rest der Pipeline nicht verschleiern.

Judge + alle Agenten werden parallel geprüft (ThreadPoolExecutor) statt
nacheinander – jeder Check ist ein unabhängiger Subprozess ohne
Datenabhängigkeit zu den anderen.

Aufruf:
  python scripts/run_smoke_test.py
"""

import concurrent.futures
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from dotenv import load_dotenv

from agenteval_ovb.agents_config import load_agents_config, require_api_base
from agenteval_ovb.promptfoo_utils import DEFAULT_MAX_CONCURRENCY, PROMPTFOO_VERSION

ROOT = Path(__file__).parent.parent

# .env laden (lokal nötig – in CI kommen die Secrets bereits als Env-Variablen).
load_dotenv(ROOT / ".env")


def _entry_env(model: str, api_key_env: str, api_base: str) -> dict:
    env = os.environ.copy()
    env["OPENAI_API_KEY"]  = os.environ.get(api_key_env, "")
    env["MODEL_NAME"]      = model
    env["OPENAI_BASE_URL"] = api_base
    return env


def run_smoke(label: str, model: str, api_key_env: str, api_base: str) -> bool:
    print(f"\n▶  Smoke-Test: {label}  (Modell: {model}, Endpunkt: {api_base})")
    env = _entry_env(model, api_key_env, api_base)
    # Eigenes, isoliertes PROMPTFOO_CONFIG_DIR pro Job: promptfoo schreibt jeden
    # Lauf zusätzlich in eine lokale SQLite-Verlaufs-DB (Default ~/.promptfoo) –
    # bei den hier parallel laufenden Jobs (Judge + alle Agenten gleichzeitig)
    # führte das zu echten "SQLITE_BUSY: database is locked"-Fehlern (siehe
    # run_promptfoo_multi_agent.py für denselben, dort bereits behobenen Bug).
    pf_config_dir = Path(tempfile.mkdtemp(prefix=f"promptfoo_smoke_{label.replace(' ', '_')}_"))
    env["PROMPTFOO_CONFIG_DIR"] = str(pf_config_dir)
    try:
        result = subprocess.run(
            [
                "npx", f"promptfoo@{PROMPTFOO_VERSION}", "eval", "--no-cache",
                "--max-concurrency", str(DEFAULT_MAX_CONCURRENCY),
                "--config", "promptfooconfig.yaml",
            ],
            env=env, cwd=ROOT,
        )
    finally:
        shutil.rmtree(pf_config_dir, ignore_errors=True)
    return result.returncode == 0


def main() -> None:
    config = load_agents_config()
    failed: list[str] = []

    entries: list[tuple[str, str, str, str]] = []  # (label, model, api_key_env, api_base)

    judge = config.get("judge") or {}
    if judge:
        entries.append(("Judge", judge["model"], judge["api_key_env"], require_api_base(judge, "judge")))

    for agent in config.get("agents", []):
        entries.append((
            agent["label"], agent["model"], agent["api_key_env"],
            require_api_base(agent, f"Agent '{agent.get('id', '?')}'"),
        ))

    with concurrent.futures.ThreadPoolExecutor(max_workers=len(entries) or 1) as executor:
        future_to_label = {executor.submit(run_smoke, *entry): entry[0] for entry in entries}
        for future in concurrent.futures.as_completed(future_to_label):
            label = future_to_label[future]
            if not future.result():
                failed.append(label)

    if failed:
        print(f"\n❌  Smoke-Test fehlgeschlagen für: {', '.join(failed)}")
        sys.exit(1)

    print("\n✅  Alle Smoke-Tests erfolgreich (Judge + alle Agenten erreichbar).")


if __name__ == "__main__":
    main()
