from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass
from datetime import date, datetime, time as datetime_time
from decimal import Decimal
from pathlib import Path
from typing import Any

import psycopg
from psycopg.rows import dict_row


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_QUERY_FILE = PROJECT_ROOT / "sql" / "sql_queries.sql"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "benchmark_results"

QUERY_PATTERN = re.compile(
    r"--\s*Query\s+(?P<name>[A-Za-z0-9_]+)\s*\n"
    r"(?P<body>.*?)(?=\n--\s*Query\s+[A-Za-z0-9_]+\s*\n|\Z)",
    re.DOTALL,
)
QUERY_NAME_PATTERN = re.compile(r"^Q(?P<number>\d+)_")
STATEMENT_TIMEOUT_MS = int(os.getenv("DB_STATEMENT_TIMEOUT_MS", "120000"))


@dataclass(frozen=True)
class BenchmarkQuery:
    name: str
    sql: str


def connect() -> psycopg.Connection:
    return psycopg.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=int(os.getenv("DB_PORT", "5432")),
        dbname=os.getenv("DB_NAME", "formula1"),
        user=os.getenv("DB_USER", "f1_user"),
        password=os.getenv("DB_PASSWORD", "f1_password"),
        row_factory=dict_row,
    )


def read_queries(query_file: Path) -> list[BenchmarkQuery]:
    content = query_file.read_text(encoding="utf-8")
    queries = []

    for match in QUERY_PATTERN.finditer(content):
        name = match.group("name").strip()
        body = strip_sql_comments(match.group("body")).strip()
        if body.endswith(";"):
            body = body[:-1].strip()

        if body:
            queries.append(BenchmarkQuery(name=name, sql=body))

    if not queries:
        raise ValueError(f"No benchmark queries found in {query_file}")

    validate_query_numbering(queries)
    return queries


def validate_query_numbering(queries: list[BenchmarkQuery]) -> None:
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


def strip_sql_comments(sql_text: str) -> str:
    lines = []
    for line in sql_text.splitlines():
        if line.strip().startswith("--"):
            continue
        lines.append(line)
    return "\n".join(lines)


def run_query(cursor: psycopg.Cursor, query: BenchmarkQuery) -> dict[str, Any]:
    start = time.perf_counter()
    cursor.execute(query.sql)
    rows = cursor.fetchall()
    elapsed_seconds = time.perf_counter() - start

    return {
        "elapsed_seconds": elapsed_seconds,
        "row_count": len(rows),
        "sample_rows": rows[:10],
    }


def run_explain_analyze(cursor: psycopg.Cursor, query: BenchmarkQuery) -> list[str]:
    cursor.execute("EXPLAIN (ANALYZE, BUFFERS, VERBOSE, FORMAT TEXT) " + query.sql)
    return [row["QUERY PLAN"] for row in cursor.fetchall()]


def benchmark_queries(query_file: Path, output_dir: Path) -> tuple[Path, Path]:
    queries = read_queries(query_file)
    output_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = output_dir / f"postgres_benchmark_{timestamp}.json"
    markdown_path = output_dir / f"postgres_benchmark_{timestamp}.md"

    results = []

    with connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT set_config('statement_timeout', %s, false)", (str(STATEMENT_TIMEOUT_MS),))
            for query in queries:
                print(f"Running {query.name}")
                execution = run_query(cursor, query)
                explain_plan = run_explain_analyze(cursor, query)

                result = {
                    "name": query.name,
                    "sql": query.sql,
                    "elapsed_seconds": execution["elapsed_seconds"],
                    "row_count": execution["row_count"],
                    "sample_rows": execution["sample_rows"],
                    "explain_analyze": explain_plan,
                }
                results.append(result)

                print(
                    f"  rows={execution['row_count']} "
                    f"python_time={execution['elapsed_seconds']:.6f}s"
                )

    payload = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "database": {
            "host": os.getenv("DB_HOST", "localhost"),
            "port": int(os.getenv("DB_PORT", "5432")),
            "name": os.getenv("DB_NAME", "formula1"),
            "user": os.getenv("DB_USER", "f1_user"),
        },
        "query_file": str(query_file),
        "results": results,
    }

    json_path.write_text(json.dumps(payload, indent=2, default=to_json, ensure_ascii=False), encoding="utf-8")
    markdown_path.write_text(render_markdown_report(payload), encoding="utf-8")

    return json_path, markdown_path


def to_json(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (date, datetime, datetime_time)):
        return value.isoformat()
    return str(value)


def render_markdown_report(payload: dict[str, Any]) -> str:
    lines = [
        "# PostgreSQL Benchmark Report",
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
        lines.append(
            f"| `{result['name']}` | {result['elapsed_seconds']:.6f} | {result['row_count']} |"
        )

    for result in payload["results"]:
        lines.extend(
            [
                "",
                f"## {result['name']}",
                "",
                "### SQL",
                "",
                "```sql",
                result["sql"],
                "```",
                "",
                "### Sample Rows",
                "",
                "```json",
                json.dumps(result["sample_rows"], indent=2, default=to_json, ensure_ascii=False),
                "```",
                "",
                "### EXPLAIN ANALYZE",
                "",
                "```text",
                *result["explain_analyze"],
                "```",
            ]
        )

    return "\n".join(lines) + "\n"


def main() -> None:
    query_file = Path(os.getenv("QUERY_FILE", DEFAULT_QUERY_FILE))
    output_dir = Path(os.getenv("BENCHMARK_OUTPUT_DIR", DEFAULT_OUTPUT_DIR))

    json_path, markdown_path = benchmark_queries(query_file, output_dir)

    print(f"JSON results written to {json_path}")
    print(f"Markdown report written to {markdown_path}")


if __name__ == "__main__":
    main()
