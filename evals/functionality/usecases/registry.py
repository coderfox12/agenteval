"""
Use-Case-Registry für den Agent-Eval@OVB-Framework.

Wähle einen Use Case über die Umgebungsvariable USE_CASE (Default: uc1).
Beispiel: USE_CASE=uc2 make functionality

Jeder UC-Eintrag enthält:
  name        – Anzeigename für Reports
  loader      – Lazy-Import-Funktion → (tools, system_prompt)
  tasks_path  – Pfad zur tasks.yaml
  metrics     – Metrik-Schlüssel, die für diesen UC laufen
               (Mapping auf DeepEval-Klassen liegt im Runner test_functionality.py)
"""

import os
from pathlib import Path

_HERE = Path(__file__).parent


def _uc1():
    from .uc1_suitability.tools import TOOLS
    from .uc1_suitability.prompt import SYSTEM_PROMPT
    return TOOLS, SYSTEM_PROMPT


def _uc2():
    from .uc2_onboarding.tools import TOOLS
    from .uc2_onboarding.prompt import SYSTEM_PROMPT
    return TOOLS, SYSTEM_PROMPT


def _uc3():
    from .uc3_compliance_triage.tools import TOOLS
    from .uc3_compliance_triage.prompt import SYSTEM_PROMPT
    return TOOLS, SYSTEM_PROMPT


def _uc4():
    from .uc4_beratungsdoku.tools import TOOLS
    from .uc4_beratungsdoku.prompt import SYSTEM_PROMPT
    return TOOLS, SYSTEM_PROMPT


USE_CASES: dict = {
    "uc1": {
        "name": "Suitability-Check (IDD Art. 30 / §7 VersVermV)",
        "loader": _uc1,
        "tasks_path": _HERE / "uc1_suitability" / "tasks.yaml",
        "uc_metrics": ["tool_correctness", "answer_relevancy"],  # + Kern: task_completion
    },
    "uc2": {
        "name": "Onboarding (KYC / GwG / AMLA)",
        "loader": _uc2,
        "tasks_path": _HERE / "uc2_onboarding" / "tasks.yaml",
        "uc_metrics": ["tool_correctness", "answer_relevancy"],  # + Kern: task_completion
    },
    "uc3": {
        "name": "Compliance-Triage (EU AI Act / OVB-Governance)",
        "loader": _uc3,
        "tasks_path": _HERE / "uc3_compliance_triage" / "tasks.yaml",
        # faithfulness statt answer_relevancy – Zitationstreue ist für RAG/Regulatorik zentral
        "uc_metrics": ["tool_correctness", "faithfulness"],  # + Kern: task_completion
    },
    "uc4": {
        "name": "Beratungsdokumentation (§61 VVG)",
        "loader": _uc4,
        "tasks_path": _HERE / "uc4_beratungsdoku" / "tasks.yaml",
        # hallucination + required_fields statt tool_correctness – Generierungs-UC
        "uc_metrics": ["hallucination", "required_fields"],  # + Kern: task_completion
    },
}

DEFAULT_USE_CASE = "uc1"

# Kern-Metrik(en): laufen in JEDEM Use Case und sind damit UC-übergreifend
# vergleichbar. Die UC-spezifischen Metriken (uc_metrics) ergänzen sie je nach
# fachlichem Schwerpunkt (z. B. faithfulness für RAG-UC3, hallucination für
# Generierungs-UC4). Effektives Metrik-Set = CORE_METRICS + uc_metrics.
CORE_METRICS = ["task_completion"]


def get_use_case(uc_id: str | None = None) -> dict:
    """
    Gibt die vollständige UC-Konfiguration zurück (tools, system_prompt, tasks_path, metrics).

    Auflösungsreihenfolge: Argument → USE_CASE-Env → DEFAULT_USE_CASE.
    """
    uc_id = (uc_id or os.environ.get("USE_CASE") or DEFAULT_USE_CASE).lower()
    if uc_id not in USE_CASES:
        raise ValueError(
            f"Unbekannter USE_CASE '{uc_id}'. Gültige Werte: {list(USE_CASES)}"
        )
    spec = USE_CASES[uc_id]
    tools, system_prompt = spec["loader"]()
    uc_metrics = list(spec["uc_metrics"])
    return {
        "id": uc_id,
        "name": spec["name"],
        "tools": tools,
        "system_prompt": system_prompt,
        "tasks_path": spec["tasks_path"],
        "core_metrics": list(CORE_METRICS),
        "uc_metrics": uc_metrics,
        # Effektives Set = Kern zuerst, dann UC-spezifisch (Reihenfolge = Report-Spalten)
        "metrics": list(CORE_METRICS) + uc_metrics,
    }
