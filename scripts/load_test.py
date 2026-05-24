"""
Async load test for Synapse GraphRAG API.

Measures P50/P95/P99 latency, RPS, and error rate under concurrent load.

Usage:
    python scripts/load_test.py [--url http://localhost:8000] [--concurrency 10] [--duration 30]

Requires: pip install httpx
"""

from __future__ import annotations

import argparse
import asyncio
import itertools
import json
import math
import statistics
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import httpx

RESULTS_DIR = Path(__file__).parent.parent / "docs" / "evaluation" / "results"

QUERIES: list[dict] = [
    {"query": "Кто отвечает за выдачу IT-доступов при онбординге?", "role": "junior"},
    {"query": "Какие ценности закреплены в кодексе поведения?", "role": "junior"},
    {"query": "Каков оптимальный размер Merge Request?", "role": "middle"},
    {"query": "Какую модель ветвления использует Synapse Corp?", "role": "middle"},
    {"query": "Какой принцип запрещает общую базу данных между микросервисами?", "role": "senior"},
    {"query": "Каков срок погашения критического технического долга?", "role": "senior"},
    {"query": "Каков принцип предоставления доступов в Synapse Corp?", "role": "manager"},
    {"query": "Что относится к инцидентам класса P1 по регламенту ИБ?", "role": "admin"},
]


@dataclass
class RequestResult:
    status_code: int
    latency_ms: float
    error: str = ""


@dataclass
class LoadTestStats:
    total_requests: int = 0
    successful: int = 0
    errors: int = 0
    latencies: list[float] = field(default_factory=list)
    start_time: float = field(default_factory=time.perf_counter)
    end_time: float = 0.0

    @property
    def duration_s(self) -> float:
        return max(self.end_time - self.start_time, 0.001)

    @property
    def rps(self) -> float:
        return self.total_requests / self.duration_s

    @property
    def error_rate(self) -> float:
        return self.errors / max(self.total_requests, 1) * 100

    def percentile(self, p: float) -> float:
        if not self.latencies:
            return 0.0
        sorted_lat = sorted(self.latencies)
        idx = math.ceil(p / 100 * len(sorted_lat)) - 1
        return sorted_lat[max(idx, 0)]

    @property
    def p50(self) -> float:
        return self.percentile(50)

    @property
    def p95(self) -> float:
        return self.percentile(95)

    @property
    def p99(self) -> float:
        return self.percentile(99)

    @property
    def avg(self) -> float:
        return statistics.mean(self.latencies) if self.latencies else 0.0

    @property
    def max_latency(self) -> float:
        return max(self.latencies) if self.latencies else 0.0


async def send_request(
    client: httpx.AsyncClient,
    base_url: str,
    query: str,
    role: str,
) -> RequestResult:
    headers = {"X-User-Role": role, "Content-Type": "application/json"}
    t0 = time.perf_counter()
    try:
        resp = await client.post(
            f"{base_url}/query",
            json={"query": query},
            headers=headers,
            timeout=30.0,
        )
        latency_ms = (time.perf_counter() - t0) * 1000
        return RequestResult(status_code=resp.status_code, latency_ms=latency_ms)
    except httpx.ConnectError as e:
        return RequestResult(status_code=0, latency_ms=0.0, error=str(e))
    except httpx.TimeoutException:
        return RequestResult(status_code=0, latency_ms=30_000.0, error="timeout")
    except Exception as e:
        return RequestResult(status_code=0, latency_ms=0.0, error=str(e))


async def worker(
    worker_id: int,
    base_url: str,
    query_cycle: itertools.cycle,
    stats: LoadTestStats,
    stop_event: asyncio.Event,
    lock: asyncio.Lock,
) -> None:
    async with httpx.AsyncClient() as client:
        while not stop_event.is_set():
            item = next(query_cycle)
            result = await send_request(client, base_url, item["query"], item["role"])
            async with lock:
                stats.total_requests += 1
                if result.status_code == 200:
                    stats.successful += 1
                    stats.latencies.append(result.latency_ms)
                else:
                    stats.errors += 1
                    if result.latency_ms > 0:
                        stats.latencies.append(result.latency_ms)


async def run_load_test(base_url: str, concurrency: int, duration_s: int) -> LoadTestStats:
    stats = LoadTestStats(start_time=time.perf_counter())
    stop_event = asyncio.Event()
    lock = asyncio.Lock()
    query_cycle = itertools.cycle(QUERIES)

    tasks = [
        asyncio.create_task(worker(i, base_url, query_cycle, stats, stop_event, lock))
        for i in range(concurrency)
    ]

    print(f"  Running {concurrency} concurrent workers for {duration_s}s ...", flush=True)

    done_at = time.perf_counter() + duration_s
    interval = 5
    while time.perf_counter() < done_at:
        await asyncio.sleep(min(interval, done_at - time.perf_counter()))
        elapsed = time.perf_counter() - stats.start_time
        async with lock:
            total = stats.total_requests
            errs = stats.errors
        print(
            f"  [{elapsed:.0f}s] requests={total} errors={errs} "
            f"rps≈{total / max(elapsed, 0.001):.1f}",
            flush=True,
        )

    stop_event.set()
    await asyncio.gather(*tasks, return_exceptions=True)
    stats.end_time = time.perf_counter()
    return stats


def check_acceptance_criteria(stats: LoadTestStats) -> list[tuple[str, bool, str]]:
    checks = [
        ("P50 < 2000 ms", stats.p50 < 2000, f"P50={stats.p50:.0f} ms"),
        ("P95 < 5000 ms", stats.p95 < 5000, f"P95={stats.p95:.0f} ms"),
        ("Error rate < 1%", stats.error_rate < 1.0, f"error_rate={stats.error_rate:.1f}%"),
        ("RPS ≥ 1.0", stats.rps >= 1.0, f"RPS={stats.rps:.2f}"),
    ]
    return checks


def write_report(stats: LoadTestStats, concurrency: int, duration_s: int, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = output_dir / f"load_test_{ts}.md"

    checks = check_acceptance_criteria(stats)
    all_pass = all(ok for _, ok, _ in checks)

    lines: list[str] = [
        "# Load Test Report — Synapse GraphRAG API",
        "",
        f"**Date:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"**Concurrency:** {concurrency} workers",
        f"**Duration:** {duration_s} s",
        f"**Total requests:** {stats.total_requests}",
        "",
        "## Latency Percentiles",
        "",
        "| Metric | Value |",
        "|--------|------:|",
        f"| P50 (median) | {stats.p50:.0f} ms |",
        f"| P95 | {stats.p95:.0f} ms |",
        f"| P99 | {stats.p99:.0f} ms |",
        f"| Avg | {stats.avg:.0f} ms |",
        f"| Max | {stats.max_latency:.0f} ms |",
        "",
        "## Throughput & Reliability",
        "",
        "| Metric | Value |",
        "|--------|------:|",
        f"| RPS | {stats.rps:.2f} |",
        f"| Successful | {stats.successful} |",
        f"| Errors | {stats.errors} |",
        f"| Error rate | {stats.error_rate:.2f}% |",
        "",
        "## Acceptance Criteria",
        "",
        "| Criterion | Target | Actual | Status |",
        "|-----------|--------|--------|--------|",
    ]
    for name, ok, actual in checks:
        status = "PASS" if ok else "FAIL"
        lines.append(f"| {name.split('<')[0].split('≥')[0].strip()} "
                     f"| {name.split(' ', 1)[1]} | {actual} | {status} |")

    lines += [
        "",
        f"## Overall: {'PASS' if all_pass else 'FAIL'}",
        "",
        "### Notes",
        "- Queries distributed across all 5 roles and 8 question variants",
        "- Mock backend: latency primarily represents FastAPI + LangGraph overhead",
        "- For GPU demo: run against full stack with `--profile gpu --profile observability`",
        "- Prometheus metrics available at `/metrics` during test run",
    ]

    report_path.write_text("\n".join(lines), encoding="utf-8")
    return report_path


async def async_main(args: argparse.Namespace) -> int:
    print(f"Load test: {args.concurrency} workers × {args.duration}s against {args.url}")
    print()

    # Health check first
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"{args.url}/health", timeout=5.0)
            if resp.status_code != 200:
                print(f"Health check failed: HTTP {resp.status_code}", file=sys.stderr)
                return 1
        print(f"  Health check OK ({args.url}/health)")
    except Exception as e:
        print(f"  Cannot reach {args.url}: {e}", file=sys.stderr)
        return 1

    stats = await run_load_test(args.url, args.concurrency, args.duration)

    print()
    print("Results:")
    print(f"  P50={stats.p50:.0f} ms  P95={stats.p95:.0f} ms  P99={stats.p99:.0f} ms")
    print(f"  RPS={stats.rps:.2f}  errors={stats.errors}/{stats.total_requests} ({stats.error_rate:.1f}%)")

    checks = check_acceptance_criteria(stats)
    all_pass = all(ok for _, ok, _ in checks)
    print()
    for name, ok, actual in checks:
        print(f"  {'PASS' if ok else 'FAIL'} {name} ({actual})")

    report_path = write_report(stats, args.concurrency, args.duration, Path(args.output))
    print(f"\nReport written to: {report_path}")

    return 0 if all_pass else 1


def main() -> None:
    parser = argparse.ArgumentParser(description="Synapse API load tester")
    parser.add_argument("--url", default="http://localhost:8000")
    parser.add_argument("--concurrency", type=int, default=5, help="Number of concurrent workers")
    parser.add_argument("--duration", type=int, default=30, help="Test duration in seconds")
    parser.add_argument("--output", default=str(RESULTS_DIR))
    args = parser.parse_args()

    exit_code = asyncio.run(async_main(args))
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
