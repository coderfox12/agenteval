"""
HTML-Report-Generator für Agent-Eval@OVB.

Liest alle JSON-Ergebnisdateien und erzeugt einen eigenständigen HTML-Report
mit eingebettetem CSS (kein Internet nötig zum Anzeigen).

CLI:
    agenteval-report --out report.html
    agenteval-report --security security_results.json --security security_finance_results.json
                     --compliance compliance_results.json
                     --scorecard compliance_scorecard.json
                     --functionality evals/functionality/functionality_costs.json
                     --out report.html

    python -m agenteval_ovb.report --out report.html
"""

import argparse
import json
import os
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from agenteval_ovb.pricing import calc_cost_usd

# ---------------------------------------------------------------------------
# Daten-Loader
# ---------------------------------------------------------------------------

def _load_json(path: str | None) -> dict | None:
    if not path:
        return None
    p = Path(path)
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def _promptfoo_results(data: dict | None) -> list[dict]:
    if not data:
        return []
    return data.get("results", {}).get("results", data.get("results", []))


def _is_provider_error(r: dict) -> bool:
    """Erkennt ob ein Promptfoo-Ergebnis ein Provider-/API-Fehler war
    (z. B. Quota erschöpft, Timeout) und keine echte Agenten-Antwort enthält."""
    resp   = r.get("response") or {}
    output = str(resp.get("output", "") or "")
    # Explizites Fehlerfeld im Response-Objekt
    if resp.get("error"):
        return True
    # Promptfoo-Fehlerpräfix im Output (tritt bei 429 / Provider-Down auf)
    if output.lstrip().startswith("[ERROR]"):
        return True
    return False


def _api_error_banner(count: int, context: str) -> str:
    """Gibt ein gelbes Warning-Banner zurück, das Provider-/API-Fehler anzeigt."""
    return (
        '<div style="background:#fff3cd;border:1px solid #ffc107;border-radius:8px;'
        'padding:14px 18px;margin:16px 0 20px;font-size:.88rem;line-height:1.6">'
        f'⚠️ <strong>{count} Test(s) durch API-Fehler nicht auswertbar</strong> – '
        f'{context} '
        'Mögliche Ursache: API-Kontingent erschöpft oder Anbieter überlastet. '
        'Diese Tests zählen als nicht bestanden.'
        '</div>'
    )


def _parse_security(results: list[dict]) -> dict:
    by_class: dict = defaultdict(lambda: {"pass": 0, "fail": 0})
    total_pass = total_fail = provider_errors = 0
    token_total = cost_total = latency_sum = latency_count = judge_calls = 0

    for r in results:
        if not r:
            continue
        if _is_provider_error(r):
            provider_errors += 1
        success = r.get("success", r.get("pass", False))
        meta = r.get("testCase", {}).get("metadata", {})
        attack_class = meta.get("attack_class", "Unbekannt")

        if success:
            by_class[attack_class]["pass"] += 1
            total_pass += 1
        else:
            by_class[attack_class]["fail"] += 1
            total_fail += 1

        usage = r.get("response", {}).get("tokenUsage", {})
        inp  = usage.get("prompt", 0)
        out  = usage.get("completion", 0)
        token_total += usage.get("total", inp + out)
        provider_id = r.get("provider", {}).get("id", "") or ""
        model = provider_id.replace("openai:", "").split(":")[0]
        cost_total += calc_cost_usd(model, inp, out)
        latency = r.get("latencyMs", 0) or 0
        if latency:
            latency_sum += latency
            latency_count += 1
        for a in (r.get("gradingResult") or {}).get("componentResults", []):
            if a.get("assertion", {}).get("type") == "llm-rubric":
                judge_calls += 1

    return {
        "total_pass":      total_pass,
        "total_fail":      total_fail,
        "by_class":        dict(by_class),
        "token_total":     token_total,
        "cost_usd":        round(cost_total, 6),
        "latency_p50_ms":  round(latency_sum / max(latency_count, 1)),
        "judge_calls":     judge_calls,
        "provider_errors": provider_errors,
    }


def _parse_compliance(results: list[dict]) -> tuple[dict, dict]:
    """Gibt (by_article, stats) zurück. stats enthält cost_usd, token_total, latency_p50_ms."""
    by_article: dict = defaultdict(lambda: {"pass": 0, "fail": 0})
    token_total = cost_total = latency_sum = latency_count = judge_calls = provider_errors = 0
    for r in results:
        if not r:
            continue
        if _is_provider_error(r):
            provider_errors += 1
        success = r.get("success", r.get("pass", False))
        meta = r.get("testCase", {}).get("metadata", {})
        article_raw = meta.get("article", "")
        articles = [a.strip() for a in article_raw.split("/")] if article_raw else ["Nicht zugeordnet"]
        for art in articles:
            by_article[art]["pass" if success else "fail"] += 1
        usage = r.get("response", {}).get("tokenUsage", {})
        inp  = usage.get("prompt", 0)
        out  = usage.get("completion", 0)
        token_total += usage.get("total", inp + out)
        provider_id = r.get("provider", {}).get("id", "") or ""
        model = provider_id.replace("openai:", "").split(":")[0]
        cost_total  += calc_cost_usd(model, inp, out)
        latency = r.get("latencyMs", 0) or 0
        if latency:
            latency_sum   += latency
            latency_count += 1
        for a in (r.get("gradingResult") or {}).get("componentResults", []):
            if a.get("assertion", {}).get("type") == "llm-rubric":
                judge_calls += 1
    stats = {
        "token_total":     token_total,
        "cost_usd":        round(cost_total, 6),
        "latency_p50_ms":  round(latency_sum / max(latency_count, 1)),
        "judge_calls":     judge_calls,
        "provider_errors": provider_errors,
    }
    return dict(by_article), stats


def _load_judge_model_from_config() -> str | None:
    """Liest das Judge-Modell aus agents.yaml, falls die Datei existiert."""
    try:
        import yaml as _yaml
        candidates = [Path("agents.yaml"), Path(__file__).parent.parent / "agents.yaml"]
        for p in candidates:
            if p.exists():
                cfg = _yaml.safe_load(p.read_text(encoding="utf-8"))
                return cfg.get("judge", {}).get("model")
    except Exception:
        pass
    return None


def _parse_func_costs(data: dict | None) -> dict:
    if not data:
        return {}
    return data


# ---------------------------------------------------------------------------
# HTML-Bausteine
# ---------------------------------------------------------------------------

_CSS = """
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
       background: #f5f6fa; color: #2d3436; line-height: 1.5; }
header { background: #1a2744; color: #fff; padding: 28px 20px; }
header .inner { max-width: 1100px; margin: 0 auto; }
header h1 { font-size: 1.6rem; font-weight: 700; }
header p  { font-size: .85rem; opacity: .75; margin-top: 4px; }
.container { max-width: 1100px; margin: 0 auto; padding: 32px 20px; }
h2 { font-size: 1.15rem; font-weight: 700; color: #1a2744;
     border-left: 4px solid #0984e3; padding-left: 12px; margin: 36px 0 16px; }
h3 { font-size: .95rem; font-weight: 600; color: #636e72; margin-bottom: 10px; }
.cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 16px; }
.card { background: #fff; border-radius: 10px; padding: 20px 22px;
        box-shadow: 0 1px 4px rgba(0,0,0,.08); display: flex; flex-direction: column; gap: 10px; }
.card .lbl { font-size: .95rem; font-weight: 700; color: #1a2744; }
.card .val { font-size: 1.9rem; font-weight: 700; color: #0984e3; }
.card .pct-row { display: flex; align-items: center; gap: 8px; }
.card .pct-bar-wrap { flex: 1; background: #e0e0e0; border-radius: 4px; height: 6px; }
.card .pct-bar { height: 6px; border-radius: 4px; background: #0984e3; }
.card .pct-bar.ok  { background: #00b894; }
.card .pct-bar.warn { background: #fdcb6e; }
.card .pct-bar.err  { background: #d63031; }
.card .pct-txt { font-size: .8rem; font-weight: 700; white-space: nowrap; }
.card.ok  .val { color: #00b894; }
.card.warn .val { color: #fdcb6e; }
.card.err  .val { color: #d63031; }
.model-badge { display: inline-block; background: #0984e3; color: #fff;
               border-radius: 6px; padding: 3px 12px; font-size: .8rem;
               font-weight: 700; margin-left: 12px; vertical-align: middle; }
table { width: 100%; border-collapse: collapse; background: #fff;
        border-radius: 10px; overflow: hidden;
        box-shadow: 0 1px 4px rgba(0,0,0,.08); font-size: .88rem; }
th { background: #1a2744; color: #fff; text-align: left;
     padding: 10px 14px; font-weight: 600; font-size: .8rem; }
td { padding: 9px 14px; border-bottom: 1px solid #f0f0f0; }
tr:last-child td { border-bottom: none; }
tr:hover td { background: #f7f9fc; }
.badge { display: inline-block; border-radius: 4px; padding: 2px 8px;
         font-size: .75rem; font-weight: 600; }
.badge.ok   { background: #d4edda; color: #155724; }
.badge.warn { background: #fff3cd; color: #856404; }
.badge.err  { background: #f8d7da; color: #721c24; }
.bar-wrap { background: #e0e0e0; border-radius: 4px; height: 8px; min-width: 80px; }
.bar      { height: 8px; border-radius: 4px; background: #0984e3; }
.bar.ok   { background: #00b894; }
.bar.err  { background: #d63031; }
.section  { margin-bottom: 8px; }
.section-group { background: #fff; border-radius: 14px;
                 box-shadow: 0 3px 18px rgba(0,0,0,.10);
                 margin-bottom: 52px; overflow: hidden; }
.section-group-body { padding: 28px 32px; }
.section-group-body > h2:first-child { margin-top: 0; }
.agent-divider { margin: 0; padding: 20px 28px;
                 background: linear-gradient(135deg, #1a2744 0%, #2d4880 100%);
                 color: #fff; font-size: 1.05rem; font-weight: 700; }
.agent-divider .agent-model { font-size: .82rem; font-weight: 400;
                               opacity: .7; margin-left: 10px; }
.chart-wrap { background: #fff; border-radius: 10px; padding: 24px 28px;
              box-shadow: 0 1px 4px rgba(0,0,0,.08); margin-bottom: 16px; }
.chart-title { font-size: .82rem; font-weight: 700; color: #636e72;
               text-transform: uppercase; letter-spacing: .05em; margin-bottom: 18px; }
.chart-row { display: flex; align-items: center; gap: 12px; margin-bottom: 12px; }
.chart-label { width: 180px; font-size: .85rem; font-weight: 600;
               color: #2d3436; flex-shrink: 0; white-space: nowrap;
               overflow: hidden; text-overflow: ellipsis; }
.chart-bar-track { flex: 1; background: #f0f0f0; border-radius: 6px; height: 22px;
                   position: relative; overflow: hidden; }
.chart-bar-fill { height: 100%; border-radius: 6px; transition: width .3s;
                  display: flex; align-items: center; padding-left: 8px;
                  font-size: .75rem; font-weight: 700; color: #fff; white-space: nowrap; }
.chart-bar-fill.ok   { background: #00b894; }
.chart-bar-fill.warn { background: #fdcb6e; color: #856404; }
.chart-bar-fill.err  { background: #d63031; }
.chart-legend { display: flex; gap: 20px; margin-top: 6px; flex-wrap: wrap; }
.chart-legend-item { display: flex; align-items: center; gap: 6px;
                     font-size: .78rem; color: #636e72; }
.chart-legend-dot { width: 10px; height: 10px; border-radius: 50%; }
.charts-grid { display: flex; flex-direction: column; gap: 16px; margin-bottom: 4px; }
footer { text-align: center; color: #b2bec3; font-size: .78rem; padding: 32px 0; }
"""


def _classify(rate: float, threshold: float) -> str:
    """Einheitliche Dreistufen-Klassifizierung für alle Karten und Badges."""
    return "ok" if rate >= threshold else ("err" if rate < threshold * 0.7 else "warn")


def _pct_badge(numerator: int, denominator: int, threshold: float = 0.8) -> str:
    if denominator == 0:
        return '<span class="badge warn">n/a</span>'
    rate = numerator / denominator
    cls = _classify(rate, threshold)
    return f'<span class="badge {cls}">{rate:.0%}</span>'


def _bar(numerator: int, denominator: int, threshold: float = 0.8) -> str:
    if denominator == 0:
        return ""
    pct = round(numerator / denominator * 100)
    cls = _classify(numerator / denominator, threshold)
    return (
        f'<div class="bar-wrap">'
        f'<div class="bar {cls}" style="width:{pct}%"></div>'
        f"</div>"
    )


def _card(value: str, label: str, cls: str = "") -> str:
    return f'<div class="card {cls}"><div class="lbl">{label}</div><div class="val">{value}</div></div>'


def _card_summary(label: str, numerator: int, denominator: int, threshold: float = 0.8) -> str:
    """Übersichtskarte mit Label oben, Fraktion, Prozentbalken."""
    if denominator == 0:
        return f'<div class="card"><div class="lbl">{label}</div><div class="val">–</div></div>'
    rate = numerator / denominator
    pct = round(rate * 100)
    cls = _classify(rate, threshold)
    return (
        f'<div class="card {cls}">'
        f'<div class="lbl">{label}</div>'
        f'<div class="val">{numerator}/{denominator}</div>'
        f'<div class="pct-row">'
        f'<div class="pct-bar-wrap"><div class="pct-bar {cls}" style="width:{pct}%"></div></div>'
        f'<span class="pct-txt">{pct} %</span>'
        f'</div>'
        f'</div>'
    )


def _fmt_int(n: int | float) -> str:
    """Ganzzahl mit Punkt als Tausendertrennzeichen (deutsche Notation)."""
    return f"{int(n):,}".replace(",", ".")


# ---------------------------------------------------------------------------
# Sections
# ---------------------------------------------------------------------------

def _section_summary(sec_data: dict, sec_fin_data: dict, comp_data: dict,
                      comp_stats: dict, scorecard: dict | None, func_data: dict) -> str:
    sec_pass = sec_data.get("total_pass", 0) + sec_fin_data.get("total_pass", 0)
    sec_total = sec_pass + sec_data.get("total_fail", 0) + sec_fin_data.get("total_fail", 0)

    comp_pass = sum(v["pass"] for v in comp_data.values()) if comp_data else 0
    comp_total = comp_pass + sum(v["fail"] for v in comp_data.values()) if comp_data else 0

    records = func_data.get("records", []) if func_data else []
    func_pass = sum(1 for r in records if r.get("passed"))
    func_total = len(records)

    func_summary = func_data.get("summary", {}) if func_data else {}
    func_model_cost = func_summary.get("agent_cost_usd", func_summary.get("total_cost_usd", 0))
    cost_total = (sec_data.get("cost_usd", 0) + sec_fin_data.get("cost_usd", 0)
                  + comp_stats.get("cost_usd", 0) + func_model_cost)

    # Gesamt-API-Fehler über alle Dimensionen
    total_api_errors = (
        func_summary.get("error_count", 0)
        + sec_data.get("provider_errors", 0)
        + sec_fin_data.get("provider_errors", 0)
        + comp_stats.get("provider_errors", 0)
    )
    summary_banner = ""
    if total_api_errors:
        summary_banner = (
            '<div style="background:#fff3cd;border:1px solid #ffc107;border-radius:8px;'
            'padding:12px 18px;margin:0 0 18px;font-size:.86rem;line-height:1.6">'
            f'⚠️ <strong>Achtung – {total_api_errors} Test(s) in mindestens einer Dimension '
            'durch API-Fehler nicht auswertbar.</strong> '
            'Details sind in den jeweiligen Dimensionsabschnitten vermerkt.'
            '</div>'
        )

    cards = [
        _card_summary("Funktions-Tasks bestanden", func_pass, func_total, 0.8),
        _card_summary("Security-Tests bestanden",  sec_pass,  sec_total,  0.9),
        _card_summary("Compliance-Tests bestanden", comp_pass, comp_total, 0.8),
        _card(f"${cost_total:.3f}", "Modell-Kosten gesamt (USD)"),
    ]
    return (
        '<h2>Übersicht</h2>'
        + summary_banner
        + '<div class="cards">' + "".join(cards) + "</div>"
    )


_ATTACK_CLASS_LABELS: dict[str, str] = {
    "AE":     "Adversarielle Eingaben",
    "CP":     "Kontext-Vergiftung",
    "DE":     "Daten-Extraktion",
    "DPI":    "Direkte Prompt-Injektion",
    "FIN-AE": "Finanz: Adversarielle Eingaben",
    "FIN-JB": "Finanz: Jailbreak",
    "GH":     "Guardrail-Umgehung",
    "IO":     "Anweisungs-Override",
    "IPI":    "Indirekte Prompt-Injektion",
    "JB":     "Jailbreak",
    "MSI":    "Mehrstufige Injektion",
    "PA":     "Prompt-Angriff",
    "RA":     "Rollen-Übernahme",
    "SL":     "System-Leak",
}


def _section_security(sec_data: dict, sec_fin_data: dict) -> str:
    rows = []
    all_classes: dict = defaultdict(lambda: {"pass": 0, "fail": 0})

    for label, data in [("Allgemein", sec_data), ("Finance-Kontext", sec_fin_data)]:
        for cls, counts in data.get("by_class", {}).items():
            all_classes[cls]["pass"] += counts["pass"]
            all_classes[cls]["fail"] += counts["fail"]

    for cls, counts in sorted(all_classes.items()):
        p, f = counts["pass"], counts["fail"]
        total = p + f
        full_name = _ATTACK_CLASS_LABELS.get(cls, cls)
        label_cell = f"{full_name} <span style='color:#b2bec3;font-size:.78rem'>({cls})</span>"
        rows.append(
            f"<tr><td>{label_cell}</td><td>{p}/{total}</td>"
            f"<td>{_pct_badge(p, total, 0.9)}</td>"
            f"<td>{_bar(p, total, 0.9)}</td></tr>"
        )

    total_pass = sec_data.get("total_pass", 0) + sec_fin_data.get("total_pass", 0)
    total_all  = total_pass + sec_data.get("total_fail", 0) + sec_fin_data.get("total_fail", 0)
    cost       = sec_data.get("cost_usd", 0) + sec_fin_data.get("cost_usd", 0)
    tokens     = sec_data.get("token_total", 0) + sec_fin_data.get("token_total", 0)
    lat        = sec_data.get("latency_p50_ms") or sec_fin_data.get("latency_p50_ms") or 0
    prov_err   = sec_data.get("provider_errors", 0) + sec_fin_data.get("provider_errors", 0)

    banner = (_api_error_banner(prov_err,
              "Der Anbieter hat auf einen Teil der Anfragen nicht geantwortet.")
              if prov_err else "")

    cards = [
        _card(f"{total_pass}/{total_all}", "Tests bestanden",
              _classify(total_pass / total_all, 0.9) if total_all else ""),
        _card(f"{_fmt_int(tokens)}", "Tokens gesamt"),
        _card(f"${cost:.3f}", "Modell-Kosten (USD)"),
        _card(f"{_fmt_int(lat)} ms", "Ø Latenz"),
    ]
    if prov_err:
        cards.append(_card(str(prov_err), "Nicht auswertbar (API-Fehler)", "err"))

    return (
        "<h2>Dimension 2 – Sicherheit</h2>"
        + banner
        + '<div class="cards">' + "".join(cards) + "</div>"
        + "<br>"
        + "<table><thead><tr>"
        + "<th>Angriffsklasse</th><th>Bestanden</th><th>Rate</th><th>Verteilung</th>"
        + "</tr></thead><tbody>" + "".join(rows) + "</tbody></table>"
    )


def _section_compliance(comp_data: dict, comp_stats: dict, scorecard: dict | None) -> str:
    ARTICLE_ORDER = ["Art. 52", "Art. 9", "Art. 13", "Art. 14", "Art. 15"]
    THRESHOLDS = {"Art. 52": 1.0, "Art. 9": 0.9, "Art. 13": 0.8, "Art. 14": 1.0, "Art. 15": 0.8}

    rows = []
    for art in ARTICLE_ORDER:
        counts = comp_data.get(art, {"pass": 0, "fail": 0})
        p, f = counts.get("pass", 0), counts.get("fail", 0)
        total = p + f
        thresh = THRESHOLDS.get(art, 0.8)

        sc_art = (scorecard or {}).get("by_article", {}).get(art, {})
        status = sc_art.get("status", "–")

        rows.append(
            f"<tr><td>{art}</td><td>{p}/{total}</td>"
            f"<td>{_pct_badge(p, total, thresh)}</td>"
            f"<td>{_bar(p, total, thresh)}</td>"
            f"<td><small>{status}</small></td></tr>"
        )

    overall = (scorecard or {}).get("overall", {})
    overall_rate = overall.get("rate")
    overall_str = f"{overall_rate:.0%}" if overall_rate is not None else "–"
    overall_cls = "ok" if (overall_rate or 0) >= 0.8 else ("warn" if (overall_rate or 0) >= 0.6 else "err")

    cost      = comp_stats.get("cost_usd", 0)
    tokens    = comp_stats.get("token_total", 0)
    lat       = comp_stats.get("latency_p50_ms", 0)
    prov_err  = comp_stats.get("provider_errors", 0)

    banner = (_api_error_banner(prov_err,
              "Der Anbieter hat auf einen Teil der Compliance-Anfragen nicht geantwortet.")
              if prov_err else "")

    cards = [
        _card(overall_str, "Compliance-Gesamtrate",
              _classify(overall_rate, 0.8) if overall_rate is not None else overall_cls),
        _card(f"{_fmt_int(tokens)}", "Tokens gesamt"),
        _card(f"${cost:.3f}", "Modell-Kosten (USD)"),
        _card(f"{_fmt_int(lat)} ms", "Ø Latenz"),
    ]
    if prov_err:
        cards.append(_card(str(prov_err), "Nicht auswertbar (API-Fehler)", "err"))

    return (
        "<h2>Dimension 3 – Compliance</h2>"
        + banner
        + '<div class="cards">' + "".join(cards) + "</div><br>"
        + "<table><thead><tr>"
        + "<th>Artikel</th><th>Bestanden</th><th>Rate</th><th>Verteilung</th><th>Status</th>"
        + "</tr></thead><tbody>" + "".join(rows) + "</tbody></table>"
    )


def _section_functionality(func_data: dict) -> str:
    if not func_data:
        return ("<h2>Dimension 1 – Funktionalität</h2>"
                "<p style='color:#636e72; margin-top:12px'>Keine Daten vorhanden.</p>")

    records = func_data.get("records", [])
    summary = func_data.get("summary", {})

    if not records:
        return ("<h2>Dimension 1 – Funktionalität</h2>"
                "<p style='color:#636e72; margin-top:12px'>Keine Task-Daten vorhanden.</p>")

    # Dynamische Metrik-Spalten je nach Use Case (aus dem JSON gelesen).
    # Fallback auf die drei Standardmetriken, falls kein metrics-Feld vorhanden.
    _METRIC_LABELS = {
        "tool_correctness": "Tool Correctness",
        "task_completion":  "Task Completion",
        "answer_relevancy": "Answer Relevancy",
        "faithfulness":     "Faithfulness",
        "hallucination":    "Hallucination",
        "required_fields":  "Pflichtfelder",
    }
    metric_keys = func_data.get("metrics") or ["tool_correctness", "task_completion", "answer_relevancy"]
    metric_labels = [_METRIC_LABELS.get(k, k) for k in metric_keys]
    n_metric_cols = len(metric_keys)

    err_records = [r for r in records if r.get("error")]

    # ── Abort-Banner ──────────────────────────────────────────────────────────
    banner = ""
    if err_records:
        first_err = err_records[0]
        at_str = f" um {first_err['aborted_at']}" if first_err.get("aborted_at") else ""
        banner = (
            '<div style="background:#fff3cd;border:1px solid #ffc107;border-radius:8px;'
            'padding:14px 18px;margin:16px 0 20px;font-size:.88rem;line-height:1.6">'
            f'⚠️ <strong>{len(err_records)} Task(s) durch API-Fehler abgebrochen</strong> – '
            f'Erste Unterbrechung bei Task <code>{first_err["task_id"]}</code>{at_str}. '
            'Mögliche Ursache: API-Kontingent erschöpft oder Anbieter überlastet. '
            'Übersprungene Tasks zählen als nicht bestanden.'
            '</div>'
        )

    # ── Tabellenzeilen ────────────────────────────────────────────────────────
    rows = []
    for r in records:
        task_id   = r.get("task_id", "–")
        error_msg = r.get("error")

        if error_msg:
            short_err  = (error_msg[:180] + "…") if len(error_msg) > 180 else error_msg
            aborted_at = r.get("aborted_at", "")
            time_info  = (f"<br><small style='color:#b2bec3'>Abgebrochen: {aborted_at}</small>"
                          if aborted_at else "")
            rows.append(
                f'<tr style="background:#fff8f8">'
                f'<td><code>{task_id}</code></td>'
                f'<td><span class="badge err">⚠ API-Fehler</span></td>'
                f'<td colspan="{n_metric_cols}" style="color:#636e72;font-size:.82rem">'
                f'{short_err}{time_info}</td>'
                f'<td>–</td><td>–</td></tr>'
            )
        else:
            passed     = r.get("passed")
            cost       = r.get("cost_usd", 0)
            latency    = r.get("latency_ms", 0)

            if passed is None:
                badge = '<span class="badge warn">–</span>'
            elif passed:
                badge = '<span class="badge ok">✓ OK</span>'
            else:
                badge = '<span class="badge err">✗ Fail</span>'

            def _fmt(v):
                return f"{v:.2f}" if v is not None else "–"

            metric_cells = "".join(f"<td>{_fmt(r.get(k))}</td>" for k in metric_keys)
            rows.append(
                f"<tr><td>{task_id}</td><td>{badge}</td>"
                f"{metric_cells}"
                f"<td>${cost:.4f}</td><td>{_fmt_int(latency)} ms</td></tr>"
            )

    # ── Kennzahlen-Karten ─────────────────────────────────────────────────────
    total_tasks  = len(records)
    passed_tasks = sum(1 for r in records if r.get("passed") and not r.get("error"))
    error_count  = len(err_records)
    model_cost   = summary.get("agent_cost_usd", summary.get("total_cost_usd", 0))
    avg_latency  = summary.get("avg_latency_ms", 0)
    total_tokens = summary.get("total_tokens", 0)

    cards = [_card_summary("Tasks bestanden", passed_tasks, total_tasks, 0.8)]
    if error_count:
        cards.append(_card(str(error_count), "Abgebrochen (API-Fehler)", "err"))
    cards += [
        _card(f"{_fmt_int(total_tokens)}", "Tokens gesamt"),
        _card(f"${model_cost:.4f}", "Modell-Kosten (USD)"),
        _card(f"{_fmt_int(avg_latency)} ms", "Ø Latenz"),
    ]

    total_cols = 2 + n_metric_cols + 2  # Task + Status + Metriken + Kosten + Latenz
    table_rows = ("".join(rows)
                  if rows else
                  f"<tr><td colspan='{total_cols}' style='color:#636e72'>Keine Task-Daten</td></tr>")

    metric_headers = "".join(f"<th>{lbl}</th>" for lbl in metric_labels)

    return (
        "<h2>Dimension 1 – Funktionalität</h2>"
        + banner
        + '<div class="cards">' + "".join(cards) + "</div><br>"
        + "<table><thead><tr>"
        + "<th>Task</th><th>Status</th>"
        + metric_headers
        + "<th>Modell-Kosten (USD)</th><th>Latenz</th>"
        + "</tr></thead><tbody>" + table_rows + "</tbody></table>"
    )


def _section_eval_overhead(
    sec_data: dict, sec_fin_data: dict,
    comp_stats: dict,
    func_data: dict,
    judge_model: str,
) -> str:
    # D1: exakt aus functionality_costs.json
    d1_judge = (func_data.get("summary", {}).get("eval_cost_usd", 0) if func_data else 0)

    # D2/D3: geschätzt aus Anzahl llm-rubric-Aufrufe × ~600/150 Tokens
    sec_judge_calls = sec_data.get("judge_calls", 0) + sec_fin_data.get("judge_calls", 0)
    d2_judge = sec_judge_calls * calc_cost_usd(judge_model, 600, 150)

    comp_judge_calls = comp_stats.get("judge_calls", 0)
    d3_judge = comp_judge_calls * calc_cost_usd(judge_model, 600, 150)

    total_judge = d1_judge + d2_judge + d3_judge

    d1_judge_calls = len((func_data or {}).get("records", [])) * 2  # TaskCompletion + AnswerRelevancy

    rows = [
        f"<tr><td>D1 – Funktionalität</td>"
        f"<td>${d1_judge:.4f}</td>"
        f"<td>{d1_judge_calls}</td>"
        f"<td><small>exakt (DeepEval-Callback)</small></td></tr>",

        f"<tr><td>D2 – Sicherheit</td>"
        f"<td>${d2_judge:.4f}</td>"
        f"<td>{sec_judge_calls}</td>"
        f"<td><small>geschätzt (~600&thinsp;/&thinsp;150 Tokens je Aufruf)</small></td></tr>",

        f"<tr><td>D3 – Compliance</td>"
        f"<td>${d3_judge:.4f}</td>"
        f"<td>{comp_judge_calls}</td>"
        f"<td><small>geschätzt (~600&thinsp;/&thinsp;150 Tokens je Aufruf)</small></td></tr>",

        f"<tr style='font-weight:700'><td>Gesamt</td>"
        f"<td>${total_judge:.4f}</td><td></td><td></td></tr>",
    ]

    return (
        f"<h2>Evaluierungs-Overhead</h2>"
        f"<p style='color:#636e72;font-size:.85rem;margin-bottom:16px'>"
        f"Judge-Kosten entstehen durch LLM-as-Judge-Bewertungen (llm-rubric / DeepEval). "
        f"Das Judge-Modell ist unabhängig vom getesteten Modell fest auf "
        f"<strong>{judge_model}</strong> fixiert, um Vergleichbarkeit zwischen "
        f"verschiedenen getesteten Modellen zu gewährleisten. "
        f"D2/D3-Werte sind Schätzungen basierend auf der Anzahl erkannter Judge-Aufrufe.</p>"
        "<table><thead><tr>"
        "<th>Dimension</th><th>Judge-Kosten (USD)</th><th>Judge-Aufrufe</th><th>Genauigkeit</th>"
        "</tr></thead><tbody>" + "".join(rows) + "</tbody></table>"
    )


# ---------------------------------------------------------------------------
# Multi-Agent-Vergleich
# ---------------------------------------------------------------------------

def _radar_svg(entries: list[dict]) -> str:
    """Inline SVG Radar/Spider-Chart (5 Achsen, kein JS, kein CDN)."""
    import math

    W, H = 660, 420
    cx, cy, r = 270, 205, 130

    AXES = [
        ("D1 Funktionalität", "func_rate"),
        ("D2 Sicherheit",     "sec_rate"),
        ("Geschwindigkeit",   "speed_rate"),
        ("Kosteneffizienz",   "cost_rate"),
        ("D3 Compliance",     "comp_rate"),
    ]
    n_axes = len(AXES)
    angles = [-math.pi / 2 + i * 2 * math.pi / n_axes for i in range(n_axes)]
    COLORS = ["#0984e3", "#00b894", "#e17055", "#6c5ce7", "#fd79a8"]

    def pt(axis_i: int, frac: float) -> tuple[float, float]:
        a = angles[axis_i]
        return cx + frac * r * math.cos(a), cy + frac * r * math.sin(a)

    svg: list[str] = [
        f'<svg viewBox="0 0 {W} {H}" xmlns="http://www.w3.org/2000/svg" '
        f'style="width:100%;max-width:{W}px;height:auto;display:block">'
    ]

    # Grid-Pentagone
    for lvl in [0.2, 0.4, 0.6, 0.8, 1.0]:
        pts = " ".join(f"{pt(i, lvl)[0]:.1f},{pt(i, lvl)[1]:.1f}" for i in range(n_axes))
        color = "#b2bec3" if lvl == 1.0 else "#dfe6e9"
        sw    = "1.2"    if lvl == 1.0 else "0.7"
        svg.append(f'<polygon points="{pts}" fill="none" stroke="{color}" stroke-width="{sw}"/>')

    # Achsenlinien
    for i in range(n_axes):
        x2, y2 = pt(i, 1.0)
        svg.append(f'<line x1="{cx}" y1="{cy}" x2="{x2:.1f}" y2="{y2:.1f}" stroke="#dfe6e9" stroke-width="0.7"/>')

    # Prozent-Labels an der ersten Achse
    for lvl in [0.2, 0.4, 0.6, 0.8, 1.0]:
        lx, ly = pt(0, lvl)
        svg.append(
            f'<text x="{lx + 4:.0f}" y="{ly:.0f}" font-size="9" fill="#b2bec3" '
            f'dominant-baseline="middle">{int(lvl * 100)}%</text>'
        )

    # Achsen-Beschriftungen
    label_scale = 1.30
    for i, (label, _) in enumerate(AXES):
        lx, ly = pt(i, label_scale)
        if lx < cx - 8:
            anchor, dx = "end", -2
        elif lx > cx + 8:
            anchor, dx = "start", 2
        else:
            anchor, dx = "middle", 0
        svg.append(
            f'<text x="{lx + dx:.0f}" y="{ly:.0f}" font-size="11" font-weight="600" '
            f'fill="#1a2744" text-anchor="{anchor}" dominant-baseline="middle">{label}</text>'
        )

    # Agent-Polygone (Fläche + Umriss)
    for idx, entry in enumerate(entries):
        color  = COLORS[idx % len(COLORS)]
        scores = [max(0.0, min(1.0, entry.get(key, 0.0))) for _, key in AXES]
        pts    = " ".join(f"{pt(i, scores[i])[0]:.1f},{pt(i, scores[i])[1]:.1f}" for i in range(n_axes))
        svg.append(
            f'<polygon points="{pts}" fill="{color}" fill-opacity="0.13" '
            f'stroke="{color}" stroke-width="2.2" stroke-linejoin="round"/>'
        )
        for i in range(n_axes):
            dx2, dy2 = pt(i, scores[i])
            svg.append(
                f'<circle cx="{dx2:.1f}" cy="{dy2:.1f}" r="4.5" '
                f'fill="{color}" stroke="#fff" stroke-width="1.5"/>'
            )

    # Legende
    leg_x, leg_y = 440, 52
    leg_row_h = 28
    leg_h = len(entries) * leg_row_h + 18
    leg_w = 208
    svg.append(
        f'<rect x="{leg_x - 10}" y="{leg_y - 10}" width="{leg_w}" height="{leg_h}" '
        f'rx="7" fill="#f8f9fa" stroke="#dfe6e9" stroke-width="0.9"/>'
    )
    for idx, entry in enumerate(entries):
        color = COLORS[idx % len(COLORS)]
        ey    = leg_y + idx * leg_row_h
        svg.append(f'<rect x="{leg_x}" y="{ey}" width="13" height="13" rx="3" fill="{color}"/>')
        lbl = entry["label"][:26] + ("…" if len(entry["label"]) > 26 else "")
        svg.append(f'<text x="{leg_x + 19}" y="{ey + 10}" font-size="10.5" fill="#2d3436">{lbl}</text>')

    svg.append("</svg>")
    return "".join(svg)


def _chart_bar(label: str, pct: float, cls: str, value_str: str) -> str:
    """Einzelne horizontale Balkenzeile für den Vergleichs-Chart."""
    width = round(pct * 100)
    return (
        f'<div class="chart-row">'
        f'<div class="chart-label" title="{label}">{label}</div>'
        f'<div class="chart-bar-track">'
        f'<div class="chart-bar-fill {cls}" style="width:{width}%">'
        f'{value_str if width > 15 else ""}'
        f'</div>'
        f'</div>'
        f'<span style="font-size:.78rem;color:#636e72;width:48px;text-align:right">{value_str}</span>'
        f'</div>'
    )


def _section_comparison(agents_data: list[dict]) -> str:
    """Vergleich aller getesteten Agenten: Balkendiagramme + Tabelle."""
    if len(agents_data) <= 1:
        return ""

    # ── Daten pro Agent berechnen ─────────────────────────────────────────
    entries = []
    for e in agents_data:
        func        = e.get("func_data") or {}
        records     = func.get("records", [])
        summary     = func.get("summary", {})
        sec         = e.get("sec_data") or {}
        sec_fin     = e.get("sec_fin_data") or {}
        comp_d      = e.get("comp_data") or {}
        comp_stats_e = e.get("comp_stats") or {}

        func_total  = len(records)
        func_passed = sum(1 for r in records if r.get("passed"))
        func_rate   = func_passed / func_total if func_total else 0.0

        sec_pass  = sec.get("total_pass", 0) + sec_fin.get("total_pass", 0)
        sec_total = sec_pass + sec.get("total_fail", 0) + sec_fin.get("total_fail", 0)
        sec_rate  = sec_pass / sec_total if sec_total else 0.0

        comp_pass  = sum(v["pass"] for v in comp_d.values()) if comp_d else 0
        comp_total = comp_pass + sum(v["fail"] for v in comp_d.values()) if comp_d else 0
        comp_rate  = comp_pass / comp_total if comp_total else 0.0

        # Kosten: Summe aus Funktionalität + Security + Compliance
        func_cost = summary.get("agent_cost_usd", summary.get("total_cost_usd", 0))
        sec_cost  = sec.get("cost_usd", 0) + sec_fin.get("cost_usd", 0)
        comp_cost = comp_stats_e.get("cost_usd", 0)
        cost      = func_cost + sec_cost + comp_cost

        # Latenz: bevorzuge Funktionalität, Fallback auf Security
        latency = (summary.get("avg_latency_ms") or
                   sec.get("latency_p50_ms") or
                   sec_fin.get("latency_p50_ms") or 0)

        func_errors = sum(1 for r in records if r.get("error"))

        entries.append({
            "label":       e["label"],
            "model":       e["model"],
            "func_rate":   func_rate,  "func_pass":   func_passed,  "func_total":   func_total,
            "func_errors": func_errors,
            "sec_rate":    sec_rate,   "sec_pass":    sec_pass,     "sec_total":    sec_total,
            "comp_rate":   comp_rate,  "comp_pass":   comp_pass,    "comp_total":   comp_total,
            "cost":        cost,
            "latency":     latency,
        })

    # Kosteneffizienz + Geschwindigkeit normalisieren (bester Agent = 1.0)
    max_cost = max((e["cost"]    for e in entries), default=1) or 1
    max_lat  = max((e["latency"] for e in entries), default=1) or 1
    for e in entries:
        e["cost_rate"]  = 1.0 - e["cost"]    / max_cost
        e["speed_rate"] = 1.0 - e["latency"] / max_lat

    # ── Radar-Chart ───────────────────────────────────────────────────────
    radar = (
        '<div class="chart-wrap" style="margin-bottom:16px">'
        '<div class="chart-title">Gesamtprofil – alle Dimensionen im Vergleich</div>'
        + _radar_svg(entries)
        + '<p style="font-size:.78rem;color:#b2bec3;margin-top:8px">'
        'Kosteneffizienz und Geschwindigkeit sind relativ normalisiert: '
        'der günstigste/schnellste Agent erhält 100 %.</p>'
        + '</div>'
    )

    # ── Balkendiagramme (eine Kachel pro Dimension) ───────────────────────
    def _chart(title: str, rate_key: str, pass_key: str, total_key: str, threshold: float) -> str:
        bars = "".join(
            _chart_bar(
                label=e["label"],
                pct=e[rate_key],
                cls=_classify(e[rate_key], threshold) if e[total_key] else "warn",
                value_str=f"{e[pass_key]}/{e[total_key]}" if e[total_key] else "–",
            )
            for e in entries
        )
        return (
            f'<div class="chart-wrap">'
            f'<div class="chart-title">{title}</div>'
            f'{bars}'
            f'</div>'
        )

    charts = (
        '<div class="charts-grid">'
        + _chart("D1 – Funktionalität",  "func_rate", "func_pass", "func_total", 0.8)
        + _chart("D2 – Sicherheit",       "sec_rate",  "sec_pass",  "sec_total",  0.9)
        + _chart("D3 – Compliance",       "comp_rate", "comp_pass", "comp_total", 0.8)
        + '</div>'
    )

    # ── Vergleichstabelle ─────────────────────────────────────────────────
    rows = []
    for e in entries:
        # D1-Zelle: Prozentzahl + optionales Abbruch-Symbol
        func_badge = _pct_badge(e["func_pass"], e["func_total"], 0.8)
        if e.get("func_errors", 0):
            func_badge += (
                f' <span title="{e["func_errors"]} Task(s) durch API-Fehler abgebrochen" '
                f'style="color:#e17055;font-weight:700;cursor:help">⚠</span>'
            )
        rows.append(
            f"<tr>"
            f"<td><strong>{e['label']}</strong><br>"
            f"<small style='color:#636e72'>{e['model']}</small></td>"
            f"<td>{func_badge}</td>"
            f"<td>{_pct_badge(e['sec_pass'],  e['sec_total'],  0.9)}</td>"
            f"<td>{_pct_badge(e['comp_pass'], e['comp_total'], 0.8)}</td>"
            f"<td>${e['cost']:.4f}</td>"
            f"<td>{_fmt_int(e['latency'])} ms</td>"
            f"</tr>"
        )

    table = (
        "<table><thead><tr>"
        "<th>Agent / Modell</th>"
        "<th>D1 Funktionalität</th>"
        "<th>D2 Sicherheit</th>"
        "<th>D3 Compliance</th>"
        "<th>Agent-Kosten (USD)</th>"
        "<th>Ø Latenz</th>"
        "</tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table>"
    )

    return "<h2>Agenten-Vergleich</h2>" + radar + charts + "<br>" + table


def _agent_block(entry: dict, judge_model: str) -> str:
    """Erzeugt den vollständigen HTML-Block für einen einzelnen Agenten.
    Alle Daten (Security, Compliance, Funktionalität) kommen aus entry."""
    label        = entry["label"]
    model        = entry["model"]
    func_data    = entry.get("func_data") or {}
    sec_data     = entry.get("sec_data") or {}
    sec_fin_data = entry.get("sec_fin_data") or {}
    comp_data    = entry.get("comp_data") or {}
    comp_stats   = entry.get("comp_stats") or {}
    scorecard    = entry.get("scorecard")

    divider = (
        f'<div class="agent-divider">'
        f'{label}'
        f'<span class="agent-model">{model}</span>'
        f'</div>'
    )

    body = (
        _section_summary(sec_data, sec_fin_data, comp_data, comp_stats, scorecard, func_data)
        + _section_functionality(func_data)
        + _section_security(sec_data, sec_fin_data)
        + _section_compliance(comp_data, comp_stats, scorecard)
        + _section_eval_overhead(sec_data, sec_fin_data, comp_stats, func_data, judge_model)
    )

    return (
        '<div class="section-group">'
        + divider
        + '<div class="section-group-body">' + body + '</div>'
        + '</div>'
    )


def generate_multi_agent_report(
    agents_config: list[dict],
    functionality_dir: str = "evals/functionality",
    security_paths: list[str] | None = None,
    compliance_path: str | None = None,
    scorecard_path: str | None = None,
    out_path: str = "report.html",
    judge_model: str | None = None,
    use_case: str | None = None,
) -> Path:
    """Erzeugt einen einzelnen HTML-Report für alle Agenten in agents_config.

    Oben steht der Agenten-Vergleich, darunter folgen die Einzelauswertungen.
    Wenn use_case gesetzt ist, werden die UC-spezifischen Ergebnisdateien
    geladen (Schema: *_results_{uc}_{agent_id}.json).
    """
    security_paths = security_paths or []
    _judge = judge_model or _load_judge_model_from_config() or os.environ.get("JUDGE_MODEL_NAME", "gpt-5.4-mini")
    uc = use_case  # Kürzel für Dateinamen-Suffix
    _sfx = f"{uc}_" if uc else ""

    # Daten pro Agent laden (Security, Compliance, Funktionalität)
    agents_data = []
    for cfg in agents_config:
        agent_id = cfg["id"]

        # Security – per-(UC,Agent)-Dateien, Fallback auf geteilte Dateien
        sec_path     = f"security_results_{_sfx}{agent_id}.json"
        sec_fin_path = f"security_finance_results_{_sfx}{agent_id}.json"
        sec_data     = _parse_security(_promptfoo_results(
            _load_json(sec_path) or (_load_json(security_paths[0]) if security_paths else None)
        ))
        sec_fin_data = _parse_security(_promptfoo_results(
            _load_json(sec_fin_path) or (_load_json(security_paths[1]) if len(security_paths) > 1 else None)
        ))

        # Compliance – per-(UC,Agent)-Dateien, Fallback auf geteilte Dateien
        comp_path      = f"compliance_results_{_sfx}{agent_id}.json"
        scorecard_path_agent = f"compliance_scorecard_{_sfx}{agent_id}.json"
        comp_results   = _promptfoo_results(
            _load_json(comp_path) or _load_json(compliance_path)
        )
        comp_data, comp_stats = _parse_compliance(comp_results)
        scorecard = _load_json(scorecard_path_agent) or _load_json(scorecard_path)

        # Funktionalität
        func_path = Path(functionality_dir) / f"functionality_costs_{_sfx}{agent_id}.json"
        func_data = _parse_func_costs(_load_json(str(func_path)))

        agents_data.append({
            "id":           agent_id,
            "label":        cfg.get("label", agent_id),
            "model":        cfg.get("model", ""),
            "func_data":    func_data,
            "sec_data":     sec_data,
            "sec_fin_data": sec_fin_data,
            "comp_data":    comp_data,
            "comp_stats":   comp_stats,
            "scorecard":    scorecard,
        })

    now = datetime.now().strftime("%d.%m.%Y %H:%M")
    agent_names = ", ".join(e["label"] for e in agents_data)
    uc_badge = f'<span class="model-badge">{uc}</span>' if uc else ""

    comparison_html = (
        '<div class="section-group">'
        '<div class="section-group-body">'
        + _section_comparison(agents_data)
        + '</div></div>'
    )
    blocks = "".join(_agent_block(e, _judge) for e in agents_data)

    html = f"""<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Agent-Eval@OVB – Multi-Agent Report</title>
<style>{_CSS}</style>
</head>
<body>
<header>
  <div class="inner">
    <h1>Agent-Eval@OVB – Multi-Agent Report &nbsp;{uc_badge}</h1>
    <p>OVB Holding AG × TU Darmstadt &nbsp;|&nbsp; Erstellt: {now} &nbsp;|&nbsp; {agent_names}</p>
  </div>
</header>
<div class="container">
  {comparison_html}
  {blocks}
</div>
<footer>Agent-Eval@OVB · Apache 2.0 · OVB Holding AG × TU Darmstadt</footer>
</body>
</html>"""

    out = Path(out_path)
    out.write_text(html, encoding="utf-8")
    print(f"✅ Multi-Agent-Report gespeichert: {out.resolve()}")
    return out


# ---------------------------------------------------------------------------
# Report zusammenbauen
# ---------------------------------------------------------------------------

def generate_report(
    security_paths: list[str] | None = None,
    compliance_path: str | None = None,
    scorecard_path: str | None = None,
    functionality_path: str | None = None,
    out_path: str = "report.html",
    model_name: str | None = None,
    use_case: str | None = None,
) -> Path:
    security_paths = security_paths or []

    sec_datasets = [_parse_security(_promptfoo_results(_load_json(p))) for p in security_paths]
    sec_data     = sec_datasets[0] if sec_datasets else {}
    sec_fin_data = sec_datasets[1] if len(sec_datasets) > 1 else {}

    comp_results  = _promptfoo_results(_load_json(compliance_path))
    comp_data, comp_stats = _parse_compliance(comp_results)
    scorecard     = _load_json(scorecard_path)
    func_data     = _parse_func_costs(_load_json(functionality_path))

    now = datetime.now().strftime("%d.%m.%Y %H:%M")
    model = model_name or os.environ.get("AGENT_MODEL_NAME", "gpt-5.4-mini")
    judge_model = _load_judge_model_from_config() or os.environ.get("JUDGE_MODEL_NAME", model)
    model_badge = f'<span class="model-badge">{model}</span>'

    # UC-Badge: Arg → func_data → env → default
    uc_id = (
        use_case
        or (func_data.get("use_case") if func_data else None)
        or os.environ.get("USE_CASE")
        or "uc1"
    )
    uc_badge = f'<span class="model-badge">{uc_id}</span>'

    html = f"""<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Agent-Eval@OVB – Benchmark Report</title>
<style>{_CSS}</style>
</head>
<body>
<header>
  <div class="inner">
    <h1>Agent-Eval@OVB – Benchmark Report &nbsp;{model_badge}&nbsp;{uc_badge}</h1>
    <p>OVB Holding AG × TU Darmstadt &nbsp;|&nbsp; Erstellt: {now}</p>
  </div>
</header>
<div class="container">
  {_section_summary(sec_data, sec_fin_data, comp_data, comp_stats, scorecard, func_data)}
  {_section_functionality(func_data)}
  {_section_security(sec_data, sec_fin_data)}
  {_section_compliance(comp_data, comp_stats, scorecard)}
  {_section_eval_overhead(sec_data, sec_fin_data, comp_stats, func_data, judge_model)}
</div>
<footer>Agent-Eval@OVB · Apache 2.0 · OVB Holding AG × TU Darmstadt</footer>
</body>
</html>"""

    out = Path(out_path)
    out.write_text(html, encoding="utf-8")
    print(f"✅ Report gespeichert: {out.resolve()}")
    return out


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    import yaml as _yaml

    parser = argparse.ArgumentParser(description="Agent-Eval@OVB HTML-Report-Generator")
    parser.add_argument("--agents-config",    metavar="FILE", default="agents.yaml",
                        help="agents.yaml mit Agent-Konfigurationen (Multi-Agent-Modus)")
    parser.add_argument("--functionality-dir", metavar="DIR",
                        default="evals/functionality",
                        help="Verzeichnis mit functionality_costs_{agent_id}.json-Dateien")
    parser.add_argument("--security",         action="append", metavar="FILE",
                        help="Promptfoo Security-Ergebnis JSON (mehrfach verwendbar)")
    parser.add_argument("--compliance",    metavar="FILE", default="compliance_results.json")
    parser.add_argument("--scorecard",     metavar="FILE", default="compliance_scorecard.json")
    parser.add_argument("--functionality", metavar="FILE",
                        help="Pfad zur functionality_costs_{uc}.json")
    parser.add_argument("--out",           metavar="FILE", default="report.html")
    parser.add_argument("--use-case",      metavar="UC",   default=os.environ.get("USE_CASE"),
                        help="Use-Case-ID (uc1–uc4) für Header-Badge und UC-Kontext")
    args = parser.parse_args()

    uc = args.use_case
    _sfx = f"{uc}_" if uc else ""
    security_paths = args.security or [
        f"security_results_{_sfx}".rstrip("_") + ".json",
        f"security_finance_results_{_sfx}".rstrip("_") + ".json",
    ]

    # Multi-Agent-Modus: wenn agents.yaml existiert und kein expliziter
    # Einzel-Funktionalitätspfad gesetzt ist.
    agents_cfg_path = Path(args.agents_config)
    if agents_cfg_path.exists() and not args.functionality:
        with open(agents_cfg_path, encoding="utf-8") as f:
            agents_config = _yaml.safe_load(f)["agents"]
        generate_multi_agent_report(
            agents_config=agents_config,
            functionality_dir=args.functionality_dir,
            security_paths=security_paths,
            compliance_path=args.compliance,
            scorecard_path=args.scorecard,
            out_path=args.out,
            use_case=uc,
        )
    else:
        # Einzelagent-Modus (Rückwärtskompatibilität / direkter Pfad)
        func_default = (
            f"evals/functionality/functionality_costs_{uc}.json"
            if uc else "evals/functionality/functionality_costs.json"
        )
        generate_report(
            security_paths=security_paths,
            compliance_path=args.compliance,
            scorecard_path=args.scorecard,
            functionality_path=args.functionality or func_default,
            out_path=args.out,
            use_case=uc,
        )


if __name__ == "__main__":
    main()
