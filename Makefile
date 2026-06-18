# agenteval-ovb – Unified Eval Runner
#
# Verwendung: make <target> [USE_CASE=uc1|uc2|uc3|uc4]
#
# Zwei orthogonale Dimensionen:
#   USE_CASE  = WAS getestet wird (Domäne, Tools, Tasks, Metriken)  → uc1..uc4
#   agents.yaml = WOMIT getestet wird (Modelle/Endpunkte)           → alle Agenten
#
# Beispiele:
#   make eval USE_CASE=uc2           # Alle Agenten gegen UC2, ein Vergleichs-Report
#   make functionality USE_CASE=uc3  # Nur Functionality (alle Agenten) für UC3
#   make eval-all                    # Alle 4 Use Cases sequenziell
#
# Voraussetzungen:
#   - Node.js + npx  (für promptfoo)
#   - Python 3.11+   (für Funktionalitäts-Eval und Scorecard)
#   - pip install -e . (einmalig, installiert agenteval-ovb als Package)
#   - .env mit AGENT_API_KEY + JUDGE_API_KEY (siehe .env.example)
#
# Optionale Erweiterungen:
#   - OPENROUTER_API_KEY       → für weitere Agenten in agents.yaml (Llama etc.)
#   - MISTRAL_API_KEY          → für make benchmark (Mistral-Provider)
#   - LANGCHAIN_TRACING_V2=true + LANGCHAIN_API_KEY → LangSmith-Tracing

.PHONY: all eval eval-all smoke security compliance \
        functionality report report-html benchmark install clean

USE_CASE ?= uc1

# ── Hauptziele ────────────────────────────────────────────────────────────────
all: eval

eval: security functionality report
	@echo ""
	@echo "✅ Alle Evals abgeschlossen (USE_CASE=$(USE_CASE)). Report: report_$(USE_CASE).html"

eval-all:
	@for uc in uc1 uc2 uc3 uc4; do \
	  echo ""; \
	  echo "══════════════════════════════════════════════════"; \
	  echo "  Evaluierung Use Case: $$uc"; \
	  echo "══════════════════════════════════════════════════"; \
	  $(MAKE) eval USE_CASE=$$uc; \
	done
	@echo ""
	@echo "✅ Alle 4 Use Cases evaluiert."

# ── R0: Smoke Test ────────────────────────────────────────────────────────────
smoke:
	MODEL_NAME=gpt-5.4-mini npx promptfoo@latest eval --no-cache --config promptfooconfig.yaml

# ── R2/R3: Security + Compliance für alle Agenten gegen den gewählten UC ──────
# run_promptfoo_multi_agent.py iteriert über alle Agenten in agents.yaml
# und erzeugt *_results_$(USE_CASE)_{agent_id}.json + Scorecards.
security:
	USE_CASE=$(USE_CASE) python scripts/run_promptfoo_multi_agent.py

# compliance ist ein Alias für security – der Runner erzeugt beides in einem Lauf.
compliance: security

# ── Funktionalität: LangGraph + DeepEval, alle Agenten gegen den UC ───────────
# pytest (nicht 'deepeval test run' – behebt '-n auto'-Problem, D1 war sonst leer)
functionality:
	cd evals/functionality && \
	  USE_CASE=$(USE_CASE) pytest test_functionality.py -v

# ── HTML-Report (Multi-Agent-Vergleich für den gewählten UC) ──────────────────
report-html:
	agenteval-report --use-case $(USE_CASE) --out report_$(USE_CASE).html

report: report-html
	@echo "📊 Report generiert: report_$(USE_CASE).html"

# ── Multi-Modell-Benchmark (Vendor Neutrality) ────────────────────────────────
benchmark:
	node scripts/run_benchmark.js

# ── Setup ─────────────────────────────────────────────────────────────────────
install:
	pip install -e .

# ── Aufräumen ─────────────────────────────────────────────────────────────────
clean:
	rm -f *_results_*.json compliance_scorecard_*.json report_*.html
	rm -f evals/functionality/functionality_costs_*.json
