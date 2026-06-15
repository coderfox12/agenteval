# agenteval-ovb – Unified Eval Runner
#
# Verwendung: make <target> [USE_CASE=uc1|uc2|uc3|uc4]
#
# Beispiele:
#   make eval USE_CASE=uc2           # Volle Evaluation für UC2
#   make functionality USE_CASE=uc3  # Nur Functionality für UC3
#   make eval-all                    # Alle 4 Use Cases sequenziell
#
# Voraussetzungen:
#   - Node.js + npx  (für promptfoo)
#   - Python 3.11+   (für Funktionalitäts-Eval und Scorecard)
#   - pip install -e . (einmalig, installiert agenteval-ovb als Package)
#   - OPENAI_API_KEY in .env oder Umgebungsvariable
#
# Optionale Erweiterungen:
#   - MISTRAL_API_KEY          → für make benchmark (Mistral-Provider)
#   - GROQ_API_KEY             → für make benchmark (Open-Source-Provider)
#   - LANGCHAIN_TRACING_V2=true + LANGCHAIN_API_KEY → LangSmith-Tracing

.PHONY: all eval eval-all smoke security security-finance security-all \
        compliance scorecard functionality report report-html benchmark install clean

USE_CASE ?= uc1
SEC_DIR  := evals/security/usecases/$(USE_CASE)
COMP_DIR := evals/compliance/usecases/$(USE_CASE)
COST_FILE := functionality_costs_$(USE_CASE).json

# ── Hauptziele ────────────────────────────────────────────────────────────────
all: eval

eval: security security-finance compliance functionality report
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
	npx promptfoo@latest eval --no-cache --config promptfooconfig.yaml

# ── R2: Sicherheit ────────────────────────────────────────────────────────────
security:
	npx promptfoo@latest eval --no-cache \
	  --config $(SEC_DIR)/security_eval.yaml \
	  --output security_results_$(USE_CASE).json
	node scripts/cost_report.js security_results_$(USE_CASE).json

security-finance:
	@if [ -f $(SEC_DIR)/security_eval_finance.yaml ]; then \
	  npx promptfoo@latest eval --no-cache \
	    --config $(SEC_DIR)/security_eval_finance.yaml \
	    --output security_finance_results_$(USE_CASE).json; \
	  node scripts/cost_report.js security_finance_results_$(USE_CASE).json; \
	else \
	  echo "ℹ️  Kein security_eval_finance.yaml für $(USE_CASE) – übersprungen."; \
	fi

security-all: security security-finance

# ── R3: Compliance ────────────────────────────────────────────────────────────
compliance:
	npx promptfoo@latest eval --no-cache \
	  --config $(COMP_DIR)/compliance_eval.yaml \
	  --output compliance_results_$(USE_CASE).json
	node scripts/cost_report.js compliance_results_$(USE_CASE).json

# ── Compliance Scorecard (EU AI Act Mapping) ──────────────────────────────────
scorecard:
	agenteval-scorecard compliance_results_$(USE_CASE).json --use-case $(USE_CASE)

# ── Funktionalität: LangGraph + DeepEval ─────────────────────────────────────
functionality:
	cd evals/functionality && \
	  USE_CASE=$(USE_CASE) COST_FILE=$(COST_FILE) \
	  deepeval test run test_functionality.py -v

# ── HTML-Report ───────────────────────────────────────────────────────────────
report-html:
	agenteval-report \
	  --security security_results_$(USE_CASE).json \
	  --security security_finance_results_$(USE_CASE).json \
	  --compliance compliance_results_$(USE_CASE).json \
	  --scorecard compliance_scorecard.json \
	  --functionality evals/functionality/$(COST_FILE) \
	  --use-case $(USE_CASE) \
	  --out report_$(USE_CASE).html

# ── Reporting (Scorecard + HTML) ──────────────────────────────────────────────
report: scorecard report-html
	@echo "📊 Reports generiert: compliance_scorecard.json, report_$(USE_CASE).html"

# ── Multi-Modell-Benchmark (Vendor Neutrality) ────────────────────────────────
# Benötigt: MISTRAL_API_KEY + GROQ_API_KEY (beide kostenlos erhältlich)
benchmark:
	node scripts/run_benchmark.js

# ── Setup ─────────────────────────────────────────────────────────────────────
install:
	pip install -e .

# ── Aufräumen ─────────────────────────────────────────────────────────────────
clean:
	rm -f *_results_*.json compliance_scorecard.json report_*.html
	rm -f evals/functionality/functionality_costs_*.json
