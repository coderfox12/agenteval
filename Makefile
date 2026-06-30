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

.PHONY: all eval eval-all smoke security compliance \
        functionality report report-html install clean

USE_CASE ?= uc1

# ── Hauptziele ────────────────────────────────────────────────────────────────
all: eval

eval: smoke security functionality report
	@echo ""
	@echo "✅ Alle Evals abgeschlossen (USE_CASE=$(USE_CASE)). Report: results/report.html"

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

# ── R0: Smoke Test – Judge + alle Agenten aus agents.yaml ──────────────────────
# Schlägt einer fehl, bricht make ab – security/functionality/report laufen
# dann nicht mehr (make stoppt bei der ersten fehlschlagenden Prerequisite).
smoke:
	python scripts/run_smoke_test.py

# ── R2/R3: Security + Compliance für alle Agenten gegen den gewählten UC ──────
# run_promptfoo_multi_agent.py führt alle (Agent × Config)-Kombinationen
# parallel aus (ThreadPoolExecutor um subprocess.run() – jeder promptfoo-Call
# ist ein eigener OS-Prozess) und erzeugt results/*_results_$(USE_CASE)_{agent_id}.json
# + Scorecards.
security:
	USE_CASE=$(USE_CASE) python scripts/run_promptfoo_multi_agent.py

# compliance ist ein Alias für security – der Runner erzeugt beides in einem Lauf.
compliance: security

# ── Funktionalität: LangGraph + DeepEval, alle Agenten gegen den UC ───────────
# KEIN -n auto: trotz xdist_group-Marker landeten Tests eines Agenten in der
# Praxis auf mehreren Worker-PROZESSEN (in CI beobachtet: gw0–gw3 für
# denselben Agenten) – _trackers/_cache sind Modul-Level-State, pro Prozess
# getrennt, jeder Worker überschreibt beim Speichern die Datei des
# vorherigen. Die eigentliche Parallelität läuft jetzt INNERHALB des
# Test-Moduls per ThreadPoolExecutor (pytest_sessionstart in conftest.py
# ruft test_functionality.warm_caches() auf, zwei Phasen: erst alle
# Agent-Läufe parallel, dann alle Judge-Bewertungen parallel – WICHTIG:
# pytest erkennt pytest_sessionstart/pytest_sessionfinish NUR in
# conftest.py, nicht in test_functionality.py selbst, sonst wird der Hook
# nie aufgerufen) – ein Prozess, mehrere Threads, daher
# kein Cross-Prozess-Datenverlust, aber trotzdem alles gleichzeitig statt
# sequenziell. Dieser Job läuft in der CI außerdem als eigener, zu
# security_compliance PARALLELER Job (siehe promptfoo.yml) – beide hängen
# nur von smoke ab, nicht voneinander.
functionality:
	cd evals/functionality && \
	  USE_CASE=$(USE_CASE) pytest test_functionality.py -v

# ── HTML-Report (Multi-Agent-Vergleich für den gewählten UC) ──────────────────
report-html:
	agenteval-report --use-case $(USE_CASE) --out results/report.html

report: report-html
	@echo "📊 Report generiert: results/report.html"

# ── Setup ─────────────────────────────────────────────────────────────────────
install:
	pip install -e .

# ── Aufräumen ─────────────────────────────────────────────────────────────────
clean:
	rm -rf results
