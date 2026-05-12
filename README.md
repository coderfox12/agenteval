# Agent-Eval@OVB

**Reproduzierbares Evaluations- und Sicherheits-Framework für agentische KI-Systeme im regulierten Finanzumfeld**

OVB Holding AG × TU Darmstadt – Kooperatives Seminar Sommersemester 2026

---

## Schnellstart

```bash
# 1. Voraussetzungen: Python 3.11+, Node.js 20+, OPENAI_API_KEY
cp .env.example .env                               # OPENAI_API_KEY eintragen
pip install -e .                                   # agenteval-ovb als Package installieren
pip install -r evals/functionality/requirements.txt  # DeepEval + LangGraph

# 2. Alle Evals + HTML-Report
make eval
# → report.html (Benchmark-Report)
# → compliance_scorecard.json (EU AI Act Mapping)
```

---

## Evaluations-Dimensionen

| Dimension | Tool | Output |
|-----------|------|--------|
| **D1 Funktionalität** | LangGraph + DeepEval | Task-Completion, Tool-Use-Correctness |
| **D2 Sicherheit** | promptfoo | Prompt-Injection-Resistenz, Data-Leakage-Rate |
| **D3 Compliance** | promptfoo + Scorecard | EU AI Act Art. 9/13/14/15/52 |
| **Wirtschaftlichkeit** *(Querschnitt)* | cost_report.js | Tokens, Kosten in USD, Latenz (p50/p95) |

---

## Make-Targets

```bash
make eval            # Alle Evals + Scorecard + HTML-Report (Hauptziel)
make smoke           # R0: Hello-World Smoke Test
make security        # R2: Sicherheits-Taxonomie (AgentDojo/InjecAgent)
make security-finance  # R2: Finance-Kontext (manuell kuratiert)
make security-all    # R2: Beide Security-Suiten
make compliance      # R3: EU AI Act Compliance
make scorecard       # Compliance-Scorecard generieren
make functionality   # D1: LangGraph + DeepEval Agent Eval
make report          # Scorecard + HTML-Report generieren
make report-html     # Nur HTML-Report
make benchmark       # Multi-Modell-Vergleich (benötigt MISTRAL_API_KEY + GROQ_API_KEY)
make install         # pip install -e . (einmalig)
make clean           # Alle generierten Ergebnisdateien löschen
```

---

## Package-Struktur

```
agenteval_ovb/            ← installierbares Python-Package (pip install -e .)
  __init__.py
  scorecard.py            ← EU AI Act Scorecard-Generator (CLI: agenteval-scorecard)
  report.py               ← HTML-Report-Generator (CLI: agenteval-report)

evals/
  security/
    security_eval.yaml              ← R2: Allgemeine Red-Team-Suite (AgentDojo/InjecAgent)
    security_eval_finance.yaml      ← R2: Finance-spezifische Angriffe (110+ Tests)
  compliance/
    compliance_eval.yaml            ← R3: EU AI Act Compliance-Tests
  functionality/
    agent/                          ← LangGraph Finance Advisory Agent
    test_functionality.py           ← DeepEval Test Suite
    tasks/ovb_tasks.yaml            ← Deklarative Task-Definitionen
  benchmark/
    model_comparison.yaml           ← Multi-Modell-Vergleich

docs/
  security_taxonomy.yaml            ← Angriffsklassen-Taxonomie
  eu_ai_act_mapping.yaml            ← Regulatorisches Mapping

scripts/
  cost_report.js                    ← Wirtschaftlichkeits-Report (Token, Kosten, Latenz)
  compliance_scorecard.py           ← Wrapper → agenteval_ovb.scorecard
  generate_tests_from_injecagent.py ← InjecAgent JSONL → promptfoo YAML
  run_benchmark.js                  ← Multi-Modell-Benchmark Runner

.github/workflows/promptfoo.yml     ← CI-Pipeline (GitHub Actions)
pyproject.toml                      ← Package-Konfiguration
Makefile                            ← Unified Eval Runner
```

---

## Reproduzierbarkeit

Alle Eval-Läufe verwenden `--no-cache` und `temperature: 0`. Für exakte Reproduzierbarkeit:

```bash
# Versionen fixieren (nach erstem erfolgreichen Lauf)
pip freeze > requirements-lock.txt
npx promptfoo@latest --version   # im README dokumentieren
```

Ergebnisdateien als GitHub-Artifacts: jeder CI-Lauf speichert `security_results.json`,
`compliance_results.json`, `compliance_scorecard.json`, `functionality_costs.json` und
`report.html` als downloadbare Artefakte.

---

## CLI-Kommandos (nach `pip install -e .`)

```bash
agenteval-scorecard compliance_results.json   # EU AI Act Scorecard
agenteval-report --out report.html            # HTML-Benchmark-Report
agenteval-report --help                       # Alle Optionen
```

---

## Voraussetzungen

| Werkzeug | Version | Zweck |
|----------|---------|-------|
| Python | ≥ 3.11 | Package, DeepEval, Scorecard |
| Node.js | ≥ 20 | promptfoo, cost_report.js |
| OPENAI_API_KEY | – | Alle Evals (Pflicht) |
| MISTRAL_API_KEY | – | `make benchmark` (optional) |
| GROQ_API_KEY | – | `make benchmark` (optional) |

---

## Red-Team-Suite (R2)

110+ kuratierte Tests in 9 Angriffsklassen:

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
