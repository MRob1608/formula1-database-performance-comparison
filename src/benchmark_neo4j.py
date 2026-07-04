from __future__ import annotations

import base64
import json
import os
import re
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_QUERY_FILE = PROJECT_ROOT / "neo4j" / "neo4j_queries.cypher"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "benchmark_results"
NEO4J_HTTP_URL = os.getenv("NEO4J_HTTP_URL", "http://localhost:7474/db/neo4j/tx/commit")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "f1_password")
QUERY_TIMEOUT_SECONDS = int(os.getenv("NEO4J_QUERY_TIMEOUT_SECONDS", "600"))

QUERY_PATTERN = re.compile(
    r"//\s*Query\s+(?P<name>[A-Za-z0-9_]+)\s*\n"
    r"(?P<body>.*?)(?=\n//\s*Query\s+[A-Za-z0-9_]+\s*\n|\Z)",
    re.DOTALL,
)
QUERY_NAME_PATTERN = re.compile(r"^Q(?P<number>\d+)_")


@dataclass(frozen=True)
class Neo4jQuery:
    name: str
    cypher: str


def read_queries(query_file: Path) -> list[Neo4jQuery]:
    content = query_file.read_text(encoding="utf-8")
    queries = []

    for match in QUERY_PATTERN.finditer(content):
        name = match.group("name").strip()
        body = strip_cypher_comments(match.group("body")).strip()
        if body.endswith(";"):
            body = body[:-1].strip()
        if body:
            queries.append(Neo4jQuery(name=name, cypher=body))

    if not queries:
        raise ValueError(f"No Neo4j benchmark queries found in {query_file}")

    validate_query_numbering(queries)
    return queries


def validate_query_numbering(queries: list[Neo4jQuery]) -> None:
    query_numbers = []
    for query in queries:
        match = QUERY_NAME_PATTERN.match(query.name)
        if not match:
            raise ValueError(f"Query name must start with Q<number>_: {query.name}")
        query_numbers.append(int(match.group("number")))

    expected_numbers = list(range(1, len(queries) + 1))
    if query_numbers != expected_numbers:
        raise ValueError(
            f"Query numbers must be consecutive. Expected {expected_numbers}, got {query_numbers}."
        )


def strip_cypher_comments(cypher_text: str) -> str:
    lines = []
    for line in cypher_text.splitlines():
        if line.strip().startswith("//"):
            continue
        lines.append(line)
    return "\n".join(lines)


def request_headers() -> dict[str, str]:
    token = base64.b64encode(f"{NEO4J_USER}:{NEO4J_PASSWORD}".encode("utf-8")).decode("ascii")
    return {
        "Authorization": f"Basic {token}",
        "Content-Type": "application/json; charset=utf-8",
    }


def run_cypher(statement: str) -> dict[str, Any]:
    payload = json.dumps({"statements": [{"statement": statement}]}).encode("utf-8")
    request = Request(NEO4J_HTTP_URL, data=payload, headers=request_headers(), method="POST")
    with urlopen(request, timeout=QUERY_TIMEOUT_SECONDS + 30) as response:
        result = json.loads(response.read().decode("utf-8"))

    if result.get("errors"):
        raise RuntimeError(result["errors"])

    return result["results"][0]


def run_query(query: Neo4jQuery) -> dict[str, Any]:
    start = time.perf_counter()
    try:
        result = run_cypher(query.cypher)
    except TimeoutError as exc:
        return timeout_result(start, exc)
    except URLError as exc:
        if isinstance(exc.reason, TimeoutError):
            return timeout_result(start, exc)
        raise

    elapsed_seconds = time.perf_counter() - start
    rows = [record["row"] for record in result["data"]]
    return {
        "elapsed_seconds": elapsed_seconds,
        "timed_out": False,
        "error": None,
        "row_count": len(rows),
        "sample_rows": rows[:10],
    }


def run_profile(query: Neo4jQuery) -> dict[str, Any] | None:
    try:
        result = run_cypher("PROFILE " + query.cypher)
    except TimeoutError:
        return None
    except URLError as exc:
        if isinstance(exc.reason, TimeoutError):
            return None
        raise

    return result.get("plan")


def timeout_result(start: float, exc: BaseException) -> dict[str, Any]:
    elapsed_seconds = time.perf_counter() - start
    return {
        "elapsed_seconds": elapsed_seconds,
        "timed_out": True,
        "error": str(exc),
        "row_count": None,
        "sample_rows": [],
    }


def benchmark_queries(query_file: Path, output_dir: Path) -> tuple[Path, Path]:
    queries = read_queries(query_file)
    output_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = output_dir / f"neo4j_benchmark_{timestamp}.json"
    markdown_path = output_dir / f"neo4j_benchmark_{timestamp}.md"

    results = []
    for query in queries:
        print(f"Running {query.name}")
        execution = run_query(query)
        profile = None if execution["timed_out"] else run_profile(query)

        result = {
            "name": query.name,
            "cypher": query.cypher,
            "elapsed_seconds": execution["elapsed_seconds"],
            "timed_out": execution["timed_out"],
            "error": execution["error"],
            "row_count": execution["row_count"],
            "sample_rows": execution["sample_rows"],
            "profile": profile,
        }
        results.append(result)

        if execution["timed_out"]:
            print(f"  timed_out after {execution['elapsed_seconds']:.6f}s")
        else:
            print(f"  rows={execution['row_count']} python_time={execution['elapsed_seconds']:.6f}s")

    payload = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "database": {
            "url": NEO4J_HTTP_URL,
            "user": NEO4J_USER,
        },
        "query_file": str(query_file),
        "results": results,
    }

    json_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    markdown_path.write_text(render_markdown_report(payload), encoding="utf-8")
    return json_path, markdown_path


def render_markdown_report(payload: dict[str, Any]) -> str:
    lines = [
        "# Neo4j Benchmark Report",
        "",
        f"Created at: `{payload['created_at']}`",
        f"Query file: `{payload['query_file']}`",
        "",
        "## Summary",
        "",
        "| Query | Python total time (s) | Rows returned |",
        "| --- | ---: | ---: |",
    ]

    for result in payload["results"]:
        elapsed = f">{QUERY_TIMEOUT_SECONDS}" if result.get("timed_out") else f"{result['elapsed_seconds']:.6f}"
        row_count = "timeout" if result.get("timed_out") else result["row_count"]
        lines.append(f"| `{result['name']}` | {elapsed} | {row_count} |")

    for result in payload["results"]:
        lines.extend(
            [
                "",
                f"## {result['name']}",
                "",
                "### Cypher",
                "",
                "```cypher",
                result["cypher"],
                "```",
                "",
                "### Sample Rows",
                "",
                "```json",
                json.dumps(result["sample_rows"], indent=2, ensure_ascii=False, default=str),
                "```",
                "",
                "### PROFILE",
                "",
                "```json",
                json.dumps(result["profile"], indent=2, ensure_ascii=False, default=str)
                if result["profile"]
                else f"Skipped because the query timed out: {result.get('error')}",
                "```",
            ]
        )

    return "\n".join(lines) + "\n"


def main() -> None:
    query_file = Path(os.getenv("NEO4J_QUERY_FILE", DEFAULT_QUERY_FILE))
    output_dir = Path(os.getenv("BENCHMARK_OUTPUT_DIR", DEFAULT_OUTPUT_DIR))
    json_path, markdown_path = benchmark_queries(query_file, output_dir)
    print(f"JSON results written to {json_path}")
    print(f"Markdown report written to {markdown_path}")


if __name__ == "__main__":
    main()
