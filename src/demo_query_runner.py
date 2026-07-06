from __future__ import annotations

import base64
import json
import os
import re
import time
from dataclasses import dataclass
from datetime import date, datetime, time as datetime_time
from decimal import Decimal
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen

import psycopg
from psycopg import errors
from psycopg.rows import dict_row


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SQL_QUERY_FILE = PROJECT_ROOT / "sql" / "sql_queries.sql"
CYPHER_QUERY_FILE = PROJECT_ROOT / "neo4j" / "neo4j_queries.cypher"

SQL_QUERY_PATTERN = re.compile(
    r"--\s*Query\s+(?P<name>[A-Za-z0-9_]+)\s*\n"
    r"(?P<body>.*?)(?=\n--\s*Query\s+[A-Za-z0-9_]+\s*\n|\Z)",
    re.DOTALL,
)
CYPHER_QUERY_PATTERN = re.compile(
    r"//\s*Query\s+(?P<name>[A-Za-z0-9_]+)\s*\n"
    r"(?P<body>.*?)(?=\n//\s*Query\s+[A-Za-z0-9_]+\s*\n|\Z)",
    re.DOTALL,
)
QUERY_NUMBER_PATTERN = re.compile(r"^Q(?P<number>\d+)_")

POSTGRES_TIMEOUT_MS = int(os.getenv("DEMO_DB_STATEMENT_TIMEOUT_MS", "120000"))
NEO4J_TIMEOUT_SECONDS = int(os.getenv("DEMO_NEO4J_TIMEOUT_SECONDS", "180"))
SAMPLE_ROW_LIMIT = int(os.getenv("DEMO_SAMPLE_ROW_LIMIT", "5"))


@dataclass(frozen=True)
class DemoQuery:
    name: str
    objective: str
    statement: str


@dataclass(frozen=True)
class DemoResult:
    elapsed_seconds: float
    row_count: int | None
    sample_rows: list[Any]
    timed_out: bool = False
    failed: bool = False
    error: str | None = None


def strip_sql_comments(text: str) -> str:
    return "\n".join(line for line in text.splitlines() if not line.strip().startswith("--"))


def strip_cypher_comments(text: str) -> str:
    return "\n".join(line for line in text.splitlines() if not line.strip().startswith("//"))


def extract_objective(body: str, comment_prefix: str) -> str:
    for line in body.splitlines():
        line = line.strip()
        expected_prefix = f"{comment_prefix} Objective:"
        if line.startswith(expected_prefix):
            return line.removeprefix(expected_prefix).strip()
    return "No objective comment found."


def read_sql_queries() -> dict[str, DemoQuery]:
    content = SQL_QUERY_FILE.read_text(encoding="utf-8")
    queries = {}
    for match in SQL_QUERY_PATTERN.finditer(content):
        name = match.group("name").strip()
        body = match.group("body")
        statement = strip_sql_comments(body).strip()
        if statement.endswith(";"):
            statement = statement[:-1].strip()
        queries[name] = DemoQuery(
            name=name,
            objective=extract_objective(body, "--"),
            statement=statement,
        )
    return queries


def read_cypher_queries() -> dict[str, DemoQuery]:
    content = CYPHER_QUERY_FILE.read_text(encoding="utf-8")
    queries = {}
    for match in CYPHER_QUERY_PATTERN.finditer(content):
        name = match.group("name").strip()
        body = match.group("body")
        statement = strip_cypher_comments(body).strip()
        if statement.endswith(";"):
            statement = statement[:-1].strip()
        queries[name] = DemoQuery(
            name=name,
            objective=extract_objective(body, "//"),
            statement=statement,
        )
    return queries


def query_number(name: str) -> int:
    match = QUERY_NUMBER_PATTERN.match(name)
    if not match:
        raise ValueError(f"Invalid query name: {name}")
    return int(match.group("number"))


def read_paired_queries() -> list[tuple[DemoQuery, DemoQuery]]:
    sql_queries = read_sql_queries()
    cypher_queries = read_cypher_queries()
    if set(sql_queries) != set(cypher_queries):
        missing_in_cypher = sorted(set(sql_queries) - set(cypher_queries))
        missing_in_sql = sorted(set(cypher_queries) - set(sql_queries))
        raise ValueError(
            "SQL and Cypher query files are not aligned. "
            f"Missing in Cypher: {missing_in_cypher}; missing in SQL: {missing_in_sql}"
        )
    return [(sql_queries[name], cypher_queries[name]) for name in sorted(sql_queries, key=query_number)]


def postgres_connection() -> psycopg.Connection:
    return psycopg.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=int(os.getenv("DB_PORT", "5432")),
        dbname=os.getenv("DB_NAME", "formula1"),
        user=os.getenv("DB_USER", "f1_user"),
        password=os.getenv("DB_PASSWORD", "f1_password"),
        row_factory=dict_row,
    )


def run_postgres(query: DemoQuery) -> DemoResult:
    start = time.perf_counter()
    try:
        with postgres_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT set_config('statement_timeout', %s, false)", (str(POSTGRES_TIMEOUT_MS),))
                cursor.execute(query.statement)
                rows = cursor.fetchall()
    except errors.QueryCanceled as exc:
        return DemoResult(
            elapsed_seconds=time.perf_counter() - start,
            row_count=None,
            sample_rows=[],
            timed_out=True,
            error=str(exc),
        )
    except Exception as exc:
        return DemoResult(
            elapsed_seconds=time.perf_counter() - start,
            row_count=None,
            sample_rows=[],
            failed=True,
            error=str(exc),
        )
    return DemoResult(
        elapsed_seconds=time.perf_counter() - start,
        row_count=len(rows),
        sample_rows=rows[:SAMPLE_ROW_LIMIT],
    )


def neo4j_headers() -> dict[str, str]:
    user = os.getenv("NEO4J_USER", "neo4j")
    password = os.getenv("NEO4J_PASSWORD", "f1_password")
    token = base64.b64encode(f"{user}:{password}".encode("utf-8")).decode("ascii")
    return {
        "Authorization": f"Basic {token}",
        "Content-Type": "application/json; charset=utf-8",
    }


def run_cypher(statement: str) -> dict[str, Any]:
    url = os.getenv("NEO4J_HTTP_URL", "http://localhost:7474/db/neo4j/tx/commit")
    payload = json.dumps({"statements": [{"statement": statement}]}).encode("utf-8")
    request = Request(url, data=payload, headers=neo4j_headers(), method="POST")
    with urlopen(request, timeout=NEO4J_TIMEOUT_SECONDS + 30) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if payload.get("errors"):
        raise RuntimeError(payload["errors"])
    return payload["results"][0]


def run_neo4j(query: DemoQuery) -> DemoResult:
    start = time.perf_counter()
    try:
        result = run_cypher(query.statement)
    except TimeoutError as exc:
        return DemoResult(
            elapsed_seconds=time.perf_counter() - start,
            row_count=None,
            sample_rows=[],
            timed_out=True,
            error=str(exc),
        )
    except URLError as exc:
        if isinstance(exc.reason, TimeoutError):
            return DemoResult(
                elapsed_seconds=time.perf_counter() - start,
                row_count=None,
                sample_rows=[],
                timed_out=True,
                error=str(exc),
            )
        return DemoResult(
            elapsed_seconds=time.perf_counter() - start,
            row_count=None,
            sample_rows=[],
            failed=True,
            error=str(exc),
        )
    except Exception as exc:
        return DemoResult(
            elapsed_seconds=time.perf_counter() - start,
            row_count=None,
            sample_rows=[],
            failed=True,
            error=str(exc),
        )

    columns = result["columns"]
    rows = [dict(zip(columns, record["row"], strict=True)) for record in result["data"]]
    return DemoResult(
        elapsed_seconds=time.perf_counter() - start,
        row_count=len(rows),
        sample_rows=rows[:SAMPLE_ROW_LIMIT],
    )


def to_json(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (date, datetime, datetime_time)):
        return value.isoformat()
    return str(value)


def print_result(database_name: str, result: DemoResult) -> None:
    print(f"\n{database_name}")
    print("-" * len(database_name))
    if result.timed_out:
        print(f"Status: timed out after {result.elapsed_seconds:.6f}s")
        print(f"Error: {result.error}")
        return
    if result.failed:
        print(f"Status: failed after {result.elapsed_seconds:.6f}s")
        print(f"Error: {result.error}")
        return
    print(f"Rows returned: {result.row_count}")
    print(f"Python wall-clock time: {result.elapsed_seconds:.6f}s")
    print(f"Sample rows (first {len(result.sample_rows)}):")
    print(json.dumps(result.sample_rows, indent=2, ensure_ascii=False, default=to_json))


def print_menu(paired_queries: list[tuple[DemoQuery, DemoQuery]]) -> None:
    print("\nAvailable demo queries")
    print("======================")
    for index, (sql_query, _) in enumerate(paired_queries, start=1):
        print(f"{index}. {sql_query.name}")
        print(f"   {sql_query.objective}")
    print("q. Quit")
    print(
        f"\nTimeouts: PostgreSQL {POSTGRES_TIMEOUT_MS / 1000:.0f}s, "
        f"Neo4j {NEO4J_TIMEOUT_SECONDS}s. "
        "Use DEMO_DB_STATEMENT_TIMEOUT_MS or DEMO_NEO4J_TIMEOUT_SECONDS to change them."
    )


def choose_query(paired_queries: list[tuple[DemoQuery, DemoQuery]]) -> tuple[DemoQuery, DemoQuery] | None:
    while True:
        choice = input("\nSelect a query number, or q to quit: ").strip().lower()
        if choice in {"q", "quit", "exit"}:
            return None
        if not choice.isdigit():
            print("Please enter a number from the menu.")
            continue
        index = int(choice)
        if 1 <= index <= len(paired_queries):
            return paired_queries[index - 1]
        print(f"Please choose a number between 1 and {len(paired_queries)}.")


def main() -> None:
    paired_queries = read_paired_queries()
    print_menu(paired_queries)

    while True:
        selected = choose_query(paired_queries)
        if selected is None:
            print("Demo runner stopped.")
            return

        sql_query, cypher_query = selected
        print(f"\nRunning {sql_query.name}")
        print(f"Objective: {sql_query.objective}")

        postgres_result = run_postgres(sql_query)
        neo4j_result = run_neo4j(cypher_query)

        print_result("PostgreSQL", postgres_result)
        print_result("Neo4j", neo4j_result)

        if not postgres_result.failed and not postgres_result.timed_out and not neo4j_result.failed and not neo4j_result.timed_out:
            if postgres_result.row_count == neo4j_result.row_count:
                print("\nRow-count check: OK")
            else:
                print(
                    "\nRow-count check: different row counts "
                    f"(PostgreSQL={postgres_result.row_count}, Neo4j={neo4j_result.row_count})"
                )


if __name__ == "__main__":
    main()
