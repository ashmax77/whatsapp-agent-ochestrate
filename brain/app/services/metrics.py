"""
Telemetry and Prometheus Observability Metrics Service (Phase 9).
Provides request rate tracking, turn latency percentiles, tool execution stats,
handoff counters, and per-branch order distribution.
"""

import time
from collections import defaultdict
from typing import Any, Dict, List


class MetricsCollector:
    def __init__(self):
        self.start_time = time.time()
        self.requests_total: Dict[str, int] = defaultdict(int)
        self.message_types_total: Dict[str, int] = defaultdict(int)
        self.tool_calls_total: Dict[str, int] = defaultdict(int)
        self.tool_errors_total: Dict[str, int] = defaultdict(int)
        self.handoffs_total: Dict[str, int] = defaultdict(int)
        self.orders_placed_total: Dict[str, int] = defaultdict(int)
        self.latencies: List[float] = []
        self._max_latency_samples = 1000

    def record_request(self, endpoint: str, status_code: int, duration_sec: float) -> None:
        key = f"{endpoint}:{status_code}"
        self.requests_total[key] += 1
        self.latencies.append(duration_sec)
        if len(self.latencies) > self._max_latency_samples:
            self.latencies = self.latencies[-self._max_latency_samples:]

    def record_message(self, msg_type: str) -> None:
        self.message_types_total[msg_type] += 1

    def record_tool_call(self, tool_name: str, ok: bool) -> None:
        self.tool_calls_total[tool_name] += 1
        if not ok:
            self.tool_errors_total[tool_name] += 1

    def record_handoff(self, reason: str) -> None:
        safe_reason = (reason or "unknown").replace(" ", "_")[:32]
        self.handoffs_total[safe_reason] += 1

    def record_order(self, branch_id: str) -> None:
        safe_branch = branch_id or "unassigned"
        self.orders_placed_total[safe_branch] += 1

    def compute_percentiles(self) -> Dict[str, float]:
        if not self.latencies:
            return {"p50": 0.0, "p95": 0.0, "p99": 0.0, "avg": 0.0, "count": 0}
        sorted_l = sorted(self.latencies)
        n = len(sorted_l)
        return {
            "p50": round(sorted_l[int(n * 0.50)], 3),
            "p95": round(sorted_l[int(min(n - 1, n * 0.95))], 3),
            "p99": round(sorted_l[int(min(n - 1, n * 0.99))], 3),
            "avg": round(sum(sorted_l) / n, 3),
            "count": n,
        }

    def to_dict(self) -> Dict[str, Any]:
        uptime_sec = round(time.time() - self.start_time, 1)
        return {
            "uptime_seconds": uptime_sec,
            "requests_total": dict(self.requests_total),
            "message_types_total": dict(self.message_types_total),
            "latency": self.compute_percentiles(),
            "tool_calls_total": dict(self.tool_calls_total),
            "tool_errors_total": dict(self.tool_errors_total),
            "handoffs_total": dict(self.handoffs_total),
            "orders_placed_total": dict(self.orders_placed_total),
        }

    def to_prometheus(self) -> str:
        lines: List[str] = [
            "# HELP pizza_uptime_seconds Total runtime of the pizza agent brain in seconds",
            "# TYPE pizza_uptime_seconds gauge",
            f"pizza_uptime_seconds {round(time.time() - self.start_time, 1)}",
            "",
            "# HELP pizza_requests_total Total HTTP requests handled by endpoint and status",
            "# TYPE pizza_requests_total counter",
        ]
        for key, count in self.requests_total.items():
            endpoint, status = key.split(":")
            lines.append(f'pizza_requests_total{{endpoint="{endpoint}",status="{status}"}} {count}')

        lines.extend([
            "",
            "# HELP pizza_messages_total Total incoming messages by type (text, audio, location)",
            "# TYPE pizza_messages_total counter",
        ])
        for msg_type, count in self.message_types_total.items():
            lines.append(f'pizza_messages_total{{type="{msg_type}"}} {count}')

        p = self.compute_percentiles()
        lines.extend([
            "",
            "# HELP pizza_latency_seconds Request processing latency summary",
            "# TYPE pizza_latency_seconds gauge",
            f'pizza_latency_seconds{{quantile="0.50"}} {p["p50"]}',
            f'pizza_latency_seconds{{quantile="0.95"}} {p["p95"]}',
            f'pizza_latency_seconds{{quantile="0.99"}} {p["p99"]}',
            f'pizza_latency_seconds{{quantile="avg"}} {p["avg"]}',
            "",
            "# HELP pizza_tool_calls_total Invocations per deterministic/RAG tool",
            "# TYPE pizza_tool_calls_total counter",
        ])
        for tool_name, count in self.tool_calls_total.items():
            err_count = self.tool_errors_total.get(tool_name, 0)
            lines.append(f'pizza_tool_calls_total{{tool="{tool_name}",status="ok"}} {count - err_count}')
            if err_count > 0:
                lines.append(f'pizza_tool_calls_total{{tool="{tool_name}",status="error"}} {err_count}')

        lines.extend([
            "",
            "# HELP pizza_handoffs_total Human escalation events by reason",
            "# TYPE pizza_handoffs_total counter",
        ])
        for reason, count in self.handoffs_total.items():
            lines.append(f'pizza_handoffs_total{{reason="{reason}"}} {count}')

        lines.extend([
            "",
            "# HELP pizza_orders_placed_total Total orders successfully confirmed by branch",
            "# TYPE pizza_orders_placed_total counter",
        ])
        for branch, count in self.orders_placed_total.items():
            lines.append(f'pizza_orders_placed_total{{branch="{branch}"}} {count}')

        lines.append("")
        return "\n".join(lines)


# Singleton instance
metrics = MetricsCollector()
