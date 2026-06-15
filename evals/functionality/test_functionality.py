"""
Funktionalitäts-Evaluation – Agent-Eval@OVB
Framework: LangGraph (Orchestrierung) + DeepEval 3.9.9 (Bewertung)

Use Case wird über die Umgebungsvariable USE_CASE gewählt (Default: uc1).
Beispiel: USE_CASE=uc2 deepeval test run test_functionality.py -v

Pro-UC-Metriken (in usecases/registry.py konfiguriert):
  UC1/UC2: tool_correctness, task_completion, answer_relevancy
  UC3:     tool_correctness, task_completion, faithfulness (Zitationstreue)
  UC4:     task_completion, hallucination, required_fields (Pflichtfeld-Check)

Wirtschaftlichkeit:
  - Agent-Kosten werden via get_openai_callback pro Task erfasst.
  - Judge-Kosten (LLM-basierte Metriken) werden separat erfasst.

Ausführung:
  cd evals/functionality
  USE_CASE=uc1 deepeval test run test_functionality.py -v
"""

import os
import sys
from pathlib import Path

import pytest
import yaml
from langchain_community.callbacks import get_openai_callback
from deepeval.metrics import (
    AnswerRelevancyMetric,
    FaithfulnessMetric,
    HallucinationMetric,
    TaskCompletionMetric,
    ToolCorrectnessMetric,
)
from deepeval.test_case import LLMTestCase, ToolCall
from dotenv import load_dotenv
from agenteval_ovb.pricing import calc_cost_usd

_EVAL_MODEL = os.environ.get("MODEL_NAME", "gpt-5.4-mini")

sys.path.insert(0, str(Path(__file__).parent))

# .env laden bevor Env-Variablen ausgelesen werden
load_dotenv(Path(__file__).parent.parent.parent / ".env")

from agent.graph import UseCaseAgent
from usecases.registry import get_use_case
from cost_tracker import CostTracker

# ─── UC-Initialisierung ───────────────────────────────────────────────────────

_UC = get_use_case()
_COST_FILE = os.environ.get("COST_FILE", f"functionality_costs_{_UC['id']}.json")

agent = UseCaseAgent(tools=_UC["tools"], system_prompt=_UC["system_prompt"])
tracker = CostTracker(output_path=_COST_FILE, use_case=_UC["id"], metrics=_UC["metrics"])


def load_tasks() -> list[dict]:
    with open(_UC["tasks_path"], encoding="utf-8") as f:
        return yaml.safe_load(f)["tasks"]


TASKS = load_tasks()


# ─── Metrik-Builder-Mapping ───────────────────────────────────────────────────

def _build_metric(key: str, task: dict):
    if key == "tool_correctness":
        return ToolCorrectnessMetric(threshold=0.7)
    if key == "task_completion":
        return TaskCompletionMetric(threshold=0.7, task=task["deepeval_task"], model=_EVAL_MODEL)
    if key == "answer_relevancy":
        return AnswerRelevancyMetric(threshold=0.7, model=_EVAL_MODEL)
    if key == "faithfulness":
        return FaithfulnessMetric(threshold=0.7, model=_EVAL_MODEL)
    if key == "hallucination":
        return HallucinationMetric(threshold=0.5, model=_EVAL_MODEL)
    raise ValueError(f"Unbekannter Metrik-Schlüssel: '{key}'")


# ─── Ergebnis-Cache ───────────────────────────────────────────────────────────

_cache: dict[str, tuple[str, list[ToolCall]] | None] = {}
_errors: dict[str, str] = {}


def run_and_record(task: dict) -> tuple[str, list[ToolCall]] | None:
    """Führt den Agenten aus, erfasst Kosten und cached das Ergebnis.
    Gibt None zurück wenn der Agent fehlschlägt (Quota, Timeout, Auth-Fehler)."""
    task_id = task["id"]
    if task_id not in _cache:
        try:
            result = agent.run(task["input"])
            tracker.record(task_id, result["cost"])
            _cache[task_id] = (result["output"], [ToolCall(name=name) for name in result["tools_called"]])
        except Exception as exc:
            err_str = str(exc)
            tracker.record_error(task_id, err_str)
            _cache[task_id] = None
            _errors[task_id] = err_str
    return _cache[task_id]


def _skip_if_error(task: dict) -> None:
    task_id = task["id"]
    if _cache.get(task_id) is None and task_id in _errors:
        short = _errors[task_id][:160].replace("\n", " ")
        pytest.skip(f"Agent fehlgeschlagen – {short}")


# ─── Tests ────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("task", TASKS, ids=[t["id"] for t in TASKS])
def test_tool_correctness(task: dict):
    """Prüft ob der Agent die richtigen Tools aufgerufen hat."""
    if "tool_correctness" not in _UC["metrics"]:
        pytest.skip(f"tool_correctness nicht in Metrik-Set von {_UC['id']}")

    run_and_record(task)
    _skip_if_error(task)
    actual_output, tools_called = _cache[task["id"]]
    expected_tools = [ToolCall(name=name) for name in task["expected_tools"]]

    test_case = LLMTestCase(
        input=task["input"],
        actual_output=actual_output,
        expected_output=task["expected_output"],
        tools_called=tools_called,
        expected_tools=expected_tools,
    )

    metric = ToolCorrectnessMetric(threshold=0.7)
    metric.measure(test_case)
    tracker.update_metrics(task["id"], {"tool_correctness": round(metric.score, 3)})
    assert metric.is_successful(), f"ToolCorrectness: {metric.score:.2f} < 0.7"


@pytest.mark.parametrize("task", TASKS, ids=[t["id"] for t in TASKS])
def test_task_completion(task: dict):
    """Prüft ob der Agent die Gesamtaufgabe vollständig erfüllt hat."""
    if "task_completion" not in _UC["metrics"]:
        pytest.skip(f"task_completion nicht in Metrik-Set von {_UC['id']}")

    run_and_record(task)
    _skip_if_error(task)
    actual_output, _ = _cache[task["id"]]

    test_case = LLMTestCase(
        input=task["input"],
        actual_output=actual_output,
        expected_output=task["deepeval_task"],
    )

    metric = TaskCompletionMetric(threshold=0.7, task=task["deepeval_task"], model=_EVAL_MODEL)
    with get_openai_callback() as cb:
        metric.measure(test_case)
    judge_cost = calc_cost_usd(_EVAL_MODEL, cb.prompt_tokens, cb.completion_tokens)
    tracker.update_metrics(task["id"], {
        "task_completion": round(metric.score, 3),
        "eval_cost_usd": round(tracker.get_eval_cost(task["id"]) + judge_cost, 6),
    })
    assert metric.is_successful(), f"TaskCompletion: {metric.score:.2f} < 0.7"


@pytest.mark.parametrize("task", TASKS, ids=[t["id"] for t in TASKS])
def test_answer_relevancy(task: dict):
    """Prüft ob die Antwort des Agenten relevant zur gestellten Aufgabe ist (UC1/UC2)."""
    if "answer_relevancy" not in _UC["metrics"]:
        pytest.skip(f"answer_relevancy nicht in Metrik-Set von {_UC['id']}")

    run_and_record(task)
    _skip_if_error(task)
    actual_output, _ = _cache[task["id"]]

    test_case = LLMTestCase(input=task["input"], actual_output=actual_output)

    metric = AnswerRelevancyMetric(threshold=0.7, model=_EVAL_MODEL)
    with get_openai_callback() as cb:
        metric.measure(test_case)
    judge_cost = calc_cost_usd(_EVAL_MODEL, cb.prompt_tokens, cb.completion_tokens)
    tracker.update_metrics(task["id"], {
        "answer_relevancy": round(metric.score, 3),
        "eval_cost_usd": round(tracker.get_eval_cost(task["id"]) + judge_cost, 6),
    })
    assert metric.is_successful(), f"AnswerRelevancy: {metric.score:.2f} < 0.7"


@pytest.mark.parametrize("task", TASKS, ids=[t["id"] for t in TASKS])
def test_faithfulness(task: dict):
    """Prüft Zitationstreue – Antwort darf nur Fakten aus dem Retrieval-Kontext enthalten (UC3)."""
    if "faithfulness" not in _UC["metrics"]:
        pytest.skip(f"faithfulness nicht in Metrik-Set von {_UC['id']}")

    run_and_record(task)
    _skip_if_error(task)
    actual_output, _ = _cache[task["id"]]

    retrieval_context = [task.get("expected_output", "")]
    test_case = LLMTestCase(
        input=task["input"],
        actual_output=actual_output,
        retrieval_context=retrieval_context,
    )

    metric = FaithfulnessMetric(threshold=0.7, model=_EVAL_MODEL)
    with get_openai_callback() as cb:
        metric.measure(test_case)
    judge_cost = calc_cost_usd(_EVAL_MODEL, cb.prompt_tokens, cb.completion_tokens)
    tracker.update_metrics(task["id"], {
        "faithfulness": round(metric.score, 3),
        "eval_cost_usd": round(tracker.get_eval_cost(task["id"]) + judge_cost, 6),
    })
    assert metric.is_successful(), f"Faithfulness: {metric.score:.2f} < 0.7"


@pytest.mark.parametrize("task", TASKS, ids=[t["id"] for t in TASKS])
def test_hallucination(task: dict):
    """Prüft Halluzinationen – Agent darf keine Fakten erfinden (UC4)."""
    if "hallucination" not in _UC["metrics"]:
        pytest.skip(f"hallucination nicht in Metrik-Set von {_UC['id']}")

    run_and_record(task)
    _skip_if_error(task)
    actual_output, _ = _cache[task["id"]]

    context = [task.get("input", ""), task.get("expected_output", "")]
    test_case = LLMTestCase(
        input=task["input"],
        actual_output=actual_output,
        context=context,
    )

    metric = HallucinationMetric(threshold=0.5, model=_EVAL_MODEL)
    with get_openai_callback() as cb:
        metric.measure(test_case)
    judge_cost = calc_cost_usd(_EVAL_MODEL, cb.prompt_tokens, cb.completion_tokens)
    passed = metric.score <= 0.5
    tracker.update_metrics(task["id"], {
        "hallucination": round(metric.score, 3),
        "eval_cost_usd": round(tracker.get_eval_cost(task["id"]) + judge_cost, 6),
    })
    assert passed, f"Hallucination zu hoch: {metric.score:.2f} > 0.5"


@pytest.mark.parametrize("task", TASKS, ids=[t["id"] for t in TASKS])
def test_required_fields(task: dict):
    """Prüft ob alle §61-VVG-Pflichtfelder im generierten Protokoll vorhanden sind (UC4)."""
    if "required_fields" not in _UC["metrics"]:
        pytest.skip(f"required_fields nicht in Metrik-Set von {_UC['id']}")

    run_and_record(task)
    _skip_if_error(task)
    actual_output, tools_called = _cache[task["id"]]

    from usecases.uc4_beratungsdoku.tools import VVG_REQUIRED_FIELDS

    tool_names = [tc.name for tc in tools_called]

    if task.get("should_escalate"):
        passed = "flag_missing_information" in tool_names
        score = 1.0 if passed else 0.0
    else:
        found = sum(1 for f in VVG_REQUIRED_FIELDS if f.lower() in actual_output.lower())
        score = round(found / len(VVG_REQUIRED_FIELDS), 3)
        passed = score >= 0.7

    tracker.update_metrics(task["id"], {"required_fields": score})
    assert passed, f"RequiredFields: {score:.2f} < 0.7 oder flag_missing_information nicht aufgerufen"


# ─── Wirtschaftlichkeits-Report nach allen Tests ──────────────────────────────

def pytest_sessionfinish(session, exitstatus):
    """Berechnet passed-Flag aus gespeicherten Scores und gibt Report aus."""
    if not tracker.records:
        return
    for r in tracker.records:
        if r.get("error"):
            r["passed"] = False
            continue
    tracker.finalize_passed()
    tracker._save()
    tracker.print_report()
