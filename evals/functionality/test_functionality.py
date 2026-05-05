"""
Funktionalitäts-Evaluation des Finanzgesellschaft Advisory Agents
Framework: LangGraph (Orchestrierung) + DeepEval 3.9.9 (Bewertung)

DeepEval-Metriken:
  - ToolCorrectnessMetric  → Hat der Agent die richtigen Tools aufgerufen?
  - TaskCompletionMetric   → Wurde die Gesamtaufgabe erfüllt?
  - AnswerRelevancyMetric  → Ist die Antwort relevant zur Anfrage?

Wirtschaftlichkeit:
  - Token-Verbrauch und Latenz werden via LangGraph-Callbacks (get_openai_callback)
    pro Task erfasst und am Ende als Report ausgegeben.

Ausführung:
  cd evals/functionality
  pytest test_functionality.py -v
"""

import os
import sys
from pathlib import Path

import pytest
import yaml
from deepeval import assert_test
from deepeval.metrics import (
    AnswerRelevancyMetric,
    TaskCompletionMetric,
    ToolCorrectnessMetric,
)
from deepeval.test_case import LLMTestCase, ToolCall
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parent))

load_dotenv(Path(__file__).parent.parent.parent / ".env")

from agent.graph import FinanceAdvisoryAgent
from cost_tracker import CostTracker

# ─── Initialisierung ──────────────────────────────────────────────────────────

agent = FinanceAdvisoryAgent(model="gpt-4o-mini")
tracker = CostTracker(output_path="functionality_costs.json")


def load_tasks() -> list[dict]:
    tasks_path = Path(__file__).parent / "tasks" / "ovb_tasks.yaml"
    with open(tasks_path, encoding="utf-8") as f:
        return yaml.safe_load(f)["tasks"]


TASKS = load_tasks()


# ─── Hilfsfunktion ────────────────────────────────────────────────────────────

_cache: dict[str, tuple[str, list[ToolCall]]] = {}


def run_and_record(task: dict) -> tuple[str, list[ToolCall]]:
    """Führt den Agenten aus, erfasst Kosten und gibt Output + ToolCall-Objekte zurück.
    Ergebnis wird pro Task-ID gecacht, damit der Agent nur einmal pro Task läuft."""
    task_id = task["id"]
    if task_id not in _cache:
        result = agent.run(task["input"])
        tracker.record(task_id, result["cost"])
        _cache[task_id] = (result["output"], [ToolCall(name=name) for name in result["tools_called"]])
    return _cache[task_id]


# ─── Tests ────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("task", TASKS, ids=[t["id"] for t in TASKS])
def test_tool_correctness(task: dict):
    """Prüft ob der Agent die richtigen Tools aufgerufen hat."""
    actual_output, tools_called = run_and_record(task)
    expected_tools = [ToolCall(name=name) for name in task["expected_tools"]]

    test_case = LLMTestCase(
        input=task["input"],
        actual_output=actual_output,
        expected_output=task["expected_output"],
        tools_called=tools_called,
        expected_tools=expected_tools,
    )

    assert_test(test_case, [ToolCorrectnessMetric(threshold=0.7)])


@pytest.mark.parametrize("task", TASKS, ids=[t["id"] for t in TASKS])
def test_task_completion(task: dict):
    """Prüft ob der Agent die Gesamtaufgabe vollständig erfüllt hat."""
    actual_output, _ = run_and_record(task)

    test_case = LLMTestCase(
        input=task["input"],
        actual_output=actual_output,
        expected_output=task["deepeval_task"],
    )

    assert_test(test_case, [TaskCompletionMetric(threshold=0.7, task=task["deepeval_task"])])


@pytest.mark.parametrize("task", TASKS, ids=[t["id"] for t in TASKS])
def test_answer_relevancy(task: dict):
    """Prüft ob die Antwort des Agenten relevant zur gestellten Aufgabe ist."""
    actual_output, _ = run_and_record(task)

    test_case = LLMTestCase(
        input=task["input"],
        actual_output=actual_output,
    )

    assert_test(test_case, [AnswerRelevancyMetric(threshold=0.7)])


# ─── Wirtschaftlichkeits-Report nach allen Tests ──────────────────────────────

def pytest_sessionfinish(session, exitstatus):
    """Gibt den Wirtschaftlichkeits-Report am Ende der Test-Session aus."""
    if tracker.records:
        tracker.print_report()
