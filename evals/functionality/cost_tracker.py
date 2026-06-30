"""
Wirtschaftlichkeits-Tracking für den LangGraph-Agenten.
Erfasst Token-Verbrauch und Latenz pro Task direkt aus den LangGraph-Callbacks.
"""

import json
from datetime import datetime
from pathlib import Path

# Metriken bei denen ein niedrigerer Score besser ist (Schwelle: score <= threshold)
_INVERSE_METRICS = {"hallucination"}


def _passes(key: str, score: float) -> bool:
    threshold = 0.5 if key in _INVERSE_METRICS else 0.7
    return score <= threshold if key in _INVERSE_METRICS else score >= threshold


class CostTracker:
    def __init__(
        self,
        output_path: str = "functionality_costs.json",
        use_case: str | None = None,
        metrics: list[str] | None = None,
        core_metrics: list[str] | None = None,
    ):
        self.output_path = Path(output_path)
        self.use_case = use_case
        self.metrics = metrics or []
        # Teilmenge von metrics, die UC-übergreifend vergleichbar ist (Kern).
        self.core_metrics = core_metrics or []
        self.records: list[dict] = []

    def record(self, task_id: str, cost_data: dict) -> None:
        self.records.append({"task_id": task_id, **cost_data})
        self._save()

    def record_error(self, task_id: str, error_msg: str, cost_usd: float | None = None) -> None:
        """Erfasst einen fehlgeschlagenen Task (z. B. API-Quota erschöpft, Timeout).

        cost_usd: falls vor dem endgültigen Fehlschlag bereits reale, bei
        OpenRouter abgerechnete Tokens verbraucht wurden (z. B. ein Content-
        Filter-Treffer, der nach erfolgter Inferenz eine leere Antwort liefert) –
        diese Kosten sollen nicht unsichtbar verschwinden, nur weil der Task
        am Ende als Fehler gilt."""
        record = {
            "task_id":    task_id,
            "error":      str(error_msg)[:400],
            "aborted_at": datetime.now().isoformat(timespec="seconds"),
            "passed":     False,
        }
        if cost_usd:
            record["cost_usd"] = round(cost_usd, 6)
        self.records.append(record)
        self._save()

    def update_metrics(self, task_id: str, metrics: dict) -> None:
        for r in self.records:
            if r["task_id"] == task_id:
                r.update(metrics)
                self._recompute_passed(r)
                break
        self._save()

    def _recompute_passed(self, record: dict) -> None:
        """Berechnet passed dynamisch über alle UC-Metrik-Schlüssel – WÄHREND
        der Lauf noch läuft. Wartet bewusst, bis alle erwarteten Scores für
        diesen Task vorliegen (Testfunktionen schreiben sie nacheinander),
        sonst würde ein Task fälschlich als "nicht bestanden" gelten, nur weil
        z. B. answer_relevancy noch gar nicht dran war. Für die ENDGÜLTIGE
        Bewertung nach Testende siehe finalize_passed() – dort bedeutet ein
        zu diesem Zeitpunkt immer noch fehlendes Score einen echten, nicht nur
        einen vorübergehenden Mangel."""
        if not self.metrics:
            return
        score_keys = [k for k in self.metrics if k != "required_fields"]
        scores = [record.get(k) for k in score_keys]
        if not all(s is not None for s in scores):
            return  # warten bis alle Scores vorliegen

        record["passed"] = all(_passes(key, record[key]) for key in score_keys)

    def finalize_passed(self) -> None:
        """Endgültige Berechnung von passed für alle Records, nach Testende
        (pytest_sessionfinish).

        Anders als _recompute_passed() (während des Laufs, wartet auf alle
        Scores) gilt hier: der Lauf ist vorbei – ein zu diesem Zeitpunkt immer
        noch fehlendes Metrik-Score wird nie mehr ankommen (der zugehörige
        Test ist nach erschöpften Retries endgültig fehlgeschlagen, z. B.
        pytest.fail in test_task_completion). Das zählt als nicht bestanden,
        nicht als unklares "–" für immer – sonst verschwinden Tasks mit
        teilweise erfolgreichen Metriken (z. B. Tool Correctness vorhanden,
        Task Completion fehlgeschlagen) komplett aus den Bestehensraten in
        Übersicht und Einzelansicht, obwohl reale Metrikwerte vorliegen.
        """
        score_keys = [k for k in self.metrics if k != "required_fields"]
        if not score_keys:
            return
        for r in self.records:
            if r.get("error"):
                continue  # bereits explizit passed=False in record_error()
            r["passed"] = all(
                r.get(key) is not None and _passes(key, r[key])
                for key in score_keys
            )

    def get_eval_cost(self, task_id: str) -> float:
        for r in self.records:
            if r["task_id"] == task_id:
                return r.get("eval_cost_usd", 0.0)
        return 0.0

    def _save(self) -> None:
        payload = {
            "use_case": self.use_case,
            "metrics": self.metrics,
            "core_metrics": self.core_metrics,
            "records": self.records,
            "summary": self._summary(),
        }
        self.output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def _summary(self) -> dict:
        if not self.records:
            return {}
        # Fehler-Records haben i.d.R. keine Tokens/Kosten/Latenz, außer
        # record_error() wurde mit cost_usd aufgerufen (Content-Filter-Fall:
        # Tokens trotz leerer Antwort verbraucht) → sicher mit .get()
        ok_records   = [r for r in self.records if not r.get("error")]
        err_records  = [r for r in self.records if r.get("error")]
        total_tokens = sum(r.get("total_tokens", 0) for r in self.records)
        agent_cost   = sum(r.get("cost_usd", 0) for r in self.records)
        eval_cost    = sum(r.get("eval_cost_usd", 0.0) for r in self.records)
        latencies    = [r["latency_ms"] for r in ok_records if "latency_ms" in r]
        avg_latency  = sum(latencies) / len(latencies) if latencies else 0
        p95_latency  = sorted(latencies)[max(0, int(0.95 * len(latencies)) - 1)] if latencies else 0
        return {
            "total_tokens":     total_tokens,
            "agent_cost_usd":   round(agent_cost, 6),
            "eval_cost_usd":    round(eval_cost, 6),
            "total_cost_usd":   round(agent_cost + eval_cost, 6),
            "avg_latency_ms":   round(avg_latency),
            "p95_latency_ms":   p95_latency,
            "error_count":      len(err_records),
            "aborted":          len(err_records) > 0,
            "first_error_task": err_records[0]["task_id"]  if err_records else None,
            "first_error_msg":  err_records[0]["error"]    if err_records else None,
            "first_error_at":   err_records[0].get("aborted_at") if err_records else None,
        }

    def print_report(self) -> None:
        sep   = "─" * 70
        title = "=" * 70
        s     = self._summary()
        uc    = self.use_case or "–"

        print(f"\n{title}")
        print(f"  WIRTSCHAFTLICHKEIT – Funktionalitäts-Eval  |  Use Case: {uc}")
        print(title)
        print(f"\n📊 GESAMT")
        print(sep)
        print(f"  Tasks ausgeführt:    {len(self.records)}")
        print(f"  Tokens gesamt:       {s.get('total_tokens', 0):,}")
        print(f"  Gesamtkosten:        ${s.get('total_cost_usd', 0):.6f}")
        print(f"  Ø Kosten / Task:     ${s.get('total_cost_usd', 0) / max(len(self.records), 1):.6f}")
        print(f"\n⏱  LATENZ")
        print(sep)
        print(f"  Durchschnitt:        {s.get('avg_latency_ms', 0):,} ms")
        print(f"  P95:                 {s.get('p95_latency_ms', 0):,} ms")
        print(f"\n📋 PRO TASK")
        print(sep)
        header = "  " + "Task-ID".ljust(20) + "Tokens".ljust(12) + "Kosten (USD)".ljust(16) + "Latenz"
        print(header)
        print("  " + "─" * 60)
        for r in self.records:
            if r.get("error"):
                print(f"  {r['task_id']:<20}{'— API-Fehler —':<28}{'(abgebrochen)'}")
                continue
            print(
                f"  {r['task_id']:<20}"
                f"{r.get('total_tokens', 0):<12,}"
                f"${r.get('cost_usd', 0):<15.6f}"
                f"{r.get('latency_ms', 0):,} ms"
            )
        avg_cost = s.get("total_cost_usd", 0) / max(len(self.records), 1)
        print(f"\n💡 HOCHRECHNUNGEN (Ø ${avg_cost:.6f} / Task)")
        print(sep)
        for label, n in [("1.000 Tasks/Tag", 1_000), ("10.000 Tasks/Tag", 10_000),
                         ("100.000 Tasks/Monat", 100_000), ("1.000.000 Tasks/Monat", 1_000_000)]:
            print(f"  {label:<30} → ${avg_cost * n:.2f}")
        print(f"\n{title}\n")
