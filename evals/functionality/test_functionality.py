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

import concurrent.futures
import os
import sys
import threading
import time
from pathlib import Path

import pytest
import yaml
from deepeval.metrics import (
    AnswerRelevancyMetric,
    FaithfulnessMetric,
    HallucinationMetric,
    TaskCompletionMetric,
    ToolCorrectnessMetric,
)
from deepeval.test_case import LLMTestCase, ToolCall
from dotenv import load_dotenv
from agenteval_ovb.agents_config import load_agents_config, require_api_base
from agenteval_ovb.pricing import price_per_token, validate_agents_config

sys.path.insert(0, str(Path(__file__).parent))

# .env laden bevor Env-Variablen ausgelesen werden
load_dotenv(Path(__file__).parent.parent.parent / ".env")

from agent.graph import UseCaseAgent
from usecases.registry import get_use_case
from cost_tracker import CostTracker


# ─── Use Case + Agenten-Konfiguration laden ───────────────────────────────────

_UC = get_use_case()  # liest USE_CASE env, Default uc1


def load_tasks() -> list[dict]:
    with open(_UC["tasks_path"], encoding="utf-8") as f:
        return yaml.safe_load(f)["tasks"]


_CONFIG       = load_agents_config()
AGENTS_CONFIG = _CONFIG["agents"]
TASKS         = load_tasks()

# Judge-Konfiguration aus agents.yaml
_JUDGE_CFG      = _CONFIG.get("judge", {})
_JUDGE_API_BASE = require_api_base(_JUDGE_CFG, "judge")
_JUDGE_MODEL    = _JUDGE_CFG.get("model", "gpt-5.4-mini")
_JUDGE_API_KEY  = os.environ.get(_JUDGE_CFG.get("api_key_env", "JUDGE_API_KEY"))

# Preis-Validierung: lieber jetzt abbrechen als falsche Wirtschaftlichkeits-
# Zahlen im Report erzeugen, weil ein Modell in pricing.py fehlt.
validate_agents_config(_CONFIG)

# DeepEval liest OPENAI_API_KEY und OPENAI_BASE_URL aus der Umgebung.
# Wir setzen sie auf die Judge-Credentials aus agents.yaml.
if _JUDGE_API_KEY:
    os.environ["OPENAI_API_KEY"] = _JUDGE_API_KEY
os.environ["OPENAI_BASE_URL"] = _JUDGE_API_BASE

# DeepEval berechnet Kosten selbst aus den echten Tokens der API-Antwort
# (completion.usage), aber mit einem eigenen, oft falschen Preis für
# unbekannte Modellnamen wie OpenRouter-Slugs. Mit OPENAI_COST_PER_*_TOKEN
# erzwingen wir unseren eigenen, korrekten Preis aus pricing.py – das Ergebnis
# in metric.evaluation_cost ist dann exakt (echte Tokens × unser Preis).
_judge_in_price, _judge_out_price = price_per_token(_JUDGE_MODEL)
os.environ["OPENAI_COST_PER_INPUT_TOKEN"]  = str(_judge_in_price)
os.environ["OPENAI_COST_PER_OUTPUT_TOKEN"] = str(_judge_out_price)


# ─── Agent- und Tracker-Instanzen (lazy, gecacht) ─────────────────────────────

_agent_instances: dict[str, UseCaseAgent] = {}
_trackers: dict[str, CostTracker] = {}
_agent_init_lock = threading.Lock()


def _get_agent(cfg: dict) -> tuple[UseCaseAgent, CostTracker]:
    agent_id = cfg["id"]
    if agent_id not in _agent_instances:
        # Lock nötig: beim parallelen Vorwärmen (ThreadPoolExecutor unten)
        # greifen mehrere Threads gleichzeitig auf denselben Agenten zu –
        # ohne Lock könnte ein zweiter Thread Instanz/Tracker überschreiben,
        # bevor der erste fertig ist (verlorene Records, kein Crash).
        with _agent_init_lock:
            if agent_id not in _agent_instances:
                api_base = require_api_base(cfg, f"Agent '{agent_id}'")
                api_key = os.environ.get(cfg["api_key_env"])
                _agent_instances[agent_id] = UseCaseAgent(
                    tools=_UC["tools"],
                    system_prompt=_UC["system_prompt"],
                    model=cfg["model"],
                    api_key=api_key,
                    api_base=api_base,
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
_AGENT_MAX_RETRIES = 3


def _run_and_record(agent_cfg: dict, task: dict) -> tuple[str, list[ToolCall]] | None:
    """Führt den Agenten aus und cached das Ergebnis pro (Agent, Task).
    Gibt None zurück wenn der Agent nach allen Versuchen fehlschlägt (Quota,
    Timeout, Auth-Fehler, leere Antwort durch Content-Filter).

    Mit Retry: reale Läufe zeigten intermittierende Fehler bei beiden Agenten
    (nicht nur beim Judge) – wahrscheinlich transiente OpenRouter-Probleme,
    kein deterministischer Bug. Ein zweiter/dritter Versuch ist oft erfolgreich."""
    key = (agent_cfg["id"], task["id"])
    if key not in _cache:
        agent, tracker = _get_agent(agent_cfg)
        last_exc: Exception | None = None
        # Kosten leerer/gefilterter Antworten aus vorherigen Versuchen dieser
        # Schleife – echte, bei OpenRouter abgerechnete Tokens, die sonst
        # spurlos verschwinden würden, nur weil der Task am Ende scheitert
        # oder erst im nächsten Versuch erfolgreich ist.
        wasted_cost_usd = 0.0
        for attempt in range(_AGENT_MAX_RETRIES):
            try:
                result = agent.run(task["input"])
                cost_data = result["cost"]
                if wasted_cost_usd:
                    cost_data = {**cost_data, "cost_usd": round(cost_data["cost_usd"] + wasted_cost_usd, 6)}
                if not result["output"]:
                    # Leere Antwort (kein Text, keine Tool-Calls) – z.B. durch
                    # einen Content-Filter ausgelöst (bei Gemini via OpenRouter
                    # beobachtet). Kosten dieses Versuchs nicht verwerfen,
                    # sondern bei einem späteren Erfolg/endgültigen Fehler
                    # draufrechnen, dann erneut versuchen.
                    wasted_cost_usd = cost_data["cost_usd"]
                    raise RuntimeError(
                        "Agent lieferte leere Antwort (kein Text, keine Tool-Calls) – "
                        "möglicherweise durch einen Content-Filter des Modells ausgelöst."
                    )
                tracker.record(task["id"], cost_data)
                _cache[key] = (result["output"], [ToolCall(name=n) for n in result["tools_called"]])
                break
            except Exception as exc:
                last_exc = exc
                if attempt < _AGENT_MAX_RETRIES - 1:
                    time.sleep(2 ** attempt)  # 1s, 2s
        else:
            err_str = str(last_exc)
            tracker.record_error(task["id"], err_str, cost_usd=wasted_cost_usd or None)
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


# ─── Metrik-Cache: (agent_id, task_id, metric_name) → (score, judge_cost) ──────
# Separat vom Ergebnis-Cache (_cache), weil eine LLM-Judge-Bewertung erst
# nach dem Agent-Lauf möglich ist (braucht actual_output) – siehe Phase 2
# in pytest_sessionstart.

_metric_cache: dict[tuple[str, str, str], tuple[float | None, float]] = {}
_metric_errors: dict[tuple[str, str, str], str] = {}
_metric_cache_lock = threading.Lock()
_LLM_JUDGE_METRICS = ("task_completion", "answer_relevancy", "faithfulness", "hallucination")
_METRIC_MAX_RETRIES = 3


def _build_test_case_and_metric(task: dict, metric_name: str, actual_output: str):
    """Baut LLMTestCase + frisches Metric-Objekt für eine LLM-Judge-Metrik.
    Jeder Aufruf erzeugt ein eigenes Metric-Objekt – kein gemeinsamer
    mutable State zwischen parallel laufenden Threads."""
    if metric_name == "task_completion":
        test_case = LLMTestCase(
            input=task["input"], actual_output=actual_output, expected_output=task["deepeval_task"],
        )
        metric = TaskCompletionMetric(threshold=0.7, task=task["deepeval_task"], model=_JUDGE_MODEL)
    elif metric_name == "answer_relevancy":
        test_case = LLMTestCase(input=task["input"], actual_output=actual_output)
        metric = AnswerRelevancyMetric(threshold=0.7, model=_JUDGE_MODEL)
    elif metric_name == "faithfulness":
        retrieval_context = [task.get("expected_output", "")]
        test_case = LLMTestCase(
            input=task["input"], actual_output=actual_output, retrieval_context=retrieval_context,
        )
        metric = FaithfulnessMetric(threshold=0.7, model=_JUDGE_MODEL)
    elif metric_name == "hallucination":
        context = [task.get("input", ""), task.get("expected_output", "")]
        test_case = LLMTestCase(input=task["input"], actual_output=actual_output, context=context)
        metric = HallucinationMetric(threshold=0.5, model=_JUDGE_MODEL)
    else:
        raise ValueError(f"Unbekannte LLM-Judge-Metrik: {metric_name}")
    return test_case, metric


def _prewarm_metric(agent_cfg: dict, task: dict, metric_name: str) -> None:
    """Berechnet eine LLM-Judge-Metrik für (agent, task) und cached (score, cost).

    Mit Retry: unter Last (security_compliance läuft als paralleler CI-Job
    gleichzeitig gegen denselben Judge-API-Key) wurden vereinzelt transiente
    Fehler (z.B. Rate-Limits) beobachtet, die ohne Retry sofort als endgültig
    fehlgeschlagen gewertet wurden – obwohl ein zweiter Versuch oft erfolgreich
    ist. Der Fehlergrund wird in _metric_errors hinterlegt, damit ein
    endgültiger Fehlschlag im Test nicht nur als "–" verschwindet, sondern mit
    Ursache sichtbar wird.
    """
    key = (agent_cfg["id"], task["id"], metric_name)
    cached = _cache.get((agent_cfg["id"], task["id"]))
    if cached is None:
        return  # Agent-Lauf fehlgeschlagen – Tests behandeln das via _skip_if_error
    actual_output, _ = cached
    last_exc: Exception | None = None
    for attempt in range(_METRIC_MAX_RETRIES):
        try:
            test_case, metric = _build_test_case_and_metric(task, metric_name, actual_output)
            metric.measure(test_case)
            with _metric_cache_lock:
                _metric_cache[key] = (metric.score, metric.evaluation_cost or 0.0)
            return
        except Exception as exc:
            last_exc = exc
            if attempt < _METRIC_MAX_RETRIES - 1:
                time.sleep(2 ** attempt)  # 1s, 2s

    print(f"⚠  Judge-Metrik '{metric_name}' für {key} nach {_METRIC_MAX_RETRIES} Versuchen fehlgeschlagen: {last_exc}")
    with _metric_cache_lock:
        _metric_cache[key] = (None, 0.0)
        _metric_errors[key] = str(last_exc)


def warm_caches() -> None:
    """Wärmt Agent-Läufe und Judge-Bewertungen parallel vor (Threads, ein Prozess).

    WICHTIG: wird über conftest.py:pytest_sessionstart aufgerufen, NICHT als
    pytest_sessionstart hier in der Testdatei selbst definiert – pytest
    erkennt Session-Hooks (pytest_sessionstart/pytest_sessionfinish) NUR in
    conftest.py, nicht in regulären test_*.py-Dateien. Ein gleichnamiger Hook
    direkt hier wird von pytest nie aufgerufen (verifiziert mit einem
    minimalen Wegwerf-Testfall) – dieser Bug hat dafür gesorgt, dass die
    gesamte Parallelisierung + Judge-Bewertung in der Praxis nie liefen,
    obwohl die Funktion selbst korrekt war.

    Phase 1: alle agent.run()-Aufrufe parallel (_cache befüllen).
    Phase 2: alle LLM-Judge-Metriken parallel (_metric_cache befüllen) – erst
    nachdem Phase 1 abgeschlossen ist, da jede Metrik actual_output braucht.
    Die Testfunktionen unten lesen danach nur noch aus den Caches und machen
    selbst keine API-Calls mehr – der gesamte Lauf wird dadurch durch die
    LANGSAMSTE Einzelanfrage begrenzt, nicht durch die Summe aller Anfragen.

    Threads statt pytest-xdist-Prozessen: Python gibt die GIL während des
    Wartens auf die HTTP-Antwort frei (echte Nebenläufigkeit fürs I/O), aber
    _cache/_trackers/_metric_cache bleiben EIN gemeinsames Objekt in EINEM
    Prozess – die Prozess-Race, die -n auto verursacht hat, kann hier nicht
    auftreten (siehe Makefile-Kommentar). _get_agent() ist per Lock gegen
    die verbleibende Race beim Erststart eines Agenten abgesichert.
    """
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(_run_and_record, agent_cfg, task) for agent_cfg, task in _PARAMS]
        concurrent.futures.wait(futures)

    metric_jobs = [
        (agent_cfg, task, metric_name)
        for agent_cfg, task in _PARAMS
        for metric_name in _LLM_JUDGE_METRICS
        if metric_name in _UC["metrics"]
    ]
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        futures = [
            executor.submit(_prewarm_metric, agent_cfg, task, metric_name)
            for agent_cfg, task, metric_name in metric_jobs
        ]
        concurrent.futures.wait(futures)


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
    """Prüft ob der Agent die Gesamtaufgabe vollständig erfüllt hat.
    Score/Kosten kommen aus _metric_cache (Phase 2 in pytest_sessionstart) –
    kein API-Call mehr hier, nur noch Auswertung des Vorgewärmten."""
    if "task_completion" not in _UC["metrics"]:
        pytest.skip(f"task_completion nicht in Metrik-Set von {_UC['id']}")

    _skip_if_error(agent_cfg, task)
    key = (agent_cfg["id"], task["id"], "task_completion")
    score, judge_cost = _metric_cache.get(key, (None, 0.0))
    if score is None:
        pytest.fail(f"TaskCompletion: Metrik-Berechnung fehlgeschlagen – {_metric_errors.get(key, '?')}")
    _, tracker = _get_agent(agent_cfg)
    tracker.update_metrics(task["id"], {
        "task_completion": round(score, 3),
        "eval_cost_usd": round(tracker.get_eval_cost(task["id"]) + judge_cost, 6),
    })
    assert score >= 0.7, f"TaskCompletion: {score:.2f} < 0.7"


@pytest.mark.parametrize("agent_cfg,task", _PARAMS, ids=_IDS)
def test_answer_relevancy(agent_cfg, task):
    """Prüft ob die Antwort des Agenten relevant zur gestellten Aufgabe ist (UC1/UC2).
    Score/Kosten kommen aus _metric_cache (Phase 2 in pytest_sessionstart)."""
    if "answer_relevancy" not in _UC["metrics"]:
        pytest.skip(f"answer_relevancy nicht in Metrik-Set von {_UC['id']}")

    _skip_if_error(agent_cfg, task)
    key = (agent_cfg["id"], task["id"], "answer_relevancy")
    score, judge_cost = _metric_cache.get(key, (None, 0.0))
    if score is None:
        pytest.fail(f"AnswerRelevancy: Metrik-Berechnung fehlgeschlagen – {_metric_errors.get(key, '?')}")
    _, tracker = _get_agent(agent_cfg)
    tracker.update_metrics(task["id"], {
        "answer_relevancy": round(score, 3),
        "eval_cost_usd": round(tracker.get_eval_cost(task["id"]) + judge_cost, 6),
    })
    assert score >= 0.7, f"AnswerRelevancy: {score:.2f} < 0.7"


@pytest.mark.parametrize("agent_cfg,task", _PARAMS, ids=_IDS)
def test_faithfulness(agent_cfg, task):
    """Prüft Zitationstreue – Antwort darf nur Fakten aus dem Retrieval-Kontext enthalten (UC3).
    Score/Kosten kommen aus _metric_cache (Phase 2 in pytest_sessionstart)."""
    if "faithfulness" not in _UC["metrics"]:
        pytest.skip(f"faithfulness nicht in Metrik-Set von {_UC['id']}")

    _skip_if_error(agent_cfg, task)
    key = (agent_cfg["id"], task["id"], "faithfulness")
    score, judge_cost = _metric_cache.get(key, (None, 0.0))
    if score is None:
        pytest.fail(f"Faithfulness: Metrik-Berechnung fehlgeschlagen – {_metric_errors.get(key, '?')}")
    _, tracker = _get_agent(agent_cfg)
    tracker.update_metrics(task["id"], {
        "faithfulness": round(score, 3),
        "eval_cost_usd": round(tracker.get_eval_cost(task["id"]) + judge_cost, 6),
    })
    assert score >= 0.7, f"Faithfulness: {score:.2f} < 0.7"


@pytest.mark.parametrize("agent_cfg,task", _PARAMS, ids=_IDS)
def test_hallucination(agent_cfg, task):
    """Prüft Halluzinationen – Agent darf keine Fakten erfinden (UC4).
    Score/Kosten kommen aus _metric_cache (Phase 2 in pytest_sessionstart)."""
    if "hallucination" not in _UC["metrics"]:
        pytest.skip(f"hallucination nicht in Metrik-Set von {_UC['id']}")

    _skip_if_error(agent_cfg, task)
    key = (agent_cfg["id"], task["id"], "hallucination")
    score, judge_cost = _metric_cache.get(key, (None, 0.0))
    if score is None:
        pytest.fail(f"Hallucination: Metrik-Berechnung fehlgeschlagen – {_metric_errors.get(key, '?')}")
    passed = score <= 0.5
    _, tracker = _get_agent(agent_cfg)
    tracker.update_metrics(task["id"], {
        "hallucination": round(score, 3),
        "eval_cost_usd": round(tracker.get_eval_cost(task["id"]) + judge_cost, 6),
    })
    assert passed, f"Hallucination zu hoch: {score:.2f} > 0.5"


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


# ─── Abschluss-Report nach allen Tests ────────────────────────────────────────

def finalize_and_report() -> None:
    """Berechnet passed-Flag aus gespeicherten Scores und gibt Report pro Agent aus.

    Wird über conftest.py:pytest_sessionfinish aufgerufen – siehe warm_caches()
    für die Erklärung, warum dieser Hook nicht hier in der Testdatei selbst
    als pytest_sessionfinish definiert sein darf."""
    for agent_id, tracker in _trackers.items():
        if not tracker.records:
            continue
        for r in tracker.records:
            if r.get("error"):
                r["passed"] = False
        # finalize_passed()/_save() MÜSSEN für jeden Agenten laufen, auch wenn
        # ein anderer Agent zuvor beim reinen Konsolen-Report crasht (z.B.
        # UnicodeEncodeError bei Emojis auf Windows-Terminals mit cp1252 –
        # real beobachtet). Eine kaputte Konsolenausgabe darf nie verhindern,
        # dass die Datenkorrektheit für die übrigen Agenten sichergestellt wird.
        tracker.finalize_passed()
        tracker._save()
        try:
            print(f"\n{'='*70}")
            print(f"  Use Case: {_UC['id']}  |  Agent: {agent_id}")
            tracker.print_report()
        except UnicodeEncodeError:
            print(f"  (Konsolen-Report für {agent_id} wegen Encoding-Problem übersprungen – Daten sind trotzdem korrekt gespeichert)")
