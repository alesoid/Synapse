"""
RBAC leakage test for Synapse GraphRAG.

Verifies that each role can only access documents at or below its access level.
Target: 0% leakage across all role/document combinations.

Usage:
    python scripts/eval_rbac.py [--url http://localhost:8000] [--output docs/evaluation/results/]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import httpx

CORPUS_MANIFEST = Path(__file__).parent.parent / "docs" / "corpus" / "corpus_manifest.json"
RESULTS_DIR = Path(__file__).parent.parent / "docs" / "evaluation" / "results"

ROLES: list[tuple[str, int]] = [
    ("junior", 1),
    ("middle", 2),
    ("senior", 3),
    ("manager", 4),
    ("admin", 5),
]

# Questions that reliably pull from specific document levels
PROBE_QUESTIONS: list[dict] = [
    # L1
    {"question": "Кто отвечает за выдачу IT-доступов при онбординге?",
     "target_level": 1, "expected_doc": "INS-HR-001"},
    # L2
    {"question": "Каков оптимальный размер Merge Request в стандарте код-ревью?",
     "target_level": 2, "expected_doc": "STD-ENG-001"},
    # L3
    {"question": "Какой архитектурный принцип запрещает общую базу данных между микросервисами?",
     "target_level": 3, "expected_doc": "STD-ARCH-001"},
    # L4
    {"question": "На каком принципе построена политика предоставления доступов в Synapse Corp?",
     "target_level": 4, "expected_doc": "POL-SEC-001"},
    # L5
    {"question": "Что относится к инцидентам класса P1 в регламенте информационной безопасности?",
     "target_level": 5, "expected_doc": "POL-SEC-005"},
]


@dataclass
class LeakResult:
    role: str
    role_level: int
    question: str
    target_level: int
    expected_doc: str
    status_code: int
    sources_returned: list[str]
    leaked: bool
    leak_detail: str
    latency_ms: float


def probe(client: httpx.Client, base_url: str, role: str, question: str) -> tuple[int, list[dict], float]:
    headers = {"X-User-Role": role, "Content-Type": "application/json"}
    t0 = time.perf_counter()
    try:
        resp = client.post(f"{base_url}/query", json={"query": question}, headers=headers, timeout=30.0)
        latency_ms = (time.perf_counter() - t0) * 1000
        try:
            body = resp.json()
        except Exception:
            body = {}
        sources = body.get("sources", [])
        return resp.status_code, sources, latency_ms
    except httpx.ConnectError:
        return 0, [], 0.0
    except httpx.TimeoutException:
        return 0, [], 30_000.0


def load_manifest(path: Path) -> dict[str, int]:
    """Return mapping doc_id → access_level."""
    with path.open(encoding="utf-8") as f:
        manifest = json.load(f)
    return {doc["doc_id"]: doc["access_level"] for doc in manifest}


def run_rbac_tests(base_url: str, manifest: dict[str, int]) -> list[LeakResult]:
    results: list[LeakResult] = []

    with httpx.Client() as client:
        for probe_q in PROBE_QUESTIONS:
            target_level = probe_q["target_level"]
            expected_doc = probe_q["expected_doc"]
            question = probe_q["question"]

            for role, role_level in ROLES:
                print(
                    f"  role={role:7s} (L{role_level}) → L{target_level} doc [{expected_doc}] ...",
                    end=" ", flush=True,
                )
                status_code, sources, latency_ms = probe(client, base_url, role, question)

                source_doc_ids = [s.get("doc_id", "") for s in sources]

                if role_level >= target_level:
                    # Should be allowed — we don't test leak here (positive path)
                    leaked = False
                    detail = "allowed"
                else:
                    # Role is BELOW required level — should NOT see this doc
                    if expected_doc in source_doc_ids:
                        leaked = True
                        detail = f"LEAK: {expected_doc} returned to role={role} (L{role_level} < L{target_level})"
                    else:
                        # Also check if any source has access_level > role_level
                        over_level = [
                            s for s in sources
                            if manifest.get(s.get("doc_id", ""), 0) > role_level
                        ]
                        if over_level:
                            leaked = True
                            detail = (
                                f"LEAK: {len(over_level)} source(s) with level > {role_level} returned: "
                                + str([s.get("doc_id") for s in over_level])
                            )
                        else:
                            leaked = False
                            detail = "blocked"

                result = LeakResult(
                    role=role,
                    role_level=role_level,
                    question=question,
                    target_level=target_level,
                    expected_doc=expected_doc,
                    status_code=status_code,
                    sources_returned=source_doc_ids,
                    leaked=leaked,
                    leak_detail=detail,
                    latency_ms=latency_ms,
                )
                results.append(result)

                if leaked:
                    print(f"LEAK  ({latency_ms:.0f} ms)  ← {detail}")
                elif detail == "allowed":
                    print(f"OK    ({latency_ms:.0f} ms)  [expected access]")
                else:
                    print(f"OK    ({latency_ms:.0f} ms)  [correctly blocked]")

    return results


def write_report(results: list[LeakResult], manifest: dict[str, int], output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = output_dir / f"eval_rbac_{ts}.md"

    leaks = [r for r in results if r.leaked]
    total_restricted = sum(1 for r in results if r.role_level < r.target_level)
    leak_rate = len(leaks) / total_restricted * 100 if total_restricted else 0

    lines: list[str] = [
        "# RBAC Leakage Test Report",
        "",
        f"**Date:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"**Total probes:** {len(results)}  "
        f"**Restricted probes:** {total_restricted}  "
        f"**Leaks detected:** {len(leaks)}",
        f"**Leakage rate:** {leak_rate:.1f}%  (target: 0%)",
        "",
        f"## AC-03 Status: {'PASS — 0% leakage' if not leaks else 'FAIL — leakage detected'}",
        "",
        "## Matrix: Role × Document Level",
        "",
        "Legend: ✅ allowed (role >= doc level) | 🔒 blocked | ❌ LEAK",
        "",
    ]

    # Build matrix header
    doc_levels = sorted(set(r.target_level for r in results))
    role_labels = [f"L{r} {name}" for name, r in ROLES]

    lines.append("| Role | " + " | ".join(f"L{lvl}" for lvl in doc_levels) + " |")
    lines.append("|------|" + "|".join("-----" for _ in doc_levels) + "|")

    for role, role_level in ROLES:
        row = [f"{role} (L{role_level})"]
        for lvl in doc_levels:
            cell_results = [r for r in results if r.role == role and r.target_level == lvl]
            if not cell_results:
                row.append("—")
            elif cell_results[0].role_level >= lvl:
                row.append("✅")
            elif cell_results[0].leaked:
                row.append("❌")
            else:
                row.append("🔒")
        lines.append("| " + " | ".join(row) + " |")

    lines += [
        "",
        "## Detailed Results",
        "",
        "| Role | Role L | Doc | Doc L | Status | HTTP | Sources Returned |",
        "|------|--------|-----|-------|--------|------|-----------------|",
    ]
    for r in results:
        if r.role_level < r.target_level:
            status = "❌ LEAK" if r.leaked else "🔒 blocked"
        else:
            status = "✅ allowed"
        sources_str = ", ".join(r.sources_returned) if r.sources_returned else "—"
        lines.append(
            f"| {r.role} | L{r.role_level} | {r.expected_doc} | L{r.target_level} "
            f"| {status} | {r.status_code} | {sources_str} |"
        )

    if leaks:
        lines += ["", "## Leak Details", ""]
        for r in leaks:
            lines += [
                f"### LEAK: {r.role} (L{r.role_level}) → {r.expected_doc} (L{r.target_level})",
                f"**Question:** {r.question}",
                f"**Sources returned:** {r.sources_returned}",
                f"**Detail:** {r.leak_detail}",
                "",
            ]

    report_path.write_text("\n".join(lines), encoding="utf-8")
    return report_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Synapse RBAC leakage tester")
    parser.add_argument("--url", default="http://localhost:8000", help="Base URL of Synapse API")
    parser.add_argument("--output", default=str(RESULTS_DIR), help="Output directory for report")
    args = parser.parse_args()

    manifest = load_manifest(CORPUS_MANIFEST)

    print(f"RBAC leakage test against {args.url}")
    print(f"Corpus: {len(manifest)} documents, {len(PROBE_QUESTIONS)} probe questions × {len(ROLES)} roles")
    print()

    results = run_rbac_tests(args.url, manifest)

    leaks = [r for r in results if r.leaked]
    restricted = sum(1 for r in results if r.role_level < r.target_level)
    print()
    print(f"Leakage: {len(leaks)}/{restricted} restricted probes leaked ({len(leaks) / restricted * 100:.1f}%)")

    report_path = write_report(results, manifest, Path(args.output))
    print(f"Report written to: {report_path}")

    if leaks:
        print(f"\nFAIL: {len(leaks)} leaks detected", file=sys.stderr)
        sys.exit(1)
    else:
        print("\nPASS: 0% leakage")


if __name__ == "__main__":
    main()
