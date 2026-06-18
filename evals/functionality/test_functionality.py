"""
Funktionalitäts-Evaluation – Agent-Eval@OVB
Framework: LangGraph (Orchestrierung) + DeepEval 3.9.9 (Bewertung)

Zwei orthogonale Dimensionen werden hier zusammengeführt:
  - USE CASE (Umgebungsvariable USE_CASE, Default uc1): WAS getestet wird –
    Tools, Tasks, Metriken und Domäne. Definiert in usecases/registry.py.
  - AGENTEN (agents.yaml): WOMIT getestet wird – jedes Modell/Endpunkt wird
    gegen denselben Use Case geprüft. Erlaubt Modellvergleich (z.B. GPT vs. Llama).

Pro (Agent × Task) entsteht eine eigene functionality_costs_{uc}_{agent_id}.json.

Pro-UC-Metriken:
  UC1/UC2: tool_correctness, task_completion, answer_relevancy
  UC3:     tool_correctness, task_completion, faithfulness (Zitationstreue)
  UC4:     task_completion, hallucination, required_fields (Pflichtfeld-Check)

Ausführung:
  cd evals/functionality
  USE_CASE=uc1 pytest test_functionality.py -v
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

sys.path.insert(0, str(Path(__file__).parent))

# .env laden bevor Env-Variablen ausgelesen werden
load_dotenv(Path(__file__).parent.parent.parent / ".env")

from agent.graph import UseCaseAgent
from usecases.registry import get_use_case
from cost_tracker import CostTracker


# ─── Use Case + Agenten-Konfiguration laden ───────────────────────────────────

_UC = get_use_case()  # liest USE_CASE env, Default uc1


def _load_config() -> dict:
    path = Path(__file__).parent.parent.parent / "agents.yaml"
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_tasks() -> list[dict]:
    with open(_UC["tasks_path"], encoding="utf-8") as f:
        return yaml.safe_load(f)["tasks"]


_CONFIG       = _load_config()
AGENTS_CONFIG = _CONFIG["agents"]
TASKS         = load_tasks()

# Judge-Konfiguration aus agents.yaml
_JUDGE_CFG      = _CONFIG.get("judge", {})
_JUDGE_MODEL    = _JUDGE_CFG.get("model", "gpt-5.4-mini")
_JUDGE_API_KEY  = os.environ.get(_JUDGE_CFG.get("api_key_env", "JUDGE_API_KEY"))
_JUDGE_API_BASE = _JUDGE_CFG.get("api_base") or None

# DeepEval liest OPENAI_API_KEY und OPENAI_BASE_URL aus der Umgebung.
# Wir setzen sie auf die Judge-Credentials aus agents.yaml.
if _JUDGE_API_KEY:
    os.environ["OPENAI_API_KEY"] = _JUDGE_API_KEY
if _JUDGE_API_BASE:
    os.environ["OPENAI_BASE_URL"] = _JUDGE_API_BASE


# ─── Agent- und Tracker-Instanzen (lazy, gecacht) ─────────────────────────────

_agent_instances: dict[str, UseCaseAgent] = {}
_trackers: dict[str, CostTracker] = {}


def _get_agent(cfg: dict) -> tuple[UseCaseAgent, CostTracker]:
    agent_id = cfg["id"]
    if agent_id not in _agent_instances:
        api_key = os.environ.get(cfg["api_key_env"])
        _agent_instances[agent_id] = UseCaseAgent(
            tools=_UC["tools"],
            system_prompt=_UC["system_prompt"],
            model=cfg["model"],
            api_key=api_key,
            api_base=cfg.get("api_base") or None,
        )
        _trackers[agent_id] = CostTracker(
            output_path=f"functionality_costs_{_UC['id']}_{agent_id}.json",
            use_case=_UC["id"],
            metrics=_UC["metrics"],
            core_metrics=_UC.get("core_metrics", []),
        )
    return _agent_instances[agent_id], _trackers[agent_id]


# ─── Ergebnis-Cache: (agent_id, task_id) → (output, tool_calls) oder None bei Fehler ─

_cache: dict[tuple[str, str], tuple[str, list[ToolCall]] | None] = {}
_errors: dict[tuple[str, str], str] = {}


def _run_and_record(agent_cfg: dict, task: dict) -> tuple[str, list[ToolCall]] | None:
    """Führt den Agenten aus und cached das Ergebnis pro (Agent, Task).
    Gibt None zurück wenn der Agent fehlschlägt (Quota, Timeout, Auth-Fehler)."""
    key = (agent_cfg["id"], task["id"])
    if key not in _cache:
        agent, tracker = _get_agent(agent_cfg)
        try:
            result = agent.run(task["input"])
            tracker.record(task["id"], result["cost"])
            _cache[key] = (result["output"], [ToolCall(name=n) for n in result["tools_called"]])
        except Exception as exc:
            err_str = str(exc)
            tracker.record_error(task["id"], err_str)
            _cache[key] = None
            _errors[key] = err_str
    return _cache[key]


def _skip_if_error(agent_cfg: dict, task: dict) -> None:
    key = (agent_cfg["id"], task["id"])
    if _cache.get(key) is None and key in _errors:
        short = _errors[key][:160].replace("\n", " ")
        pytest.skip(f"Agent '{agent_cfg['id']}' fehlgeschlagen – {short}")


# ─── Parametrisierung: alle (Agent, Task)-Kombinationen für den gewählten UC ──

_PARAMS = [(a, t) for a in AGENTS_CONFIG for t in TASKS]
_IDS    = [f"{a['id']}__{t['id']}" for a, t in _PARAMS]


# ─── Tests ────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("agent_cfg,task", _PARAMS, ids=_IDS)
def test_tool_correctness(agent_cfg, task):
    """Prüft ob der Agent die richtigen Tools aufgerufen hat."""
    if "tool_correctness" not in _UC["metrics"]:
        pytest.skip(f"tool_correctness nicht in Metrik-Set von {_UC['id']}")

    _run_and_record(agent_cfg, task)
    _skip_if_error(agent_cfg, task)
    actual_output, tools_called = _cache[(agent_cfg["id"], task["id"])]
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
    _, tracker = _get_agent(agent_cfg)
    tracker.update_metrics(task["id"], {"tool_correctness": round(metric.score, 3)})
    assert metric.is_successful(), f"ToolCorrectness: {metric.score:.2f} < 0.7"


@pytest.mark.parametrize("agent_cfg,task", _PARAMS, ids=_IDS)
def test_task_completion(agent_cfg, task):
    """Prüft ob der Agent die Gesamtaufgabe vollständig erfüllt hat."""
    if "task_completion" not in _UC["metrics"]:
        pytest.skip(f"task_completion nicht in Metrik-Set von {_UC['id']}")

    _run_and_record(agent_cfg, task)
    _skip_if_error(agent_cfg, task)
    actual_output, _ = _cache[(agent_cfg["id"], task["id"])]

    test_case = LLMTestCase(
        input=task["input"],
        actual_output=actual_output,
        expected_output=task["deepeval_task"],
    )

    metric = TaskCompletionMetric(threshold=0.7, task=task["deepeval_task"], model=_JUDGE_MODEL)
    with get_openai_callback() as cb:
        metric.measure(test_case)
    judge_cost = calc_cost_usd(_JUDGE_MODEL, cb.prompt_tokens, cb.completion_tokens)
    _, tracker = _get_agent(agent_cfg)
    tracker.update_metrics(task["id"], {
        "task_completion": round(metric.score, 3),
        "eval_cost_usd": round(tracker.get_eval_cost(task["id"]) + judge_cost, 6),
    })
    assert metric.is_successful(), f"TaskCompletion: {metric.score:.2f} < 0.7"


@pytest.mark.parametrize("agent_cfg,task", _PARAMS, ids=_IDS)
def test_answer_relevancy(agent_cfg, task):
    """Prüft ob die Antwort des Agenten relevant zur gestellten Aufgabe ist (UC1/UC2)."""
    if "answer_relevancy" not in _UC["metrics"]:
        pytest.skip(f"answer_relevancy nicht in Metrik-Set von {_UC['id']}")

    _run_and_record(agent_cfg, task)
    _skip_if_error(agent_cfg, task)
    actual_output, _ = _cache[(agent_cfg["id"], task["id"])]

    test_case = LLMTestCase(input=task["input"], actual_output=actual_output)

    metric = AnswerRelevancyMetric(threshold=0.7, model=_JUDGE_MODEL)
    with get_openai_callback() as cb:
        metric.measure(test_case)
    judge_cost = calc_cost_usd(_JUDGE_MODEL, cb.prompt_tokens, cb.completion_tokens)
    _, tracker = _get_agent(agent_cfg)
    tracker.update_metrics(task["id"], {
        "answer_relevancy": round(metric.score, 3),
        "eval_cost_usd": round(tracker.get_eval_cost(task["id"]) + judge_cost, 6),
    })
    assert metric.is_successful(), f"AnswerRelevancy: {metric.score:.2f} < 0.7"


@pytest.mark.parametrize("agent_cfg,task", _PARAMS, ids=_IDS)
def test_faithfulness(agent_cfg, task):
    """Prüft Zitationstreue – Antwort darf nur Fakten aus dem Retrieval-Kontext enthalten (UC3)."""
    if "faithfulness" not in _UC["metrics"]:
        pytest.skip(f"faithfulness nicht in Metrik-Set von {_UC['id']}")

    _run_and_record(agent_cfg, task)
    _skip_if_error(agent_cfg, task)
    actual_output, _ = _cache[(agent_cfg["id"], task["id"])]

    retrieval_context = [task.get("expected_output", "")]
    test_case = LLMTestCase(
        input=task["input"],
        actual_output=actual_output,
        retrieval_context=retrieval_context,
    )

    metric = FaithfulnessMetric(threshold=0.7, model=_JUDGE_MODEL)
    with get_openai_callback() as cb:
        metric.measure(test_case)
    judge_cost = calc_cost_usd(_JUDGE_MODEL, cb.prompt_tokens, cb.completion_tokens)
    _, tracker = _get_agent(agent_cfg)
    tracker.update_metrics(task["id"], {
        "faithfulness": round(metric.score, 3),
        "eval_cost_usd": round(tracker.get_eval_cost(task["id"]) + judge_cost, 6),
    })
    assert metric.is_successful(), f"Faithfulness: {metric.score:.2f} < 0.7"


@pytest.mark.parametrize("agent_cfg,task", _PARAMS, ids=_IDS)
def test_hallucination(agent_cfg, task):
    """Prüft Halluzinationen – Agent darf keine Fakten erfinden (UC4)."""
    if "hallucination" not in _UC["metrics"]:
        pytest.skip(f"hallucination nicht in Metrik-Set von {_UC['id']}")

    _run_and_record(agent_cfg, task)
    _skip_if_error(agent_cfg, task)
    actual_output, _ = _cache[(agent_cfg["id"], task["id"])]

    context = [task.get("input", ""), task.get("expected_output", "")]
    test_case = LLMTestCase(
        input=task["input"],
        actual_output=actual_output,
        context=context,
    )

    metric = HallucinationMetric(threshold=0.5, model=_JUDGE_MODEL)
    with get_openai_callback() as cb:
        metric.measure(test_case)
    judge_cost = calc_cost_usd(_JUDGE_MODEL, cb.prompt_tokens, cb.completion_tokens)
    passed = metric.score <= 0.5
    _, tracker = _get_agent(agent_cfg)
    tracker.update_metrics(task["id"], {
        "hallucination": round(metric.score, 3),
        "eval_cost_usd": round(tracker.get_eval_cost(task["id"]) + judge_cost, 6),
    })
    assert passed, f"Hallucination zu hoch: {metric.score:.2f} > 0.5"


@pytest.mark.parametrize("agent_cfg,task", _PARAMS, ids=_IDS)
def test_required_fields(agent_cfg, task):
    """Prüft ob alle §61-VVG-Pflichtfelder im generierten Protokoll vorhanden sind (UC4)."""
    if "required_fields" not in _UC["metrics"]:
        pytest.skip(f"required_fields nicht in Metrik-Set von {_UC['id']}")

    _run_and_record(agent_cfg, task)
    _skip_if_error(agent_cfg, task)
    actual_output, tools_called = _cache[(agent_cfg["id"], task["id"])]

    from usecases.uc4_beratungsdoku.tools import VVG_REQUIRED_FIELDS

    tool_names = [tc.name for tc in tools_called]

    if task.get("should_escalate"):
        passed = "flag_missing_information" in tool_names
        score = 1.0 if passed else 0.0
    else:
        found = sum(1 for f in VVG_REQUIRED_FIELDS if f.lower() in actual_output.lower())
        score = round(found / len(VVG_REQUIRED_FIELDS), 3)
        passed = score >= 0.7

    _, tracker = _get_agent(agent_cfg)
    tracker.update_metrics(task["id"], {"required_fields": score})
    assert passed, f"RequiredFields: {score:.2f} < 0.7 oder flag_missing_information nicht aufgerufen"


# ─── pytest-xdist: Tests pro Agent auf denselben Worker gruppieren ────────────

def pytest_collection_modifyitems(items):
    """Gruppiert alle Tests eines Agenten auf denselben xdist-Worker.
    So bleiben Cache und CostTracker innerhalb eines Prozesses konsistent."""
    for item in items:
        if hasattr(item, "callspec") and "agent_cfg" in item.callspec.params:
            agent_id = item.callspec.params["agent_cfg"]["id"]
            item.add_marker(pytest.mark.xdist_group(name=agent_id))


# ─── Abschluss-Report nach allen Tests ────────────────────────────────────────

def pytest_sessionfinish(session, exitstatus):
    """Berechnet passed-Flag aus gespeicherten Scores und gibt Report pro Agent aus."""
    for agent_id, tracker in _trackers.items():
        if not tracker.records:
            continue
        for r in tracker.records:
            if r.get("error"):
                r["passed"] = False
        tracker.finalize_passed()
        tracker._save()
        print(f"\n{'='*70}")
        print(f"  Use Case: {_UC['id']}  |  Agent: {agent_id}")
        tracker.print_report()
