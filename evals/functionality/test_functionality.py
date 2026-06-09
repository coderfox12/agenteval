"""
Funktionalitäts-Evaluation des Finanzgesellschaft Advisory Agents
Framework: LangGraph (Orchestrierung) + DeepEval 3.9.9 (Bewertung)

DeepEval-Metriken:
  - ToolCorrectnessMetric  → Hat der Agent die richtigen Tools aufgerufen?
  - TaskCompletionMetric   → Wurde die Gesamtaufgabe erfüllt?
  - AnswerRelevancyMetric  → Ist die Antwort relevant zur Anfrage?

Multi-Agent:
  Alle in agents.yaml definierten Agenten werden getestet.
  Pro Agent entsteht eine eigene functionality_costs_{agent_id}.json.

Ausführung:
  cd evals/functionality
  pytest test_functionality.py -v
"""

import os
import sys
from pathlib import Path

import pytest
import yaml
from langchain_community.callbacks import get_openai_callback
from deepeval.metrics import (
    AnswerRelevancyMetric,
    TaskCompletionMetric,
    ToolCorrectnessMetric,
)
from deepeval.test_case import LLMTestCase, ToolCall
from dotenv import load_dotenv
from agenteval_ovb.pricing import calc_cost_usd

sys.path.insert(0, str(Path(__file__).parent))

# .env laden bevor Env-Variablen ausgelesen werden
load_dotenv(Path(__file__).parent.parent.parent / ".env")

from agent.graph import FinanceAdvisoryAgent
from cost_tracker import CostTracker


# ─── Konfiguration laden ──────────────────────────────────────────────────────

def _load_config() -> dict:
    path = Path(__file__).parent.parent.parent / "agents.yaml"
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _load_tasks() -> list[dict]:
    path = Path(__file__).parent / "tasks" / "ovb_tasks.yaml"
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)["tasks"]


_CONFIG     = _load_config()
AGENTS_CONFIG = _CONFIG["agents"]
TASKS         = _load_tasks()

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


# ─── Agent- und Tracker-Instanzen (lazy, gecacht) ────────────────────────────

_agent_instances: dict[str, FinanceAdvisoryAgent] = {}
_trackers: dict[str, CostTracker] = {}


def _get_agent(cfg: dict) -> tuple[FinanceAdvisoryAgent, CostTracker]:
    agent_id = cfg["id"]
    if agent_id not in _agent_instances:
        api_key = os.environ.get(cfg["api_key_env"])
        _agent_instances[agent_id] = FinanceAdvisoryAgent(
            model=cfg["model"],
            api_key=api_key,
            api_base=cfg.get("api_base") or None,
        )
        _trackers[agent_id] = CostTracker(
            output_path=f"functionality_costs_{agent_id}.json"
        )
    return _agent_instances[agent_id], _trackers[agent_id]


# ─── Ergebnis-Cache: (agent_id, task_id) → (output, tool_calls) oder None bei Fehler ─

_cache: dict[tuple[str, str], tuple[str, list[ToolCall]] | None] = {}
# Fehlermeldungen pro (agent_id, task_id) für pytest.skip-Nachrichten
_errors: dict[tuple[str, str], str] = {}


def _run_and_record(
    agent_cfg: dict, task: dict
) -> tuple[str, list[ToolCall]] | None:
    """Führt den Agenten aus und cached das Ergebnis pro (Agent, Task).

    Gibt None zurück wenn der Agent fehlschlägt (Quota, Timeout, Auth-Fehler).
    Der Fehler wird im CostTracker als Fehler-Record festgehalten.
    """
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
    """Wirft pytest.skip wenn der Agent für diesen Task fehlgeschlagen ist."""
    key = (agent_cfg["id"], task["id"])
    if _cache.get(key) is None and key in _errors:
        short = _errors[key][:160].replace("\n", " ")
        pytest.skip(f"Agent '{agent_cfg['id']}' fehlgeschlagen – {short}")


# ─── Parametrisierung: alle (Agent, Task)-Kombinationen ──────────────────────

_PARAMS = [(a, t) for a in AGENTS_CONFIG for t in TASKS]
_IDS    = [f"{a['id']}__{t['id']}" for a, t in _PARAMS]


# ─── Tests ────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("agent_cfg,task", _PARAMS, ids=_IDS)
def test_tool_correctness(agent_cfg, task):
    _run_and_record(agent_cfg, task)          # Fehler im Cache festhalten
    _skip_if_error(agent_cfg, task)           # Skip wenn Agent fehlgeschlagen
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
    _run_and_record(agent_cfg, task)
    _skip_if_error(agent_cfg, task)
    actual_output, _ = _cache[(agent_cfg["id"], task["id"])]

    test_case = LLMTestCase(
        input=task["input"],
        actual_output=actual_output,
    )

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


# ─── pytest-xdist: Tests pro Agent auf denselben Worker gruppieren ───────────

def pytest_collection_modifyitems(items):
    """Gruppiert alle Tests eines Agenten auf denselben xdist-Worker.
    So bleiben Cache und CostTracker innerhalb eines Prozesses konsistent."""
    for item in items:
        if hasattr(item, "callspec") and "agent_cfg" in item.callspec.params:
            agent_id = item.callspec.params["agent_cfg"]["id"]
            item.add_marker(pytest.mark.xdist_group(name=agent_id))


# ─── Abschluss-Report nach allen Tests ───────────────────────────────────────

def pytest_sessionfinish(session, exitstatus):
    for agent_id, tracker in _trackers.items():
        if not tracker.records:
            continue
        for r in tracker.records:
            if r.get("error"):
                r["passed"] = False          # Fehler-Record: immer False, nicht überschreiben
                continue
            scores = [r.get(k) for k in ("tool_correctness", "task_completion", "answer_relevancy")]
            if all(s is not None for s in scores):
                r["passed"] = all(s >= 0.7 for s in scores)
            else:
                r["passed"] = False          # unvollständige Metriken → nicht bestanden
        tracker._save()
        print(f"\n{'='*70}")
        print(f"  Agent: {agent_id}")
        tracker.print_report()
