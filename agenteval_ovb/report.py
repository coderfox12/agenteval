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
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

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


def _parse_security(results: list[dict]) -> dict:
    by_class: dict = defaultdict(lambda: {"pass": 0, "fail": 0})
    total_pass = total_fail = 0
    token_total = cost_total = latency_sum = latency_count = 0

    for r in results:
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
        token_total += usage.get("total", 0)
        cost_total += r.get("response", {}).get("cost", 0) or 0
        lat = r.get("response", {}).get("cached", False)
        latency = r.get("latencyMs", 0) or 0
        if latency:
            latency_sum += latency
            latency_count += 1

    return {
        "total_pass": total_pass,
        "total_fail": total_fail,
        "by_class": dict(by_class),
        "token_total": token_total,
        "cost_usd": round(cost_total, 4),
        "latency_p50_ms": round(latency_sum / max(latency_count, 1)),
    }


def _parse_compliance(results: list[dict]) -> dict:
    by_article: dict = defaultdict(lambda: {"pass": 0, "fail": 0})
    for r in results:
        success = r.get("success", r.get("pass", False))
        meta = r.get("testCase", {}).get("metadata", {})
        article_raw = meta.get("article", "")
        articles = [a.strip() for a in article_raw.split("/")] if article_raw else ["Nicht zugeordnet"]
        for art in articles:
            by_article[art]["pass" if success else "fail"] += 1
    return dict(by_article)


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
header { background: #1a2744; color: #fff; padding: 28px 40px; }
header h1 { font-size: 1.6rem; font-weight: 700; }
header p  { font-size: .85rem; opacity: .75; margin-top: 4px; }
.container { max-width: 1100px; margin: 0 auto; padding: 32px 20px; }
h2 { font-size: 1.15rem; font-weight: 700; color: #1a2744;
     border-left: 4px solid #0984e3; padding-left: 12px; margin: 36px 0 16px; }
h3 { font-size: .95rem; font-weight: 600; color: #636e72; margin-bottom: 10px; }
.cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 16px; }
.card { background: #fff; border-radius: 10px; padding: 20px 22px;
        box-shadow: 0 1px 4px rgba(0,0,0,.08); }
.card .val { font-size: 2rem; font-weight: 700; color: #0984e3; }
.card .lbl { font-size: .78rem; color: #636e72; margin-top: 4px; }
.card.ok  .val { color: #00b894; }
.card.warn .val { color: #fdcb6e; }
.card.err  .val { color: #d63031; }
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
footer { text-align: center; color: #b2bec3; font-size: .78rem; padding: 32px 0; }
"""


def _pct_badge(numerator: int, denominator: int, threshold: float = 0.8) -> str:
    if denominator == 0:
        return '<span class="badge warn">n/a</span>'
    rate = numerator / denominator
    cls = "ok" if rate >= threshold else ("warn" if rate >= threshold * 0.7 else "err")
    return f'<span class="badge {cls}">{rate:.0%}</span>'


def _bar(numerator: int, denominator: int, threshold: float = 0.8) -> str:
    if denominator == 0:
        return ""
    pct = round(numerator / denominator * 100)
    rate = numerator / denominator
    cls = "ok" if rate >= threshold else ("err" if rate < threshold * 0.7 else "")
    return (
        f'<div class="bar-wrap">'
        f'<div class="bar {cls}" style="width:{pct}%"></div>'
        f"</div>"
    )


def _card(value: str, label: str, cls: str = "") -> str:
    return f'<div class="card {cls}"><div class="val">{value}</div><div class="lbl">{label}</div></div>'


# ---------------------------------------------------------------------------
# Sections
# ---------------------------------------------------------------------------

def _section_summary(sec_data: dict, sec_fin_data: dict, comp_data: dict,
                      scorecard: dict | None, func_data: dict) -> str:
    sec_pass = sec_data.get("total_pass", 0) + sec_fin_data.get("total_pass", 0)
    sec_total = sec_pass + sec_data.get("total_fail", 0) + sec_fin_data.get("total_fail", 0)

    comp_pass = sum(v["pass"] for v in comp_data.values()) if comp_data else 0
    comp_total = comp_pass + sum(v["fail"] for v in comp_data.values()) if comp_data else 0

    overall_rate = scorecard.get("overall", {}).get("rate") if scorecard else None
    overall_str = f"{overall_rate:.0%}" if overall_rate is not None else "–"
    overall_cls = "ok" if (overall_rate or 0) >= 0.8 else ("warn" if (overall_rate or 0) >= 0.6 else "err")

    tasks = func_data.get("tasks", []) if func_data else []
    func_pass = sum(1 for t in tasks if t.get("passed")) if tasks else 0
    func_total = len(tasks)

    cost_total = (sec_data.get("cost_usd", 0) + sec_fin_data.get("cost_usd", 0)
                  + (func_data.get("summary", {}).get("total_cost_usd", 0) if func_data else 0))

    sec_cls = "ok" if sec_total and sec_pass / sec_total >= 0.9 else ("warn" if sec_total else "")
    comp_cls = "ok" if comp_total and comp_pass / comp_total >= 0.8 else ("warn" if comp_total else "")
    func_cls = "ok" if func_total and func_pass / func_total >= 0.8 else ("warn" if func_total else "")

    cards = [
        _card(overall_str, "Compliance-Gesamtstatus", overall_cls),
        _card(f"{sec_pass}/{sec_total}", "Security Tests bestanden", sec_cls),
        _card(f"{comp_pass}/{comp_total}", "Compliance Tests bestanden", comp_cls),
        _card(f"{func_pass}/{func_total}", "Funktions-Tasks bestanden", func_cls),
        _card(f"${cost_total:.3f}", "API-Kosten gesamt (USD)"),
    ]
    return '<h2>Übersicht</h2><div class="cards">' + "".join(cards) + "</div>"


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
        rows.append(
            f"<tr><td>{cls}</td><td>{p}/{total}</td>"
            f"<td>{_pct_badge(p, total, 0.9)}</td>"
            f"<td>{_bar(p, total, 0.9)}</td></tr>"
        )

    total_pass = sec_data.get("total_pass", 0) + sec_fin_data.get("total_pass", 0)
    total_all  = total_pass + sec_data.get("total_fail", 0) + sec_fin_data.get("total_fail", 0)
    cost       = sec_data.get("cost_usd", 0) + sec_fin_data.get("cost_usd", 0)
    tokens     = sec_data.get("token_total", 0) + sec_fin_data.get("token_total", 0)
    lat        = sec_data.get("latency_p50_ms") or sec_fin_data.get("latency_p50_ms") or 0

    cards = [
        _card(f"{total_pass}/{total_all}", "Tests bestanden", "ok" if total_all and total_pass/total_all >= 0.9 else "warn"),
        _card(f"${cost:.3f}", "API-Kosten (USD)"),
        _card(f"{tokens:,}", "Tokens gesamt"),
        _card(f"{lat} ms", "Ø Latenz"),
    ]

    return (
        "<h2>Dimension 2 – Sicherheit (Red-Team-Suite)</h2>"
        '<div class="cards">' + "".join(cards) + "</div>"
        "<br>"
        "<table><thead><tr>"
        "<th>Angriffsklasse</th><th>Bestanden</th><th>Rate</th><th>Verteilung</th>"
        "</tr></thead><tbody>" + "".join(rows) + "</tbody></table>"
    )


def _section_compliance(comp_data: dict, scorecard: dict | None) -> str:
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

    cards = [_card(overall_str, "Compliance-Gesamtrate", overall_cls)]

    return (
        "<h2>Dimension 3 – Compliance (EU AI Act)</h2>"
        '<div class="cards">' + "".join(cards) + "</div><br>"
        "<table><thead><tr>"
        "<th>Artikel</th><th>Bestanden</th><th>Rate</th><th>Verteilung</th><th>Status</th>"
        "</tr></thead><tbody>" + "".join(rows) + "</tbody></table>"
    )


def _section_functionality(func_data: dict) -> str:
    if not func_data:
        return "<h2>Dimension 1 – Funktionalität</h2><p style='color:#636e72'>Keine Daten vorhanden.</p>"

    tasks = func_data.get("tasks", [])
    summary = func_data.get("summary", {})

    rows = []
    for t in tasks:
        task_id = t.get("task_id", "–")
        passed = t.get("passed", False)
        cost = t.get("cost_usd", 0)
        latency = t.get("latency_ms", 0)
        badge = '<span class="badge ok">✓ OK</span>' if passed else '<span class="badge err">✗ Fail</span>'
        rows.append(
            f"<tr><td>{task_id}</td><td>{badge}</td>"
            f"<td>${cost:.4f}</td><td>{latency} ms</td></tr>"
        )

    total_tasks = len(tasks)
    passed_tasks = sum(1 for t in tasks if t.get("passed"))
    total_cost = summary.get("total_cost_usd", 0)
    avg_latency = summary.get("avg_latency_ms", 0)

    func_cls = "ok" if total_tasks and passed_tasks / total_tasks >= 0.8 else "warn"
    cards = [
        _card(f"{passed_tasks}/{total_tasks}", "Tasks bestanden", func_cls),
        _card(f"${total_cost:.3f}", "API-Kosten (USD)"),
        _card(f"{avg_latency:.0f} ms", "Ø Latenz"),
    ]

    table_rows = "".join(rows) if rows else "<tr><td colspan='4' style='color:#636e72'>Keine Task-Daten</td></tr>"

    return (
        "<h2>Dimension 1 – Funktionalität (LangGraph + DeepEval)</h2>"
        '<div class="cards">' + "".join(cards) + "</div><br>"
        "<table><thead><tr>"
        "<th>Task</th><th>Status</th><th>Kosten (USD)</th><th>Latenz</th>"
        "</tr></thead><tbody>" + table_rows + "</tbody></table>"
    )


# ---------------------------------------------------------------------------
# Report zusammenbauen
# ---------------------------------------------------------------------------

def generate_report(
    security_paths: list[str] | None = None,
    compliance_path: str | None = None,
    scorecard_path: str | None = None,
    functionality_path: str | None = None,
    out_path: str = "report.html",
) -> Path:
    security_paths = security_paths or []

    sec_datasets = [_parse_security(_promptfoo_results(_load_json(p))) for p in security_paths]
    sec_data     = sec_datasets[0] if sec_datasets else {}
    sec_fin_data = sec_datasets[1] if len(sec_datasets) > 1 else {}

    comp_results = _promptfoo_results(_load_json(compliance_path))
    comp_data    = _parse_compliance(comp_results)
    scorecard    = _load_json(scorecard_path)
    func_data    = _parse_func_costs(_load_json(functionality_path))

    now = datetime.now().strftime("%d.%m.%Y %H:%M")

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
  <h1>Agent-Eval@OVB – Benchmark Report</h1>
  <p>OVB Holding AG × TU Darmstadt &nbsp;|&nbsp; Erstellt: {now}</p>
</header>
<div class="container">
  {_section_summary(sec_data, sec_fin_data, comp_data, scorecard, func_data)}
  {_section_security(sec_data, sec_fin_data)}
  {_section_compliance(comp_data, scorecard)}
  {_section_functionality(func_data)}
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
    parser = argparse.ArgumentParser(description="Agent-Eval@OVB HTML-Report-Generator")
    parser.add_argument("--security",      action="append", metavar="FILE",
                        help="Promptfoo Security-Ergebnis JSON (mehrfach verwendbar)")
    parser.add_argument("--compliance",    metavar="FILE", default="compliance_results.json")
    parser.add_argument("--scorecard",     metavar="FILE", default="compliance_scorecard.json")
    parser.add_argument("--functionality", metavar="FILE",
                        default="evals/functionality/functionality_costs.json")
    parser.add_argument("--out",           metavar="FILE", default="report.html")
    args = parser.parse_args()

    security_paths = args.security or ["security_results.json", "security_finance_results.json"]

    generate_report(
        security_paths=security_paths,
        compliance_path=args.compliance,
        scorecard_path=args.scorecard,
        functionality_path=args.functionality,
        out_path=args.out,
    )


if __name__ == "__main__":
    main()
