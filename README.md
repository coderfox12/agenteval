# Agent-Eval@OVB

**Reproduzierbares Evaluations- und Sicherheits-Framework für agentische KI-Systeme im regulierten Finanzumfeld**

OVB Holding AG × TU Darmstadt – Kooperatives Seminar Sommersemester 2026

---

## Schnellstart

```bash
# 1. Voraussetzungen: Python 3.11+, Node.js 20+
cp .env.example .env          # AGENT_API_KEY + JUDGE_API_KEY eintragen
pip install -e .              # agenteval-ovb als Package installieren
pip install -r evals/functionality/requirements.txt  # DeepEval + LangGraph

# 2. Alle Evals für Use Case 1 (Standard) + HTML-Report
make eval
# → report_uc1.html           (Benchmark-Report mit Agenten-Vergleich)
# → compliance_scorecard_uc1_*.json  (EU AI Act Mapping pro Agent)

# 3. Anderen Use Case evaluieren
make eval USE_CASE=uc2

# 4. Alle vier Use Cases sequenziell
make eval-all
```

---

## Architektur: Zwei orthogonale Dimensionen

```
USE_CASE  ×  agents.yaml
   │               │
   │               └─ WOMIT wird getestet? (Modell/Endpunkt)
   └─ WAS wird getestet? (Domäne, Tools, Tasks, Metriken)
```

| Use Case | Domäne | Regulatorik |
|----------|--------|-------------|
| **uc1** – Suitability-Check | Anlageeignungsprüfung | IDD Art. 30 / §7 VersVermV |
| **uc2** – Onboarding | KYC / Kundendaten | GwG §10 / AMLA |
| **uc3** – Compliance-Triage | Regulatorische Einordnung | EU AI Act / OVB-Governance |
| **uc4** – Beratungsdokumentation | Protokollerstellung | §61 VVG |
| **uc0** – Generische Baseline | Allg. Finanzberatung | (kein fachlicher UC) |

---

## Evaluations-Dimensionen

| Dimension | Tool | Metriken |
|-----------|------|---------|
| **D1 Funktionalität** | LangGraph + DeepEval | `task_completion` (Kern, UC-übergreifend) + UC-spezifisch: `tool_correctness`, `answer_relevancy`, `faithfulness` (UC3), `hallucination` + `required_fields` (UC4) |
| **D2 Sicherheit** | promptfoo | Prompt-Injection-Resistenz (9 Angriffsklassen, 100+ Tests); generische Baseline + UC-spezifisch |
| **D3 Compliance** | promptfoo + Scorecard | EU AI Act Art. 9/13/14/15/52; generische Baseline (14 Tests) + UC-spezifisch |
| **Wirtschaftlichkeit** *(Querschnitt)* | CostTracker + Report | Tokens, Kosten in USD, Latenz (p50/p95) |

### Zweischichtige D2/D3-Struktur

```
GENERISCHE BASELINE (scope: generic)   – läuft bei JEDEM Use Case
  evals/security/security_eval.yaml         (40 Tests, AgentDojo/InjecAgent)
  evals/security/security_eval_finance.yaml (60 Tests, Finance-spezifisch)
  evals/compliance/compliance_eval.yaml     (14 Tests, EU AI Act)

UC-SPEZIFISCH (scope: uc_specific)     – nur für den gewählten UC
  evals/security/usecases/{uc}/security_eval.yaml
  evals/compliance/usecases/{uc}/compliance_eval.yaml
```

---

## Make-Targets

```bash
make eval [USE_CASE=uc1]  # D2+D3+D1 + HTML-Report (Standard: uc1)
make eval-all             # Alle 4 Use Cases sequenziell
make smoke                # R0: Hello-World Smoke Test
make security             # D2+D3: Security & Compliance für alle Agenten
make compliance           # Alias für 'make security' (Runner deckt beides ab)
make functionality        # D1: LangGraph + DeepEval für alle Agenten
make report               # HTML-Report erzeugen
make benchmark            # Multi-Modell-Vergleich
make install              # pip install -e .
make clean                # Generierte Ergebnisdateien löschen
```

---

## Package-Struktur

```
agenteval_ovb/                  ← installierbares Python-Package
  scorecard.py                  ← EU AI Act Scorecard-Generator (CLI: agenteval-scorecard)
  report.py                     ← HTML-Report-Generator (CLI: agenteval-report)
  pricing.py                    ← Kostenberechnung nach Modell

evals/
  security/
    security_eval.yaml          ← D2: Generische Baseline (40 Tests, AgentDojo/InjecAgent)
    security_eval_finance.yaml  ← D2: Finance-Baseline (60 Tests)
    usecases/{uc}/
      security_eval.yaml        ← D2: UC-spezifische Angriffe (scope: uc_specific)
  compliance/
    compliance_eval.yaml        ← D3: Generische Baseline (14 Tests, EU AI Act)
    usecases/{uc}/
      compliance_eval.yaml      ← D3: UC-spezifische Compliance-Tests
  functionality/
    agent/
      graph.py                  ← UseCaseAgent (LangGraph ReAct, Tools/Prompt injiziert)
    usecases/
      registry.py               ← UC-Auswahl via USE_CASE-Env
      uc0_generic/              ← Generische D1-Baseline (keine Fachdomäne)
      uc1_suitability/          ← D1: IDD-Suitability-Tests
      uc2_onboarding/           ← D1: KYC/GwG-Tests
      uc3_compliance_triage/    ← D1: EU-AI-Act-RAG-Tests
      uc4_beratungsdoku/        ← D1: §61-VVG-Protokoll-Tests
    test_functionality.py       ← DeepEval-Test-Suite (pytest)
    cost_tracker.py             ← Token/Kosten/Latenz-Tracking

scripts/
  run_promptfoo_multi_agent.py  ← D2+D3-Runner (alle Agenten × Baseline + UC-Suite)
  run_benchmark.js              ← Multi-Modell-Benchmark

agents.yaml                     ← Agenten-Konfiguration (Modell, API-Key-Env, Endpunkt)
.github/workflows/promptfoo.yml ← CI-Pipeline (USE_CASE: uc1)
```

---

## Reproduzierbarkeit

Alle Eval-Läufe verwenden `--no-cache` und `temperature: 0`. Der Use Case wird über die
Umgebungsvariable `USE_CASE` gesetzt (Default: `uc1`) — sowohl im Runner als auch im Report,
sodass Producer und Consumer immer dieselbe Konfiguration verwenden.

Jeder CI-Lauf speichert folgende Artefakte:

```
*_results_*.json                              # D2/D3 Ergebnisse pro (UC, Agent)
compliance_scorecard_*.json                   # EU AI Act Scorecard pro Agent
evals/functionality/functionality_costs_*.json # D1 Kosten/Metriken pro (UC, Agent)
report.html                                   # Konsolidierter HTML-Report
```

---

## CLI-Kommandos (nach `pip install -e .`)

```bash
agenteval-scorecard compliance_results_uc1_gpt.json --use-case uc1
agenteval-report --use-case uc1 --out report_uc1.html
agenteval-report --help
```

---

## Voraussetzungen

| Werkzeug | Version | Zweck |
|----------|---------|-------|
| Python | ≥ 3.11 | Package, DeepEval, Scorecard |
| Node.js | ≥ 20 | promptfoo |
| AGENT_API_KEY | – | Getestete Agenten (Pflicht) |
| JUDGE_API_KEY | – | LLM-as-Judge / DeepEval (Pflicht) |
| OPENROUTER_API_KEY | – | Zusätzliche Agenten via OpenRouter (optional) |

---

## Red-Team-Suite (D2)

100+ kuratierte Tests in 9 Angriffsklassen (generische Baseline) + UC-spezifische Erweiterungen:

| Klasse | Beschreibung | Basis |
|--------|-------------|-------|
| DPI | Direct Prompt Injection | AgentDojo |
| IPI | Indirect Prompt Injection | InjecAgent |
| DE | Data Exfiltration | InjecAgent/AgentDojo |
| GH | Goal Hijacking | AgentDojo |
| IO | Instruction Override | AgentDojo |
| CP | Context Poisoning | AgentDojo |
| PA | Persona Adoption | OVB-spezifisch |
| SL | Secret Data Leakage | OVB-spezifisch |
| MSI | Multi-Step Injection | OVB-spezifisch |

Taxonomie: [`docs/security_taxonomy.yaml`](docs/security_taxonomy.yaml)

---

## Lizenz

Apache 2.0 – siehe [LICENSE](LICENSE)

OVB Holding AG erhält ein uneingeschränktes, nicht-exklusives Nutzungsrecht an allen Artefakten.
