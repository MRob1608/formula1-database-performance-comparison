from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BENCHMARK_DIR = PROJECT_ROOT / "benchmark_results"


def latest_json(prefix: str) -> Path:
    files = sorted(BENCHMARK_DIR.glob(f"{prefix}_*.json"), key=lambda path: path.stat().st_mtime)
    if not files:
        raise FileNotFoundError(f"No benchmark JSON files found for prefix: {prefix}")
    return files[-1]


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def result_map(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {result["name"]: result for result in payload["results"]}


def format_time(result: dict[str, Any]) -> str:
    if result.get("timed_out"):
        return ">600"
    if result.get("failed"):
        return f"failed after {result['elapsed_seconds']:.6f}"
    return f"{result['elapsed_seconds']:.6f}"


def format_rows(result: dict[str, Any]) -> str:
    if result.get("timed_out"):
        return "timeout"
    if result.get("failed"):
        return "failed"
    return str(result["row_count"])


def timeout_explanation(query_name: str) -> str:
    explanations = {
        "Q5_GRAPH_TEAMMATE_SHORTEST_PATH": (
            "PostgreSQL reads the same teammate network from a precomputed and indexed edge table, "
            "but it still has to recursively join edges and keep branch-local acyclic paths until "
            "it proves the Fangio-to-Norris shortest path. Neo4j follows index-free adjacency over "
            "the materialized TEAMMATE_WITH relationship, so the same graph problem maps much more "
            "directly to the storage model."
        ),
        "Q6_GRAPH_TEAMMATE_NEIGHBORHOOD_REACH": (
            "PostgreSQL reads precomputed teammate edges, but it still has to recursively expand "
            "simple paths, prevent branch-local cycles, and deduplicate the nearest distance for "
            "each reached driver. Neo4j stores the same teammate network as adjacent graph "
            "relationships, so shortest-distance expansion to many targets maps more directly to "
            "the graph storage model."
        ),
        "Q7_GRAPH_CONSTRUCTOR_DRIVER_BRIDGE": (
            "PostgreSQL must recursively alternate between constructor and driver states while "
            "tracking visited path keys. The query is semantically graph-shaped even though it is "
            "expressed as relational recursion."
        ),
    }
    return explanations.get(query_name, "The query exceeded the configured 10-minute statement timeout.")


def render_summary(postgres: dict[str, Any], neo4j: dict[str, Any], postgres_path: Path, neo4j_path: Path) -> str:
    pg_results = result_map(postgres)
    neo_results = result_map(neo4j)
    query_names = list(pg_results)

    lines = [
        "# Database Benchmark Comparison",
        "",
        f"Created at: `{datetime.now().isoformat(timespec='seconds')}`",
        f"PostgreSQL source report: `{postgres_path}`",
        f"Neo4j source report: `{neo4j_path}`",
        "",
        "PostgreSQL uses `EXPLAIN ANALYZE` for completed queries. Neo4j uses `PROFILE`, which is the corresponding execution-plan analysis tool for Cypher queries.",
        "",
        "The PostgreSQL statement timeout is 600 seconds. If a query times out, the report records `>600` and skips `EXPLAIN ANALYZE` because it would execute the same timed-out workload again.",
        "",
        "## Summary",
        "",
        "| Query | PostgreSQL Python time (s) | PostgreSQL rows | Neo4j Python time (s) | Neo4j rows |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]

    for query_name in query_names:
        pg_result = pg_results[query_name]
        neo_result = neo_results.get(query_name)
        if neo_result is None:
            lines.append(f"| `{query_name}` | {format_time(pg_result)} | {format_rows(pg_result)} | missing | missing |")
            continue
        lines.append(
            f"| `{query_name}` | {format_time(pg_result)} | {format_rows(pg_result)} | "
            f"{format_time(neo_result)} | {format_rows(neo_result)} |"
        )

    incomplete = [name for name, result in pg_results.items() if result.get("timed_out") or result.get("failed")]
    lines.extend(["", "## Timeout And Failure Notes", ""])
    if incomplete:
        for query_name in incomplete:
            lines.extend(
                [
                    f"### {query_name}",
                    "",
                    timeout_explanation(query_name),
                    "",
                ]
            )
    else:
        lines.append("No PostgreSQL queries timed out or failed.")

    lines.extend(["", "## Query Details", ""])
    for query_name in query_names:
        pg_result = pg_results[query_name]
        neo_result = neo_results.get(query_name)
        lines.extend(
            [
                f"### {query_name}",
                "",
                f"- PostgreSQL time: `{format_time(pg_result)}` seconds; rows: `{format_rows(pg_result)}`.",
            ]
        )
        if neo_result:
            lines.append(f"- Neo4j time: `{format_time(neo_result)}` seconds; rows: `{format_rows(neo_result)}`.")
        if pg_result.get("timed_out") or pg_result.get("failed"):
            lines.append(f"- PostgreSQL incomplete reason: {timeout_explanation(query_name)}")
        lines.append("")

        lines.extend(
            [
                "#### PostgreSQL EXPLAIN ANALYZE",
                "",
                "```text",
            ]
        )
        if pg_result.get("explain_analyze"):
            lines.extend(pg_result["explain_analyze"])
        else:
            lines.append(
                "Skipped because the PostgreSQL query did not complete. "
                "Running EXPLAIN ANALYZE would execute the same timed-out or failed workload again."
            )
        lines.extend(["```", ""])

        lines.extend(
            [
                "#### Neo4j PROFILE",
                "",
                "```json",
            ]
        )
        if neo_result and neo_result.get("profile"):
            lines.append(json.dumps(neo_result["profile"], indent=2, ensure_ascii=False, default=str))
        elif neo_result:
            lines.append("Skipped because the Neo4j query did not complete.")
        else:
            lines.append("No matching Neo4j result was found.")
        lines.extend(["```", ""])

    return "\n".join(lines).rstrip() + "\n"


def main() -> None:
    postgres_path = latest_json("postgres_benchmark")
    neo4j_path = latest_json("neo4j_benchmark")
    postgres = load_json(postgres_path)
    neo4j = load_json(neo4j_path)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = BENCHMARK_DIR / f"database_benchmark_comparison_{timestamp}.md"
    output_path.write_text(render_summary(postgres, neo4j, postgres_path, neo4j_path), encoding="utf-8")
    print(f"Comparison report written to {output_path}")


if __name__ == "__main__":
    main()
