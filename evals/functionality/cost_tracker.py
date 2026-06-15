"""
Wirtschaftlichkeits-Tracking für den LangGraph-Agenten.
Erfasst Token-Verbrauch und Latenz pro Task und gibt einen Report aus –
analog zu scripts/cost_report.js, aber direkt aus LangGraph-Callbacks.
"""

import json
from pathlib import Path

# Metriken bei denen ein niedrigerer Score besser ist (Schwelle: score <= threshold)
_INVERSE_METRICS = {"hallucination"}


class CostTracker:
    def __init__(
        self,
        output_path: str = "functionality_costs.json",
        use_case: str | None = None,
        metrics: list[str] | None = None,
    ):
        self.output_path = Path(output_path)
        self.use_case = use_case
        self.metrics = metrics or []
        self.records: list[dict] = []

    def record(self, task_id: str, cost_data: dict) -> None:
        self.records.append({"task_id": task_id, **cost_data})
        self._save()

    def update_metrics(self, task_id: str, metrics: dict) -> None:
        for r in self.records:
            if r["task_id"] == task_id:
                r.update(metrics)
                self._recompute_passed(r)
                break
        self._save()

    def _recompute_passed(self, record: dict) -> None:
        """Berechnet passed dynamisch über alle UC-Metrik-Schlüssel."""
        if not self.metrics:
            return
        score_keys = [k for k in self.metrics if k != "required_fields"]
        scores = [record.get(k) for k in score_keys]
        if not all(s is not None for s in scores):
            return  # warten bis alle Scores vorliegen

        def _passes(key: str, score: float) -> bool:
            threshold = 0.5 if key in _INVERSE_METRICS else 0.7
            return score <= threshold if key in _INVERSE_METRICS else score >= threshold

        record["passed"] = all(
            _passes(key, record[key])
            for key in score_keys
            if record.get(key) is not None
        )

    def finalize_passed(self) -> None:
        """Erneute Berechnung von passed für alle Records (nach pytest_sessionfinish)."""
        for r in self.records:
            self._recompute_passed(r)

    def get_eval_cost(self, task_id: str) -> float:
        for r in self.records:
            if r["task_id"] == task_id:
                return r.get("eval_cost_usd", 0.0)
        return 0.0

    def _save(self) -> None:
        payload = {
            "use_case": self.use_case,
            "metrics": self.metrics,
            "records": self.records,
            "summary": self._summary(),
        }
        self.output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def _summary(self) -> dict:
        if not self.records:
            return {}
        total_tokens = sum(r["total_tokens"] for r in self.records)
        agent_cost   = sum(r["cost_usd"] for r in self.records)
        eval_cost    = sum(r.get("eval_cost_usd", 0.0) for r in self.records)
        latencies    = [r["latency_ms"] for r in self.records]
        avg_latency  = sum(latencies) / len(latencies)
        p95_latency  = sorted(latencies)[max(0, int(0.95 * len(latencies)) - 1)]
        return {
            "total_tokens":   total_tokens,
            "agent_cost_usd": round(agent_cost, 6),
            "eval_cost_usd":  round(eval_cost, 6),
            "total_cost_usd": round(agent_cost + eval_cost, 6),
            "avg_latency_ms": round(avg_latency),
            "p95_latency_ms": p95_latency,
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
            print(
                f"  {r['task_id']:<20}"
                f"{r['total_tokens']:<12,}"
                f"${r['cost_usd']:<15.6f}"
                f"{r['latency_ms']:,} ms"
            )
        avg_cost = s.get("total_cost_usd", 0) / max(len(self.records), 1)
        print(f"\n💡 HOCHRECHNUNGEN (Ø ${avg_cost:.6f} / Task)")
        print(sep)
        for label, n in [("1.000 Tasks/Tag", 1_000), ("10.000 Tasks/Tag", 10_000),
                         ("100.000 Tasks/Monat", 100_000), ("1.000.000 Tasks/Monat", 1_000_000)]:
            print(f"  {label:<30} → ${avg_cost * n:.2f}")
        print(f"\n{title}\n")
