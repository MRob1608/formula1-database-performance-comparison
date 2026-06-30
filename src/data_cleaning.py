from __future__ import annotations

import re
from pathlib import Path

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RAW_DATA_DIR = PROJECT_ROOT / "data" / "raw"
PROCESSED_DATA_DIR = PROJECT_ROOT / "data" / "processed"
CLEANING_REPORT_PATH = PROCESSED_DATA_DIR / "cleaning_report.md"

MISSING_MARKERS = {"", r"\N"}

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

DATE_COLUMNS = {
    "dob",
    "date",
    "fp1_date",
    "fp2_date",
    "fp3_date",
    "quali_date",
    "sprint_date",
}

TIME_RESULT_TABLES = {"results", "sprint_results"}
URL_COLUMNS = {"url"}


def to_snake_case(name: str) -> str:
    first_pass = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", name)
    snake_case = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", first_pass)
    return snake_case.lower()


def read_raw_table(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, dtype="string", keep_default_na=False)


def normalize_missing_values(df: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    cleaned = df.copy()
    missing_count = 0

    for column in cleaned.columns:
        cleaned[column] = cleaned[column].astype("string").str.strip()
        missing_mask = cleaned[column].isin(MISSING_MARKERS)
        missing_count += int(missing_mask.sum())
        cleaned.loc[missing_mask, column] = pd.NA

    return cleaned, missing_count


def convert_column_types(df: pd.DataFrame, table_name: str) -> pd.DataFrame:
    converted = df.copy()

    for column in converted.columns:
        if column in INTEGER_COLUMNS:
            converted[column] = parse_integer_column(converted[column], table_name, column)
        elif column in FLOAT_COLUMNS:
            converted[column] = parse_float_column(converted[column], table_name, column)
        elif column in DATE_COLUMNS:
            converted[column] = parse_date_column(converted[column], table_name, column)

    return converted


def parse_integer_column(series: pd.Series, table_name: str, column: str) -> pd.Series:
    parsed = pd.to_numeric(series, errors="coerce")
    invalid = parsed.isna() & series.notna()
    if invalid.any():
        raise ValueError(f"{table_name}.{column} contains non-integer values")
    return parsed.astype("Int64")


def parse_float_column(series: pd.Series, table_name: str, column: str) -> pd.Series:
    parsed = pd.to_numeric(series, errors="coerce")
    invalid = parsed.isna() & series.notna()
    if invalid.any():
        raise ValueError(f"{table_name}.{column} contains non-numeric values")
    return parsed.astype("Float64")


def parse_date_column(series: pd.Series, table_name: str, column: str) -> pd.Series:
    parsed = pd.to_datetime(series, format="%Y-%m-%d", errors="coerce")
    invalid = parsed.isna() & series.notna()
    if invalid.any():
        raise ValueError(f"{table_name}.{column} contains invalid dates")

    formatted = parsed.dt.strftime("%Y-%m-%d").astype("string")
    formatted.loc[series.isna()] = pd.NA
    return formatted


def normalize_result_times(df: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    if not {"raceId", "positionOrder", "milliseconds", "time"}.issubset(df.columns):
        return df, 0

    normalized = df.copy()
    milliseconds = pd.to_numeric(normalized["milliseconds"], errors="coerce")
    positions = pd.to_numeric(normalized["positionOrder"], errors="coerce")

    winners = (
        normalized.loc[(positions == 1) & milliseconds.notna(), ["raceId"]]
        .assign(milliseconds=milliseconds[(positions == 1) & milliseconds.notna()].astype("Int64"))
        .drop_duplicates(subset=["raceId"])
        .set_index("raceId")["milliseconds"]
        .to_dict()
    )

    changed = 0
    for index, row in normalized.iterrows():
        if pd.isna(row["time"]) or pd.isna(milliseconds.loc[index]) or pd.isna(positions.loc[index]):
            continue

        current_time = row["time"]
        total_ms = int(milliseconds.loc[index])
        position = int(positions.loc[index])

        if position == 1:
            new_time = format_elapsed_milliseconds(total_ms)
        else:
            winner_ms = winners.get(row["raceId"])
            if winner_ms is None:
                continue

            gap_ms = total_ms - int(winner_ms)
            if gap_ms < 0:
                continue
            new_time = "+" + format_gap_milliseconds(gap_ms)

        if current_time != new_time:
            normalized.at[index, "time"] = new_time
            changed += 1

    return normalized, changed


def format_elapsed_milliseconds(total_ms: int) -> str:
    seconds_total, milliseconds = divmod(total_ms, 1000)
    minutes_total, seconds = divmod(seconds_total, 60)
    hours, minutes = divmod(minutes_total, 60)
    return f"{hours}:{minutes:02d}:{seconds:02d}.{milliseconds:03d}"


def format_gap_milliseconds(gap_ms: int) -> str:
    seconds_total, milliseconds = divmod(gap_ms, 1000)
    minutes, seconds = divmod(seconds_total, 60)
    if minutes:
        return f"{minutes}:{seconds:02d}.{milliseconds:03d}"
    return f"{seconds}.{milliseconds:03d}"


def rename_columns_to_snake_case(df: pd.DataFrame) -> pd.DataFrame:
    return df.rename(columns={column: to_snake_case(column) for column in df.columns})


def drop_url_columns(df: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    url_columns = [column for column in df.columns if column in URL_COLUMNS]
    if not url_columns:
        return df, 0

    return df.drop(columns=url_columns), len(url_columns)


def clean_table(path: Path) -> tuple[str, pd.DataFrame, dict[str, int]]:
    table_name = path.stem
    raw = read_raw_table(path)
    without_missing_markers, replaced_missing = normalize_missing_values(raw)
    typed = convert_column_types(without_missing_markers, table_name)

    normalized_times = 0
    if table_name in TIME_RESULT_TABLES:
        typed, normalized_times = normalize_result_times(typed)

    deduplicated = typed.drop_duplicates()
    duplicate_rows_removed = len(typed) - len(deduplicated)
    without_urls, url_columns_removed = drop_url_columns(deduplicated)
    ready_for_sql = rename_columns_to_snake_case(without_urls)

    metrics = {
        "raw_rows": len(raw),
        "processed_rows": len(ready_for_sql),
        "columns": len(ready_for_sql.columns),
        "url_columns_removed": url_columns_removed,
        "missing_markers_replaced": replaced_missing,
        "duplicate_rows_removed": duplicate_rows_removed,
        "result_times_normalized": normalized_times,
    }
    return table_name, ready_for_sql, metrics


def markdown_table(headers: tuple[str, ...], rows: list[tuple[object, ...]]) -> str:
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(str(value) for value in row) + " |")
    return "\n".join(lines)


def write_cleaning_report(metrics_by_table: dict[str, dict[str, int]]) -> None:
    rows = [
        (
            table_name,
            metrics["raw_rows"],
            metrics["processed_rows"],
            metrics["columns"],
            metrics["url_columns_removed"],
            metrics["missing_markers_replaced"],
            metrics["duplicate_rows_removed"],
            metrics["result_times_normalized"],
        )
        for table_name, metrics in sorted(metrics_by_table.items())
    ]

    report = "\n".join(
        [
            "# Formula 1 Dataset - Cleaning Report",
            "",
            "Clean CSV files generated by `src/data_cleaning.py` from `data/raw`.",
            "",
            "## Operations Performed",
            "- Converted `\\N` markers and empty strings to NULL-ready empty fields in the processed CSV files.",
            "- Trimmed leading and trailing whitespace from all text fields.",
            "- Validated and converted numeric and date fields.",
            "- Removed URL columns because they are not needed for the database imports.",
            "- Converted column names to snake_case to avoid quoted identifiers in PostgreSQL.",
            "- Removed any fully duplicated rows.",
            "- Normalized the `time` fields in `results` and `sprint_results` by using `milliseconds`.",
            "",
            "## Table Summary",
            markdown_table(
                (
                    "table",
                    "raw_rows",
                    "processed_rows",
                    "columns",
                    "url_columns_removed",
                    "nulls_converted",
                    "duplicates_removed",
                    "times_normalized",
                ),
                rows,
            ),
            "",
            "## Output",
            f"- Processed CSV files: `{PROCESSED_DATA_DIR}`",
            f"- Cleaning report: `{CLEANING_REPORT_PATH}`",
            "- Raw data quality report: `data/processed/data_quality_report.md`",
            "",
            "## PostgreSQL and Neo4j Import Notes",
            "- NULL values are represented as empty fields in the processed CSV files; in PostgreSQL use `COPY ... CSV HEADER NULL ''`.",
            "- In Neo4j, cast numeric and date fields during `LOAD CSV` or in the import script.",
            "- `lap_times` should use the composite key `(race_id, driver_id, lap)`.",
            "- `pit_stops` should use the composite key `(race_id, driver_id, stop)`.",
        ]
    )
    CLEANING_REPORT_PATH.write_text(report + "\n", encoding="utf-8")


def main() -> None:
    PROCESSED_DATA_DIR.mkdir(parents=True, exist_ok=True)
    metrics_by_table = {}

    for csv_path in sorted(RAW_DATA_DIR.glob("*.csv")):
        table_name, cleaned, metrics = clean_table(csv_path)
        output_path = PROCESSED_DATA_DIR / csv_path.name
        cleaned.to_csv(output_path, index=False, na_rep="")
        metrics_by_table[table_name] = metrics
        print(f"Wrote {output_path} ({metrics['processed_rows']} rows)")

    write_cleaning_report(metrics_by_table)
    print(f"Cleaning report written to {CLEANING_REPORT_PATH}")


if __name__ == "__main__":
    main()
