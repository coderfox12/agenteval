# Agent-Eval@OVB

**Reproduzierbares Evaluations- und Sicherheits-Framework für agentische KI-Systeme im regulierten Finanzumfeld**

OVB Holding AG × TU Darmstadt – Kooperatives Seminar Sommersemester 2026

---

## Schnellstart

Du bist gerade frisch auf der Repo-Seite gelandet und hast noch nichts installiert?
Hier die komplette Strecke bis zum fertigen HTML-Report, in zwei Teilen:

### Schritt 0: Einmalige Vorbereitung (für BEIDE Wege gleich nötig)

```bash
git clone <repo-url> && cd agenteval
pip install -e .                                      # agenteval-ovb als Package
pip install -r evals/functionality/requirements.txt   # DeepEval + LangGraph
```

Zusätzlich nötig: **Node.js ≥ 20** (für promptfoo) muss installiert sein – sonst nichts.

Danach entscheidest du dich für GENAU EINEN der beiden folgenden Wege. Beide führen
am Ende zum selben `results/report.html`, rufen intern auch dieselben Skripte auf – der
Unterschied ist nur, *wie* du `.env`/`agents.yaml` befüllst und den Lauf startest.

### Weg 1: Terminal (von Hand konfigurieren)

```bash
cp .env.example .env
# .env im Editor öffnen: AGENT_API_KEY_1 + JUDGE_API_KEY eintragen
# agents.yaml im Editor öffnen: Judge + mind. einen Agenten eintragen
#   (model, api_key_env, api_base – api_base ist Pflicht, siehe Kommentare in der Datei)

make eval                     # Use Case 1 (Standard): D1+D2+D3 + HTML-Report
# → results/report.html       (direkt im Browser öffnen)

make eval USE_CASE=uc2        # optional: anderen Use Case evaluieren
make eval-all                 # optional: alle vier Use Cases sequenziell
```

### Weg 2: Web-App (nichts von Hand editieren)

```bash
# Windows: einfach start.bat doppelklicken – installiert fehlende
# Abhängigkeiten automatisch und startet den Server.
start.bat

# Oder manuell, plattformunabhängig:
pip install -r webapp/requirements.txt
streamlit run webapp/app.py
```

Browser öffnet sich automatisch unter `http://localhost:8501` (Tab „API & Modelle“).
Von dort, der Reihe nach:

1. **API & Modelle** – Agent- und Judge-API-Keys eintragen, „.env speichern“ klicken
2. **Agenten** – Judge- und Agenten-Konfiguration (Modell, api_base, provider_pin) eintragen, „agents.yaml speichern“ klicken
3. **Use Case & Evaluierung** – Use Case (UC0–UC4) wählen, gewünschte Dimensionen (D1/D2/D3) ankreuzen, „Evaluierung starten“ klicken – Log läuft live im Browser mit
4. Nach Abschluss: **HTML-Report** direkt eingebettet sichtbar (Agenten-Vergleich, Radar-Chart) plus Button **„Report herunterladen (HTML)“** → das ist die fertige `results/report.html`-Datei, z. B. zum Versenden per Mail
5. **Hilfe & Dokumentation** (Sidebar) – genau diese README, direkt in der App nachlesbar

Weder `.env` noch `agents.yaml` müssen für Weg 2 vorher angelegt werden – die Web-App
erzeugt beide Dateien selbst beim ersten Speichern. Da es ganz normale Dateien im
Projekt-Root sind, wirken Änderungen über die Web-App sofort auch bei `make eval` im
Terminal und umgekehrt – beide Wege teilen sich dieselbe Konfiguration und denselben
`results/`-Ordner für alle erzeugten Ergebnis-Dateien.

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
make eval [USE_CASE=uc1]  # D2+D3+D1 + HTML-Report → results/report.html (Standard: uc1)
make eval-all             # Alle 4 Use Cases sequenziell
make smoke                # R0: Hello-World Smoke Test
make security             # D2+D3: Security & Compliance für alle Agenten
make compliance           # Alias für 'make security' (Runner deckt beides ab)
make functionality        # D1: LangGraph + DeepEval, Agenten parallel (-n auto)
make report               # HTML-Report erzeugen → results/report.html
make install              # pip install -e .
make clean                # results/-Ordner löschen
```

---

## Package-Struktur

`agenteval_ovb/` ist bewusst klein gehalten: Es ist das EINZIGE, was `pip install -e .`
tatsächlich installiert (siehe `pyproject.toml`) – die wiederverwendbare Bibliothekslogik
plus die beiden CLI-Befehle `agenteval-report`/`agenteval-scorecard`. Alles andere liegt
absichtlich daneben statt darin, weil es etwas anderes ist als installierbarer Bibliothekscode:

- `evals/` sind Test-**Inhalte** (YAML-Suiten, Task-Definitionen, der LangGraph-Agent) –
  werden direkt von `pytest`/`promptfoo` ausgeführt, nicht importiert.
- `scripts/` sind eigenständig lauffähige Orchestrierungs-Skripte, die das Package benutzen.
- `webapp/` ist eine komplett separate Streamlit-Anwendung, die nur Make-Targets/Skripte
  per Subprozess aufruft.
- `docs/` ist reine Referenzdokumentation, keine Python-Logik.

Würde man das alles in `agenteval_ovb/` packen, würde `pip install -e .` plötzlich auch
YAML-Testdaten, JS-Dateien und die ganze Web-App mit ausliefern – unnötig aufgebläht für
etwas, das eigentlich nur drei kleine Python-Module sein soll.

Aus demselben Grund liegt auch `promptfooconfig.yaml` im Root statt in `evals/`: `promptfoo`
sucht standardmäßig nach genau dieser Datei im aktuellen Arbeitsverzeichnis (Default-Config,
analog zu `package.json` bei npm). Sie ist bewusst die einzige Config mit diesem Namen – der
günstige R0-Smoke-Test. Die eigentlichen D2/D3-Suiten in `evals/` heißen absichtlich anders
und werden immer explizit per `--config <pfad>` angesteuert, da es davon viele gibt (pro
Use Case, pro Scope).

```
results/                        ← ALLE generierten Ergebnisdateien (gitignored, entsteht
                                   beim ersten Lauf von selbst; siehe Reproduzierbarkeit)

agenteval_ovb/                  ← installierbares Python-Package (das EINZIGE, was
                                   pip install -e . tatsächlich verpackt)
  scorecard.py                  ← EU AI Act Scorecard-Generator (CLI: agenteval-scorecard)
  report.py                     ← HTML-Report-Generator (CLI: agenteval-report)
  pricing.py                    ← Kostenberechnung nach Modell

webapp/                         ← separate Streamlit-App, ruft Make-Targets/Skripte auf
  app.py                        ← Konfiguration (.env/agents.yaml) + Live-Ausführung im Browser

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
  run_smoke_test.py             ← R0-Smoke-Test (Judge + alle Agenten)
  generate_tests_from_injecagent.py ← Generiert D2-Testfälle aus InjecAgent-Datensätzen

agents.yaml                     ← Agenten-Konfiguration (Modell, API-Key-Env, Endpunkt)
promptfooconfig.yaml            ← R0-Smoke-Test-Config (promptfoo-Default-Dateiname, daher Root)
.github/workflows/promptfoo.yml ← CI-Pipeline (USE_CASE: uc1)
```

---

## Reproduzierbarkeit

Alle Eval-Läufe verwenden `--no-cache` und `temperature: 0`. Der Use Case wird über die
Umgebungsvariable `USE_CASE` gesetzt (Default: `uc1`) — sowohl im Runner als auch im Report,
sodass Producer und Consumer immer dieselbe Konfiguration verwenden.

Jeder Lauf (Terminal, Web-App oder CI) sammelt alle Artefakte in einem einzigen,
gitignorten `results/`-Ordner:

```
results/*_results_*.json          # D2/D3 Ergebnisse pro (UC, Agent)
results/compliance_scorecard_*.json # EU AI Act Scorecard pro Agent
results/functionality_costs_*.json  # D1 Kosten/Metriken pro (UC, Agent)
results/report.html                 # Konsolidierter HTML-Report
```

---

## CLI-Kommandos (nach `pip install -e .`)

```bash
agenteval-scorecard results/compliance_results_uc1_gpt.json --use-case uc1
agenteval-report --use-case uc1 --out results/report_uc1.html
agenteval-report --help
```

---

## Voraussetzungen

| Werkzeug | Version | Zweck |
|----------|---------|-------|
| Python | ≥ 3.11 | Package, DeepEval, Scorecard |
| Node.js | ≥ 20 | promptfoo |
| AGENT_API_KEY_1 (mind. einer) | – | Getestete Agenten (Pflicht) |
| JUDGE_API_KEY | – | LLM-as-Judge / DeepEval (Pflicht) |
| AGENT_API_KEY_2, _3, ... | – | Weitere Agenten, beliebiger Anbieter (optional) |

---

## Lokale Modelle anbinden (Ollama / LM Studio)

Agenten müssen nicht über einen Cloud-Anbieter laufen. Sowohl Ollama als auch LM Studio
bieten eine OpenAI-kompatible API (`/v1/chat/completions` etc.) an — das Framework braucht
dafür KEINEN Sonder-Code, nur einen normalen Eintrag in `agents.yaml` mit passendem
`api_base` (siehe Kommentare dort).

Beispiel: Mac Studio der OVB (Ollama, 21 vorinstallierte Modelle), nur per VPN erreichbar.

> **Windows-PowerShell:** `curl` ist dort nur ein Alias für `Invoke-WebRequest` und
> liefert kein rohes JSON – das betrifft beide `curl`-Aufrufe unten (Health-Check und
> Modellliste). Stattdessen `curl.exe` (echtes curl, seit Win10 vorinstalliert) oder
> `Invoke-RestMethod` verwenden:
> ```powershell
> curl.exe http://10.233.217.20:11434/api/tags
> # oder mit automatischem JSON-Parsing:
> Invoke-RestMethod http://10.233.217.20:11434/api/tags | ConvertTo-Json -Depth 4
> ```
> In Git Bash, WSL oder macOS/Linux-Terminal funktioniert `curl` dagegen wie unten
> gezeigt unverändert.

**1. VPN verbinden** – Cisco AnyConnect / Cisco Secure Client, Server-URL
`https://connect.ovb.eu/vpn` (Login mit stud.tu-darmstadt-Mailadresse; Passwort zuvor
ggf. über https://selfservice.ovb.eu/ per SMS neu setzen). Verbindung prüfen:

```bash
curl http://10.233.217.20:11434/
# → "Ollama is running"
```

**2. Verfügbare Modellnamen abfragen** – `model:` in `agents.yaml` muss exakt matchen:

```bash
curl http://10.233.217.20:11434/api/tags
```

**3. Agent-Eintrag ergänzen:**

```yaml
# agents.yaml
  - id: mac-studio-llama
    label: "Llama 3.1 (OVB Mac Studio, Ollama)"
    model: llama3.1:8b            # exakter Name aus /api/tags
    api_key_env: AGENT_API_KEY_3
    api_base: http://10.233.217.20:11434/v1
```

```bash
# .env
AGENT_API_KEY_3=dummy   # Ollama prüft den Key nicht, das SDK braucht aber einen nicht-leeren String
```

Zu beachten:
- **Tool-Calling**: Der Functionality-Agent nutzt `llm.bind_tools()`
  ([evals/functionality/agent/graph.py](evals/functionality/agent/graph.py)) – das
  unterstützen nicht alle Ollama-Modelle zuverlässig (z. B. `llama3.1`/`qwen2.5` sind
  dafür bekannt geeignet).
- **VPN muss während des gesamten Eval-Laufs aktiv bleiben** – für automatisierte/
  wiederkehrende Läufe (z. B. CI) ungeeignet, für manuelle Testläufe aber problemlos.

**LM Studio statt Ollama:** Gleiches Prinzip, andere Adresse. LM Studio hört
standardmäßig auf Port `1234` statt `11434`, die Modellliste liefert
`GET /v1/models` statt `/api/tags` (Server muss vorher im LM-Studio-UI unter
"Developer" gestartet werden). `api_base` in `agents.yaml` entsprechend anpassen,
z. B. `http://<host>:1234/v1` – der Rest (Agent-Eintrag, `.env`-Key, Tool-Calling-
Vorbehalt) bleibt identisch.

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
