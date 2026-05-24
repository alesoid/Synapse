"""
GraphRAG vs Vector-only comparison evaluator for Synapse.

Compares hybrid search (vector 0.7 + graph 0.3) against vector-only baseline
using the positive cases from the golden dataset.

Usage:
    python scripts/eval_comparison.py [--url http://localhost:8000] [--output docs/evaluation/results/]

Note: This script calls /query twice per question — once as the configured hybrid mode
and once simulating vector-only by checking if graph sources contributed. In mock mode
both paths return the same results; run against the full stack for meaningful comparison.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import httpx

DATASET_PATH = Path(__file__).parent.parent / "docs" / "evaluation" / "golden_dataset.jsonl"
RESULTS_DIR = Path(__file__).parent.parent / "docs" / "evaluation" / "results"

ROLE_TO_LEVEL: dict[str, int] = {
    "junior": 1,
    "middle": 2,
    "senior": 3,
    "manager": 4,
    "admin": 5,
}


@dataclass
class CompareResult:
    question_id: str
    question: str
    role: str
    expected_sources: list[str]
    # Hybrid GraphRAG
    hybrid_status: int
    hybrid_answer: str
    hybrid_sources: list[str]
    hybrid_quality: float
    hybrid_confidence: float
    hybrid_latency_ms: float
    hybrid_source_hit: bool
    # Vector-only (graph sources removed from scoring proxy)
    vector_only_status: int
    vector_only_sources: list[str]
    vector_only_quality: float
    vector_only_latency_ms: float
    vector_only_source_hit: bool
    # Delta
    quality_delta: float
    source_hit_delta: int


def load_positive_cases(path: Path) -> list[dict]:
    cases = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            data = json.loads(line)
            if data.get("category") == "positive":
                cases.append(data)
    return cases


def call_query(
    client: httpx.Client,
    base_url: str,
    question: str,
    role: str,
    vector_only: bool = False,
) -> tuple[int, dict, float]:
    headers = {"X-User-Role": role, "Content-Type": "application/json"}
    # Signal vector-only mode via custom header (backend honours if implemented)
    if vector_only:
        headers["X-Retrieval-Mode"] = "vector-only"
    t0 = time.perf_counter()
    try:
        resp = client.post(
            f"{base_url}/query",
            json={"query": question},
            headers=headers,
            timeout=30.0,
        )
        latency_ms = (time.perf_counter() - t0) * 1000
        try:
            body = resp.json()
        except Exception:
            body = {}
        return resp.status_code, body, latency_ms
    except httpx.ConnectError:
        return 0, {"error": "connection refused"}, 0.0
    except httpx.TimeoutException:
        return 0, {}, 30_000.0


def source_hit(body: dict, expected: list[str]) -> bool:
    returned_ids = {s.get("doc_id", "") for s in body.get("sources", [])}
    return any(e in returned_ids for e in expected)


def run_comparison(base_url: str, cases: list[dict]) -> list[CompareResult]:
    results: list[CompareResult] = []
    with httpx.Client() as client:
        for case in cases:
            qid = case["id"]
            question = case["question"]
            role = case["required_role"]
            expected_sources = case.get("expected_sources", [])

            print(f"  [{qid}] role={role:7s} ...", end=" ", flush=True)

            # Run hybrid (GraphRAG)
            h_status, h_body, h_latency = call_query(client, base_url, question, role, vector_only=False)
            h_quality = h_body.get("quality_score", 0.0)
            h_confidence = h_body.get("confidence_score", 0.0)
            h_sources = [s.get("doc_id", "") for s in h_body.get("sources", [])]
            h_answer = h_body.get("answer", "")
            h_hit = source_hit(h_body, expected_sources)

            # Run vector-only
            v_status, v_body, v_latency = call_query(client, base_url, question, role, vector_only=True)
            v_quality = v_body.get("quality_score", 0.0)
            v_sources = [s.get("doc_id", "") for s in v_body.get("sources", [])]
            v_hit = source_hit(v_body, expected_sources)

            quality_delta = h_quality - v_quality
            source_delta = int(h_hit) - int(v_hit)

            print(
                f"hybrid Q={h_quality:.1f} hit={'Y' if h_hit else 'N'}  "
                f"vector Q={v_quality:.1f} hit={'Y' if v_hit else 'N'}  "
                f"ΔQ={quality_delta:+.1f}"
            )

            results.append(CompareResult(
                question_id=qid,
                question=question,
                role=role,
                expected_sources=expected_sources,
                hybrid_status=h_status,
                hybrid_answer=h_answer,
                hybrid_sources=h_sources,
                hybrid_quality=h_quality,
                hybrid_confidence=h_confidence,
                hybrid_latency_ms=h_latency,
                hybrid_source_hit=h_hit,
                vector_only_status=v_status,
                vector_only_sources=v_sources,
                vector_only_quality=v_quality,
                vector_only_latency_ms=v_latency,
                vector_only_source_hit=v_hit,
                quality_delta=quality_delta,
                source_hit_delta=source_delta,
            ))
    return results


def write_report(results: list[CompareResult], output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = output_dir / f"eval_comparison_{ts}.md"

    n = len(results)
    hybrid_qualities = [r.hybrid_quality for r in results]
    vector_qualities = [r.vector_only_quality for r in results]
    hybrid_hits = sum(1 for r in results if r.hybrid_source_hit)
    vector_hits = sum(1 for r in results if r.vector_only_source_hit)
    avg_h_quality = statistics.mean(hybrid_qualities) if hybrid_qualities else 0
    avg_v_quality = statistics.mean(vector_qualities) if vector_qualities else 0
    avg_delta = avg_h_quality - avg_v_quality
    hypothesis_confirmed = avg_delta > 0 and hybrid_hits >= vector_hits

    lines: list[str] = [
        "# GraphRAG vs Vector-only Comparison Report",
        "",
        f"**Date:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"**Cases evaluated:** {n} (positive category from golden dataset)",
        "",
        "## Hypothesis",
        "",
        "> **H1:** Гибридный поиск GraphRAG (0.7 × vector + 0.3 × graph) даёт качество ответов выше,",
        "> чем vector-only RAG на том же корпусе.",
        "",
        "## Summary",
        "",
        "| Metric | GraphRAG (Hybrid) | Vector-only | Delta |",
        "|--------|:-----------------:|:-----------:|:-----:|",
        f"| Avg quality_score (1–5) | {avg_h_quality:.2f} | {avg_v_quality:.2f} | {avg_delta:+.2f} |",
        f"| Source hit rate | {hybrid_hits}/{n} ({hybrid_hits/n*100:.0f}%) "
        f"| {vector_hits}/{n} ({vector_hits/n*100:.0f}%) "
        f"| {hybrid_hits - vector_hits:+d} |",
        f"| Avg latency | {statistics.mean(r.hybrid_latency_ms for r in results):.0f} ms "
        f"| {statistics.mean(r.vector_only_latency_ms for r in results):.0f} ms | — |",
        "",
        f"## Hypothesis Status: {'✅ CONFIRMED' if hypothesis_confirmed else '❌ NOT CONFIRMED'}",
        "",
        f"GraphRAG quality delta: **{avg_delta:+.2f}** points "
        f"({'higher' if avg_delta > 0 else 'lower'} than vector-only).",
        f"Source hit improvement: **{hybrid_hits - vector_hits:+d}** cases.",
        "",
        "## Per-Question Results",
        "",
        "| ID | Role | GraphRAG Q | Vector Q | ΔQ | Hybrid Hit | Vector Hit |",
        "|----|------|:----------:|:--------:|:--:|:----------:|:----------:|",
    ]
    for r in results:
        lines.append(
            f"| {r.question_id} | {r.role} "
            f"| {r.hybrid_quality:.1f} | {r.vector_only_quality:.1f} "
            f"| {r.quality_delta:+.1f} "
            f"| {'✅' if r.hybrid_source_hit else '❌'} "
            f"| {'✅' if r.vector_only_source_hit else '❌'} |"
        )

    lines += [
        "",
        "## Interpretation",
        "",
        "The `quality_score` reflects the CriticAgent's LLM-as-a-Judge evaluation (1–5 scale).",
        "Source hit rate measures whether the expected document appeared in the returned sources.",
        "",
        "In mock mode both retrieval paths return the same stub data.",
        "Run against the full GPU stack (`--profile gpu`) for production-grade results.",
        "",
        "A positive ΔQ confirms that graph traversal enriches context beyond pure vector similarity,",
        "particularly for questions spanning multiple related documents (e.g. policy → standard cross-references).",
    ]

    report_path.write_text("\n".join(lines), encoding="utf-8")
    return report_path


def main() -> None:
    parser = argparse.ArgumentParser(description="GraphRAG vs vector-only comparison")
    parser.add_argument("--url", default="http://localhost:8000")
    parser.add_argument("--output", default=str(RESULTS_DIR))
    args = parser.parse_args()

    cases = load_positive_cases(DATASET_PATH)
    print(f"Comparing GraphRAG vs vector-only on {len(cases)} positive cases against {args.url}")
    print()

    results = run_comparison(args.url, cases)

    avg_delta = (
        sum(r.quality_delta for r in results) / len(results)
        if results else 0
    )
    print()
    print(f"Average quality delta (GraphRAG − vector-only): {avg_delta:+.2f}")

    report_path = write_report(results, Path(args.output))
    print(f"Report written to: {report_path}")

    if avg_delta <= 0:
        print("\nWARNING: GraphRAG did not outperform vector-only baseline.")
        sys.exit(1)


if __name__ == "__main__":
    main()
