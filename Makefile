# agenteval-ovb – Unified Eval Runner
#
# Verwendung: make <target>
#
# Voraussetzungen:
#   - Node.js + npx  (für promptfoo)
#   - Python 3.11+   (für Funktionalitäts-Eval und Scorecard)
#   - OPENAI_API_KEY in .env oder Umgebungsvariable
#
# Optionale Erweiterungen:
#   - MISTRAL_API_KEY          → für make benchmark (Mistral-Provider)
#   - Ollama mit llama3:8b     → für make benchmark (Open-Source-Provider)
#   - LANGCHAIN_TRACING_V2=true + LANGCHAIN_API_KEY → LangSmith-Tracing

.PHONY: all eval smoke security security-finance security-all \
        compliance scorecard functionality report benchmark install clean

# ── Hauptziel: Alle Evals ─────────────────────────────────────────────────────
all: eval

eval: security compliance functionality report
	@echo ""
	@echo "✅ Alle Evals abgeschlossen."

# ── R0: Smoke Test ────────────────────────────────────────────────────────────
smoke:
	npx promptfoo@latest eval --no-cache --config promptfooconfig.yaml

# ── R2: Sicherheit ────────────────────────────────────────────────────────────
security:
	npx promptfoo@latest eval --no-cache \
	  --config evals/security/security_eval.yaml \
	  --output security_results.json
	node scripts/cost_report.js security_results.json

security-finance:
	npx promptfoo@latest eval --no-cache \
	  --config evals/security/security_eval_finance.yaml \
	  --output security_finance_results.json
	node scripts/cost_report.js security_finance_results.json

security-all: security security-finance

# ── R3: Compliance ────────────────────────────────────────────────────────────
compliance:
	npx promptfoo@latest eval --no-cache \
	  --config evals/compliance/compliance_eval.yaml \
	  --output compliance_results.json
	node scripts/cost_report.js compliance_results.json

# ── Compliance Scorecard (EU AI Act Mapping) ──────────────────────────────────
scorecard:
	python3 scripts/compliance_scorecard.py compliance_results.json

# ── Funktionalität: LangGraph + DeepEval ─────────────────────────────────────
functionality:
	cd evals/functionality && pytest test_functionality.py -v --tb=short

# ── Reporting ─────────────────────────────────────────────────────────────────
report: scorecard
	@echo "📊 Reports generiert."

# ── Multi-Modell-Benchmark (Vendor Neutrality) ────────────────────────────────
# Benötigt: MISTRAL_API_KEY + GROQ_API_KEY (beide kostenlos erhältlich)
benchmark:
	node scripts/run_benchmark.js

# ── Setup ─────────────────────────────────────────────────────────────────────
install:
	pip install -r evals/functionality/requirements.txt

# ── Aufräumen ─────────────────────────────────────────────────────────────────
clean:
	rm -f *_results.json compliance_scorecard.json
	rm -f evals/functionality/functionality_costs.json
