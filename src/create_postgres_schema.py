from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import psycopg
from psycopg import sql


@dataclass(frozen=True)
class TableDefinition:
    name: str
    csv_file: str
    columns: tuple[str, ...]
    create_sql: str


DATA_DIR = Path(os.getenv("DATA_DIR", "/app/data/processed"))
RESET_DATABASE = os.getenv("RESET_DATABASE", "true").lower() == "true"
LOAD_DATA = os.getenv("LOAD_DATA", "true").lower() == "true"


TABLES = [
    TableDefinition(
        name="circuits",
        csv_file="circuits.csv",
        columns=("circuit_id", "circuit_ref", "name", "location", "country", "lat", "lng", "alt"),
        create_sql="""
            CREATE TABLE IF NOT EXISTS circuits (
                circuit_id integer PRIMARY KEY,
                circuit_ref text NOT NULL UNIQUE,
                name text NOT NULL,
                location text NOT NULL,
                country text NOT NULL,
                lat numeric NOT NULL CHECK (lat BETWEEN -90 AND 90),
                lng numeric NOT NULL CHECK (lng BETWEEN -180 AND 180),
                alt integer NOT NULL
            );
        """,
    ),
    TableDefinition(
        name="constructors",
        csv_file="constructors.csv",
        columns=("constructor_id", "constructor_ref", "name", "nationality"),
        create_sql="""
            CREATE TABLE IF NOT EXISTS constructors (
                constructor_id integer PRIMARY KEY,
                constructor_ref text NOT NULL UNIQUE,
                name text NOT NULL,
                nationality text NOT NULL
            );
        """,
    ),
    TableDefinition(
        name="drivers",
        csv_file="drivers.csv",
        columns=("driver_id", "driver_ref", "number", "code", "forename", "surname", "dob", "nationality"),
        create_sql="""
            CREATE TABLE IF NOT EXISTS drivers (
                driver_id integer PRIMARY KEY,
                driver_ref text NOT NULL UNIQUE,
                number integer CHECK (number >= 0),
                code text,
                forename text NOT NULL,
                surname text NOT NULL,
                dob date NOT NULL,
                nationality text NOT NULL
            );
        """,
    ),
    TableDefinition(
        name="status",
        csv_file="status.csv",
        columns=("status_id", "status"),
        create_sql="""
            CREATE TABLE IF NOT EXISTS status (
                status_id integer PRIMARY KEY,
                status text NOT NULL UNIQUE
            );
        """,
    ),
    TableDefinition(
        name="races",
        csv_file="races.csv",
        columns=(
            "race_id",
            "year",
            "round",
            "circuit_id",
            "name",
            "date",
            "time",
            "fp1_date",
            "fp1_time",
            "fp2_date",
            "fp2_time",
            "fp3_date",
            "fp3_time",
            "quali_date",
            "quali_time",
            "sprint_date",
            "sprint_time",
        ),
        create_sql="""
            CREATE TABLE IF NOT EXISTS races (
                race_id integer PRIMARY KEY,
                year integer NOT NULL CHECK (year >= 1950),
                round integer NOT NULL CHECK (round > 0),
                circuit_id integer NOT NULL REFERENCES circuits (circuit_id),
                name text NOT NULL,
                date date NOT NULL,
                time time,
                fp1_date date,
                fp1_time time,
                fp2_date date,
                fp2_time time,
                fp3_date date,
                fp3_time time,
                quali_date date,
                quali_time time,
                sprint_date date,
                sprint_time time,
                UNIQUE (year, round)
            );
        """,
    ),
    TableDefinition(
        name="results",
        csv_file="results.csv",
        columns=(
            "result_id",
            "race_id",
            "driver_id",
            "constructor_id",
            "number",
            "grid",
            "position",
            "position_text",
            "position_order",
            "points",
            "laps",
            "time",
            "milliseconds",
            "fastest_lap",
            "rank",
            "fastest_lap_time",
            "fastest_lap_speed",
            "status_id",
        ),
        create_sql="""
            CREATE TABLE IF NOT EXISTS results (
                result_id integer PRIMARY KEY,
                race_id integer NOT NULL REFERENCES races (race_id),
                driver_id integer NOT NULL REFERENCES drivers (driver_id),
                constructor_id integer NOT NULL REFERENCES constructors (constructor_id),
                number integer CHECK (number >= 0),
                grid integer NOT NULL CHECK (grid >= 0),
                position integer CHECK (position > 0),
                position_text text NOT NULL,
                position_order integer NOT NULL CHECK (position_order > 0),
                points numeric NOT NULL CHECK (points >= 0),
                laps integer NOT NULL CHECK (laps >= 0),
                time text,
                milliseconds integer CHECK (milliseconds >= 0),
                fastest_lap integer CHECK (fastest_lap > 0),
                rank integer CHECK (rank >= 0),
                fastest_lap_time text,
                fastest_lap_speed numeric CHECK (fastest_lap_speed >= 0),
                status_id integer NOT NULL REFERENCES status (status_id)
            );
        """,
    ),
    TableDefinition(
        name="sprint_results",
        csv_file="sprint_results.csv",
        columns=(
            "result_id",
            "race_id",
            "driver_id",
            "constructor_id",
            "number",
            "grid",
            "position",
            "position_text",
            "position_order",
            "points",
            "laps",
            "time",
            "milliseconds",
            "fastest_lap",
            "fastest_lap_time",
            "status_id",
        ),
        create_sql="""
            CREATE TABLE IF NOT EXISTS sprint_results (
                result_id integer PRIMARY KEY,
                race_id integer NOT NULL REFERENCES races (race_id),
                driver_id integer NOT NULL REFERENCES drivers (driver_id),
                constructor_id integer NOT NULL REFERENCES constructors (constructor_id),
                number integer NOT NULL CHECK (number >= 0),
                grid integer NOT NULL CHECK (grid >= 0),
                position integer CHECK (position > 0),
                position_text text NOT NULL,
                position_order integer NOT NULL CHECK (position_order > 0),
                points numeric NOT NULL CHECK (points >= 0),
                laps integer NOT NULL CHECK (laps >= 0),
                time text,
                milliseconds integer CHECK (milliseconds >= 0),
                fastest_lap integer CHECK (fastest_lap > 0),
                fastest_lap_time text,
                status_id integer NOT NULL REFERENCES status (status_id),
                UNIQUE (race_id, driver_id)
            );
        """,
    ),
    TableDefinition(
        name="qualifying",
        csv_file="qualifying.csv",
        columns=("qualify_id", "race_id", "driver_id", "constructor_id", "number", "position", "q1", "q2", "q3"),
        create_sql="""
            CREATE TABLE IF NOT EXISTS qualifying (
                qualify_id integer PRIMARY KEY,
                race_id integer NOT NULL REFERENCES races (race_id),
                driver_id integer NOT NULL REFERENCES drivers (driver_id),
                constructor_id integer NOT NULL REFERENCES constructors (constructor_id),
                number integer NOT NULL CHECK (number >= 0),
                position integer NOT NULL CHECK (position > 0),
                q1 text,
                q2 text,
                q3 text,
                UNIQUE (race_id, driver_id),
                UNIQUE (race_id, position)
            );
        """,
    ),
    TableDefinition(
        name="lap_times",
        csv_file="lap_times.csv",
        columns=("race_id", "driver_id", "lap", "position", "time", "milliseconds"),
        create_sql="""
            CREATE TABLE IF NOT EXISTS lap_times (
                race_id integer NOT NULL REFERENCES races (race_id),
                driver_id integer NOT NULL REFERENCES drivers (driver_id),
                lap integer NOT NULL CHECK (lap > 0),
                position integer NOT NULL CHECK (position > 0),
                time text NOT NULL,
                milliseconds integer NOT NULL CHECK (milliseconds >= 0),
                PRIMARY KEY (race_id, driver_id, lap)
            );
        """,
    ),
    TableDefinition(
        name="pit_stops",
        csv_file="pit_stops.csv",
        columns=("race_id", "driver_id", "stop", "lap", "time", "duration", "milliseconds"),
        create_sql="""
            CREATE TABLE IF NOT EXISTS pit_stops (
                race_id integer NOT NULL REFERENCES races (race_id),
                driver_id integer NOT NULL REFERENCES drivers (driver_id),
                stop integer NOT NULL CHECK (stop > 0),
                lap integer NOT NULL CHECK (lap > 0),
                time time NOT NULL,
                duration text NOT NULL,
                milliseconds integer NOT NULL CHECK (milliseconds >= 0),
                PRIMARY KEY (race_id, driver_id, stop)
            );
        """,
    ),
    TableDefinition(
        name="driver_standings",
        csv_file="driver_standings.csv",
        columns=("driver_standings_id", "race_id", "driver_id", "points", "position", "position_text", "wins"),
        create_sql="""
            CREATE TABLE IF NOT EXISTS driver_standings (
                driver_standings_id integer PRIMARY KEY,
                race_id integer NOT NULL REFERENCES races (race_id),
                driver_id integer NOT NULL REFERENCES drivers (driver_id),
                points numeric NOT NULL CHECK (points >= 0),
                position integer NOT NULL CHECK (position > 0),
                position_text text NOT NULL,
                wins integer NOT NULL CHECK (wins >= 0),
                UNIQUE (race_id, driver_id)
            );
        """,
    ),
    TableDefinition(
        name="constructor_standings",
        csv_file="constructor_standings.csv",
        columns=("constructor_standings_id", "race_id", "constructor_id", "points", "position", "position_text", "wins"),
        create_sql="""
            CREATE TABLE IF NOT EXISTS constructor_standings (
                constructor_standings_id integer PRIMARY KEY,
                race_id integer NOT NULL REFERENCES races (race_id),
                constructor_id integer NOT NULL REFERENCES constructors (constructor_id),
                points numeric NOT NULL CHECK (points >= 0),
                position integer NOT NULL CHECK (position > 0),
                position_text text NOT NULL,
                wins integer NOT NULL CHECK (wins >= 0),
                UNIQUE (race_id, constructor_id)
            );
        """,
    ),
    TableDefinition(
        name="constructor_results",
        csv_file="constructor_results.csv",
        columns=("constructor_results_id", "race_id", "constructor_id", "points", "status"),
        create_sql="""
            CREATE TABLE IF NOT EXISTS constructor_results (
                constructor_results_id integer PRIMARY KEY,
                race_id integer NOT NULL REFERENCES races (race_id),
                constructor_id integer NOT NULL REFERENCES constructors (constructor_id),
                points numeric NOT NULL CHECK (points >= 0),
                status text,
                UNIQUE (race_id, constructor_id)
            );
        """,
    ),
]


INDEX_STATEMENTS = (
    "CREATE INDEX IF NOT EXISTS idx_races_year ON races (year);",
    "CREATE INDEX IF NOT EXISTS idx_races_circuit_id ON races (circuit_id);",
    "CREATE INDEX IF NOT EXISTS idx_results_race_id ON results (race_id);",
    "CREATE INDEX IF NOT EXISTS idx_results_driver_id ON results (driver_id);",
    "CREATE INDEX IF NOT EXISTS idx_results_constructor_id ON results (constructor_id);",
    "CREATE INDEX IF NOT EXISTS idx_results_status_id ON results (status_id);",
    "CREATE INDEX IF NOT EXISTS idx_lap_times_driver_id ON lap_times (driver_id);",
    "CREATE INDEX IF NOT EXISTS idx_pit_stops_driver_id ON pit_stops (driver_id);",
    "CREATE INDEX IF NOT EXISTS idx_driver_standings_driver_id ON driver_standings (driver_id);",
    "CREATE INDEX IF NOT EXISTS idx_constructor_standings_constructor_id ON constructor_standings (constructor_id);",
)


def connect() -> psycopg.Connection:
    return psycopg.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=int(os.getenv("DB_PORT", "5432")),
        dbname=os.getenv("DB_NAME", "formula1"),
        user=os.getenv("DB_USER", "f1_user"),
        password=os.getenv("DB_PASSWORD", "f1_password"),
    )


def drop_tables(cursor: psycopg.Cursor) -> None:
    for table in reversed(TABLES):
        cursor.execute(sql.SQL("DROP TABLE IF EXISTS {} CASCADE").format(sql.Identifier(table.name)))


def create_tables(cursor: psycopg.Cursor) -> None:
    for table in TABLES:
        cursor.execute(table.create_sql)


def create_indexes(cursor: psycopg.Cursor) -> None:
    for statement in INDEX_STATEMENTS:
        cursor.execute(statement)


def truncate_tables(cursor: psycopg.Cursor) -> None:
    table_identifiers = [sql.Identifier(table.name) for table in TABLES]
    cursor.execute(
        sql.SQL("TRUNCATE TABLE {} RESTART IDENTITY CASCADE").format(sql.SQL(", ").join(table_identifiers))
    )


def validate_csv_headers(table: TableDefinition, csv_path: Path) -> None:
    with csv_path.open("r", encoding="utf-8", newline="") as file:
        header = file.readline().strip().split(",")

    expected_header = list(table.columns)
    if header != expected_header:
        raise ValueError(
            f"{csv_path} has unexpected columns. Expected {expected_header}, got {header}."
        )


def load_table(cursor: psycopg.Cursor, table: TableDefinition) -> int:
    csv_path = DATA_DIR / table.csv_file
    if not csv_path.exists():
        raise FileNotFoundError(f"Missing CSV file: {csv_path}")

    validate_csv_headers(table, csv_path)

    copy_statement = sql.SQL("COPY {} ({}) FROM STDIN WITH (FORMAT csv, HEADER true, NULL '')").format(
        sql.Identifier(table.name),
        sql.SQL(", ").join(sql.Identifier(column) for column in table.columns),
    )

    with cursor.copy(copy_statement) as copy:
        with csv_path.open("r", encoding="utf-8", newline="") as file:
            while chunk := file.read(1024 * 1024):
                copy.write(chunk)

    cursor.execute(sql.SQL("SELECT count(*) FROM {}").format(sql.Identifier(table.name)))
    return cursor.fetchone()[0]


def load_data(cursor: psycopg.Cursor) -> None:
    truncate_tables(cursor)
    for table in TABLES:
        row_count = load_table(cursor, table)
        print(f"Loaded {row_count} rows into {table.name}")


def main() -> None:
    print("Connecting to PostgreSQL")
    with connect() as connection:
        with connection.cursor() as cursor:
            if RESET_DATABASE:
                print("Dropping existing Formula 1 tables")
                drop_tables(cursor)

            print("Creating Formula 1 tables")
            create_tables(cursor)
            create_indexes(cursor)

            if LOAD_DATA:
                print("Loading processed CSV files")
                load_data(cursor)

        connection.commit()

    print("PostgreSQL schema initialization completed")


if __name__ == "__main__":
    main()
