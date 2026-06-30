from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RAW_DATA_DIR = PROJECT_ROOT / "data" / "raw"
PROCESSED_DATA_DIR = PROJECT_ROOT / "data" / "processed"
REPORT_PATH = PROJECT_ROOT / "Reports" / "data_quality_report.md"

MISSING_MARKERS = {"", r"\N"}


@dataclass(frozen=True)
class ForeignKey:
    table: str
    columns: tuple[str, ...]
    parent_table: str
    parent_columns: tuple[str, ...]


PRIMARY_KEYS: dict[str, tuple[str, ...]] = {
    "circuits": ("circuitId",),
    "constructors": ("constructorId",),
    "constructor_results": ("constructorResultsId",),
    "constructor_standings": ("constructorStandingsId",),
    "drivers": ("driverId",),
    "driver_standings": ("driverStandingsId",),
    "lap_times": ("raceId", "driverId", "lap"),
    "pit_stops": ("raceId", "driverId", "stop"),
    "qualifying": ("qualifyId",),
    "races": ("raceId",),
    "results": ("resultId",),
    "seasons": ("year",),
    "sprint_results": ("resultId",),
    "status": ("statusId",),
}

FOREIGN_KEYS = [
    ForeignKey("constructor_results", ("raceId",), "races", ("raceId",)),
    ForeignKey("constructor_results", ("constructorId",), "constructors", ("constructorId",)),
    ForeignKey("constructor_standings", ("raceId",), "races", ("raceId",)),
    ForeignKey("constructor_standings", ("constructorId",), "constructors", ("constructorId",)),
    ForeignKey("driver_standings", ("raceId",), "races", ("raceId",)),
    ForeignKey("driver_standings", ("driverId",), "drivers", ("driverId",)),
    ForeignKey("lap_times", ("raceId",), "races", ("raceId",)),
    ForeignKey("lap_times", ("driverId",), "drivers", ("driverId",)),
    ForeignKey("pit_stops", ("raceId",), "races", ("raceId",)),
    ForeignKey("pit_stops", ("driverId",), "drivers", ("driverId",)),
    ForeignKey("qualifying", ("raceId",), "races", ("raceId",)),
    ForeignKey("qualifying", ("driverId",), "drivers", ("driverId",)),
    ForeignKey("qualifying", ("constructorId",), "constructors", ("constructorId",)),
    ForeignKey("races", ("circuitId",), "circuits", ("circuitId",)),
    ForeignKey("races", ("year",), "seasons", ("year",)),
    ForeignKey("results", ("raceId",), "races", ("raceId",)),
    ForeignKey("results", ("driverId",), "drivers", ("driverId",)),
    ForeignKey("results", ("constructorId",), "constructors", ("constructorId",)),
    ForeignKey("results", ("statusId",), "status", ("statusId",)),
    ForeignKey("sprint_results", ("raceId",), "races", ("raceId",)),
    ForeignKey("sprint_results", ("driverId",), "drivers", ("driverId",)),
    ForeignKey("sprint_results", ("constructorId",), "constructors", ("constructorId",)),
    ForeignKey("sprint_results", ("statusId",), "status", ("statusId",)),
]

INTEGER_COLUMNS = {
    "circuitId",
    "constructorId",
    "constructorResultsId",
    "constructorStandingsId",
    "driverId",
    "driverStandingsId",
    "qualifyId",
    "raceId",
    "resultId",
    "statusId",
    "year",
    "round",
    "number",
    "position",
    "positionOrder",
    "grid",
    "laps",
    "lap",
    "stop",
    "wins",
    "milliseconds",
    "fastestLap",
    "rank",
    "alt",
}

FLOAT_COLUMNS = {
    "lat",
    "lng",
    "points",
    "fastestLapSpeed",
}

DATE_COLUMNS = {"dob", "date", "fp1_date", "fp2_date", "fp3_date", "quali_date", "sprint_date"}
TIME_OF_DAY_COLUMNS = {
    ("races", "time"),
    ("races", "fp1_time"),
    ("races", "fp2_time"),
    ("races", "fp3_time"),
    ("races", "quali_time"),
    ("races", "sprint_time"),
    ("pit_stops", "time"),
}
LAP_DURATION_COLUMNS = {
    ("lap_times", "time"),
    ("qualifying", "q1"),
    ("qualifying", "q2"),
    ("qualifying", "q3"),
    ("results", "fastestLapTime"),
    ("sprint_results", "fastestLapTime"),
}
GAP_OR_ELAPSED_TIME_COLUMNS = {
    ("results", "time"),
    ("sprint_results", "time"),
}
PIT_STOP_DURATION_COLUMNS = {("pit_stops", "duration")}

LAP_DURATION_PATTERN = re.compile(r"^(\d+:\d{2}\.\d{3}|\d+:\d{2}:\d{2}\.\d{3})$")
GAP_OR_ELAPSED_PATTERN = re.compile(r"^(\+?\d+(?::\d{2}){0,2}\.\d{1,3}|\d+:\d{2}:\d{2}\.\d{3})$")
PIT_STOP_DURATION_PATTERN = re.compile(r"^(\d+\.\d{3}|\d+:\d{2}\.\d{3})$")

NON_NEGATIVE_COLUMNS = {
    "points",
    "wins",
    "laps",
    "lap",
    "stop",
    "milliseconds",
    "fastestLap",
    "rank",
    "round",
    "position",
    "positionOrder",
    "number",
    "grid",
}


def read_raw_csvs(raw_data_dir: Path = RAW_DATA_DIR) -> dict[str, pd.DataFrame]:
    return {
        path.stem: pd.read_csv(path, dtype="string", keep_default_na=False)
        for path in sorted(raw_data_dir.glob("*.csv"))
    }


def as_missing_mask(series: pd.Series) -> pd.Series:
    return series.astype("string").str.strip().isin(MISSING_MARKERS)


def normalized_non_missing_frame(df: pd.DataFrame) -> pd.DataFrame:
    normalized = df.copy()
    for column in normalized.columns:
        mask = as_missing_mask(normalized[column])
        normalized.loc[mask, column] = pd.NA
    return normalized


def markdown_table(headers: Iterable[str], rows: Iterable[Iterable[object]]) -> str:
    headers = list(headers)
    row_values = [[format_cell(value) for value in row] for row in rows]
    if not row_values:
        return "_No items found._"

    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in row_values:
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)


def format_cell(value: object) -> str:
    if pd.isna(value):
        return ""
    return str(value).replace("|", "\\|")


def missing_value_rows(tables: dict[str, pd.DataFrame]) -> list[tuple[str, str, int, float]]:
    rows = []
    for table_name, df in tables.items():
        for column in df.columns:
            count = int(as_missing_mask(df[column]).sum())
            if count:
                rows.append((table_name, column, count, round(count / len(df) * 100, 2)))
    return sorted(rows, key=lambda row: (-row[2], row[0], row[1]))


def duplicate_rows(tables: dict[str, pd.DataFrame]) -> list[tuple[str, str, int]]:
    rows = []
    for table_name, key_columns in PRIMARY_KEYS.items():
        df = normalized_non_missing_frame(tables[table_name])
        duplicate_count = int(df.duplicated(subset=list(key_columns), keep=False).sum())
        missing_key_rows = int(df[list(key_columns)].isna().any(axis=1).sum())
        rows.append((table_name, ", ".join(key_columns), duplicate_count + missing_key_rows))
    return rows


def full_duplicate_rows(tables: dict[str, pd.DataFrame]) -> list[tuple[str, int]]:
    rows = []
    for table_name, df in tables.items():
        normalized = normalized_non_missing_frame(df)
        rows.append((table_name, int(normalized.duplicated(keep=False).sum())))
    return rows


def foreign_key_rows(tables: dict[str, pd.DataFrame]) -> list[tuple[str, str, str, int]]:
    rows = []
    normalized_tables = {name: normalized_non_missing_frame(df) for name, df in tables.items()}

    for foreign_key in FOREIGN_KEYS:
        child = normalized_tables[foreign_key.table]
        parent = normalized_tables[foreign_key.parent_table]
        child_columns = list(foreign_key.columns)
        parent_columns = list(foreign_key.parent_columns)

        child_keys = child[child_columns].dropna().drop_duplicates()
        parent_keys = parent[parent_columns].dropna().drop_duplicates()
        merged = child_keys.merge(
            parent_keys,
            left_on=child_columns,
            right_on=parent_columns,
            how="left",
            indicator=True,
        )
        missing = int((merged["_merge"] == "left_only").sum())
        rows.append(
            (
                foreign_key.table,
                ", ".join(child_columns),
                f"{foreign_key.parent_table}({', '.join(parent_columns)})",
                missing,
            )
        )
    return rows


def type_issue_rows(tables: dict[str, pd.DataFrame]) -> list[tuple[str, str, str, int]]:
    rows = []

    for table_name, raw_df in tables.items():
        df = normalized_non_missing_frame(raw_df)
        for column in df.columns:
            series = df[column].dropna().astype("string").str.strip()
            if series.empty:
                continue

            if column in INTEGER_COLUMNS:
                parsed = pd.to_numeric(series, errors="coerce")
                integer_mask = parsed.notna() & (parsed % 1 == 0)
                invalid = int((~integer_mask).sum())
                if invalid:
                    rows.append((table_name, column, "not_integer", invalid))
            elif column in FLOAT_COLUMNS:
                parsed = pd.to_numeric(series, errors="coerce")
                invalid = int(parsed.isna().sum())
                if invalid:
                    rows.append((table_name, column, "not_number", invalid))

            if column in DATE_COLUMNS:
                parsed_dates = pd.to_datetime(series, format="%Y-%m-%d", errors="coerce")
                invalid_dates = int(parsed_dates.isna().sum())
                if invalid_dates:
                    rows.append((table_name, column, "invalid_date", invalid_dates))

            if (table_name, column) in TIME_OF_DAY_COLUMNS:
                parsed_times = pd.to_datetime(series, format="%H:%M:%S", errors="coerce")
                invalid_times = int(parsed_times.isna().sum())
                if invalid_times:
                    rows.append((table_name, column, "invalid_time", invalid_times))

            if (table_name, column) in LAP_DURATION_COLUMNS:
                invalid_lap_durations = int((~series.str.match(LAP_DURATION_PATTERN)).sum())
                if invalid_lap_durations:
                    rows.append((table_name, column, "invalid_lap_duration", invalid_lap_durations))

            if (table_name, column) in GAP_OR_ELAPSED_TIME_COLUMNS:
                invalid_gap_or_elapsed = int((~series.str.match(GAP_OR_ELAPSED_PATTERN)).sum())
                if invalid_gap_or_elapsed:
                    rows.append((table_name, column, "invalid_gap_or_elapsed_time", invalid_gap_or_elapsed))

            if (table_name, column) in PIT_STOP_DURATION_COLUMNS:
                invalid_pit_stop_durations = int((~series.str.match(PIT_STOP_DURATION_PATTERN)).sum())
                if invalid_pit_stop_durations:
                    rows.append((table_name, column, "invalid_pit_stop_duration", invalid_pit_stop_durations))

            if column in NON_NEGATIVE_COLUMNS:
                parsed_numbers = pd.to_numeric(series, errors="coerce")
                negative_count = int((parsed_numbers < 0).sum())
                if negative_count:
                    rows.append((table_name, column, "negative_value", negative_count))

        if {"lat", "lng"}.issubset(df.columns):
            lat = pd.to_numeric(df["lat"], errors="coerce")
            lng = pd.to_numeric(df["lng"], errors="coerce")
            invalid_lat = int(((lat < -90) | (lat > 90)).sum())
            invalid_lng = int(((lng < -180) | (lng > 180)).sum())
            if invalid_lat:
                rows.append((table_name, "lat", "out_of_range", invalid_lat))
            if invalid_lng:
                rows.append((table_name, "lng", "out_of_range", invalid_lng))

    return rows


def generate_report(tables: dict[str, pd.DataFrame]) -> str:
    summary_rows = [
        (table_name, len(df), len(df.columns))
        for table_name, df in sorted(tables.items())
    ]
    duplicate_check_rows = duplicate_rows(tables)
    full_duplicate_check_rows = full_duplicate_rows(tables)
    fk_check_rows = foreign_key_rows(tables)
    type_checks = type_issue_rows(tables)
    missing_rows = missing_value_rows(tables)

    sections = [
        "# Formula 1 Dataset - Data Quality Report",
        "",
        "Report generated by analyzing the original CSV files in `data/raw`.",
        "",
        "## Table Size",
        markdown_table(("table", "rows", "columns"), summary_rows),
        "",
        "## Missing Values",
        markdown_table(("table", "column", "missing_values", "%"), missing_rows),
        "",
        "## Primary and Composite Keys",
        "The `issues` column counts rows with duplicate keys or missing key values.",
        markdown_table(("table", "key", "issues"), duplicate_check_rows),
        "",
        "## Fully Duplicated Rows",
        markdown_table(("table", "duplicated_rows"), full_duplicate_check_rows),
        "",
        "## Referential Integrity",
        "The `missing_references` column counts child-table values that do not exist in the parent table.",
        markdown_table(("table", "foreign_key_column", "references", "missing_references"), fk_check_rows),
        "",
        "## Types and Domains",
        markdown_table(("table", "column", "check", "issues"), type_checks),
        "",
        "## Operational Notes",
        "- `\\N` markers and empty strings should be converted to real NULL values before loading.",
        "- camelCase columns are inconvenient in PostgreSQL because they require quoted identifiers; exporting snake_case columns is preferred.",
        "- Natural composite keys are needed for `lap_times` and `pit_stops`, which do not have technical id columns.",
        "- Optional time, future session, driver code, and car number fields can remain NULL.",
    ]
    return "\n".join(sections) + "\n"


def main() -> None:
    PROCESSED_DATA_DIR.mkdir(parents=True, exist_ok=True)
    tables = read_raw_csvs()
    report = generate_report(tables)
    REPORT_PATH.write_text(report, encoding="utf-8")
    print(f"Data quality report written to {REPORT_PATH}")


if __name__ == "__main__":
    main()
