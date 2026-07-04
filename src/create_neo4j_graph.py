from __future__ import annotations

import os
from collections import Counter
from dataclasses import dataclass
from itertools import combinations
from pathlib import Path
from typing import Any, Iterable

import pandas as pd
from neo4j import GraphDatabase
from neo4j import Session


DATA_DIR = Path(os.getenv("DATA_DIR", "/app/data/processed"))
RESET_DATABASE = os.getenv("RESET_NEO4J_DATABASE", "true").lower() == "true"
LOAD_DATA = os.getenv("LOAD_NEO4J_DATA", "true").lower() == "true"
BATCH_SIZE = int(os.getenv("NEO4J_BATCH_SIZE", "5000"))
CLEAR_BATCH_SIZE = int(os.getenv("NEO4J_CLEAR_BATCH_SIZE", "5000"))


@dataclass(frozen=True)
class CsvImport:
    file_name: str
    cypher: str
    integer_columns: tuple[str, ...] = ()
    float_columns: tuple[str, ...] = ()


CONSTRAINTS_AND_INDEXES = (
    "CREATE CONSTRAINT season_year IF NOT EXISTS FOR (s:Season) REQUIRE s.year IS UNIQUE",
    "CREATE CONSTRAINT race_id IF NOT EXISTS FOR (r:Race) REQUIRE r.race_id IS UNIQUE",
    "CREATE CONSTRAINT circuit_id IF NOT EXISTS FOR (c:Circuit) REQUIRE c.circuit_id IS UNIQUE",
    "CREATE CONSTRAINT driver_id IF NOT EXISTS FOR (d:Driver) REQUIRE d.driver_id IS UNIQUE",
    "CREATE CONSTRAINT constructor_id IF NOT EXISTS FOR (c:Constructor) REQUIRE c.constructor_id IS UNIQUE",
    "CREATE CONSTRAINT status_id IF NOT EXISTS FOR (s:Status) REQUIRE s.status_id IS UNIQUE",
    "CREATE CONSTRAINT race_lap_id IF NOT EXISTS FOR (l:RaceLap) REQUIRE l.race_lap_id IS UNIQUE",
    "CREATE INDEX race_year_round IF NOT EXISTS FOR (r:Race) ON (r.year, r.round)",
    "CREATE INDEX driver_ref IF NOT EXISTS FOR (d:Driver) ON (d.driver_ref)",
    "CREATE INDEX constructor_ref IF NOT EXISTS FOR (c:Constructor) ON (c.constructor_ref)",
    "CREATE INDEX circuit_ref IF NOT EXISTS FOR (c:Circuit) ON (c.circuit_ref)",
    "CREATE INDEX race_lap_race_lap IF NOT EXISTS FOR (l:RaceLap) ON (l.race_id, l.lap)",
    "CREATE INDEX teammate_for_shared_races IF NOT EXISTS FOR ()-[r:TEAMMATE_FOR]-() ON (r.shared_races)",
    "CREATE INDEX recorded_lap_milliseconds IF NOT EXISTS FOR ()-[r:RECORDED_LAP]-() ON (r.milliseconds)",
)


NODE_IMPORTS = (
    CsvImport(
        file_name="seasons.csv",
        integer_columns=("year",),
        cypher="""
            UNWIND $rows AS row
            MERGE (season:Season {year: row.year})
        """,
    ),
    CsvImport(
        file_name="circuits.csv",
        integer_columns=("circuit_id", "alt"),
        float_columns=("lat", "lng"),
        cypher="""
            UNWIND $rows AS row
            MERGE (circuit:Circuit {circuit_id: row.circuit_id})
            SET circuit.circuit_ref = row.circuit_ref,
                circuit.name = row.name,
                circuit.location = row.location,
                circuit.country = row.country,
                circuit.lat = row.lat,
                circuit.lng = row.lng,
                circuit.alt = row.alt
        """,
    ),
    CsvImport(
        file_name="constructors.csv",
        integer_columns=("constructor_id",),
        cypher="""
            UNWIND $rows AS row
            MERGE (constructor:Constructor {constructor_id: row.constructor_id})
            SET constructor.constructor_ref = row.constructor_ref,
                constructor.name = row.name,
                constructor.nationality = row.nationality
        """,
    ),
    CsvImport(
        file_name="drivers.csv",
        integer_columns=("driver_id", "number"),
        cypher="""
            UNWIND $rows AS row
            MERGE (driver:Driver {driver_id: row.driver_id})
            SET driver.driver_ref = row.driver_ref,
                driver.number = row.number,
                driver.code = row.code,
                driver.forename = row.forename,
                driver.surname = row.surname,
                driver.dob = row.dob,
                driver.nationality = row.nationality
        """,
    ),
    CsvImport(
        file_name="status.csv",
        integer_columns=("status_id",),
        cypher="""
            UNWIND $rows AS row
            MERGE (status:Status {status_id: row.status_id})
            SET status.status = row.status
        """,
    ),
    CsvImport(
        file_name="races.csv",
        integer_columns=("race_id", "year", "round", "circuit_id"),
        cypher="""
            UNWIND $rows AS row
            MERGE (race:Race {race_id: row.race_id})
            SET race.year = row.year,
                race.round = row.round,
                race.circuit_id = row.circuit_id,
                race.name = row.name,
                race.date = row.date,
                race.time = row.time,
                race.fp1_date = row.fp1_date,
                race.fp1_time = row.fp1_time,
                race.fp2_date = row.fp2_date,
                race.fp2_time = row.fp2_time,
                race.fp3_date = row.fp3_date,
                race.fp3_time = row.fp3_time,
                race.quali_date = row.quali_date,
                race.quali_time = row.quali_time,
                race.sprint_date = row.sprint_date,
                race.sprint_time = row.sprint_time
        """,
    ),
)


RELATIONSHIP_IMPORTS = (
    CsvImport(
        file_name="races.csv",
        integer_columns=("race_id", "year", "round", "circuit_id"),
        cypher="""
            UNWIND $rows AS row
            MATCH (season:Season {year: row.year})
            MATCH (race:Race {race_id: row.race_id})
            MATCH (circuit:Circuit {circuit_id: row.circuit_id})
            MERGE (season)-[has_race:HAS_RACE]->(race)
            SET has_race.round = row.round
            MERGE (circuit)-[hosted:HOSTED]->(race)
            SET hosted.date = row.date
        """,
    ),
    CsvImport(
        file_name="results.csv",
        integer_columns=(
            "result_id",
            "race_id",
            "driver_id",
            "constructor_id",
            "number",
            "grid",
            "position",
            "position_order",
            "laps",
            "milliseconds",
            "fastest_lap",
            "rank",
            "status_id",
        ),
        float_columns=("points", "fastest_lap_speed"),
        cypher="""
            UNWIND $rows AS row
            MATCH (driver:Driver {driver_id: row.driver_id})
            MATCH (race:Race {race_id: row.race_id})
            MATCH (constructor:Constructor {constructor_id: row.constructor_id})
            MATCH (status:Status {status_id: row.status_id})
            CREATE (driver)-[:RESULT {
                result_id: row.result_id,
                constructor_id: row.constructor_id,
                status_id: row.status_id,
                number: row.number,
                grid: row.grid,
                position: row.position,
                position_text: row.position_text,
                position_order: row.position_order,
                points: row.points,
                laps: row.laps,
                time: row.time,
                milliseconds: row.milliseconds,
                fastest_lap: row.fastest_lap,
                rank: row.rank,
                fastest_lap_time: row.fastest_lap_time,
                fastest_lap_speed: row.fastest_lap_speed
            }]->(race)
            CREATE (driver)-[:DROVE_FOR {
                result_id: row.result_id,
                race_id: row.race_id,
                number: row.number,
                grid: row.grid,
                points: row.points,
                position_order: row.position_order
            }]->(constructor)
            CREATE (race)-[:FINISHED_WITH_STATUS {
                result_id: row.result_id,
                driver_id: row.driver_id,
                constructor_id: row.constructor_id
            }]->(status)
        """,
    ),
    CsvImport(
        file_name="sprint_results.csv",
        integer_columns=(
            "result_id",
            "race_id",
            "driver_id",
            "constructor_id",
            "number",
            "grid",
            "position",
            "position_order",
            "laps",
            "milliseconds",
            "fastest_lap",
            "status_id",
        ),
        float_columns=("points",),
        cypher="""
            UNWIND $rows AS row
            MATCH (driver:Driver {driver_id: row.driver_id})
            MATCH (race:Race {race_id: row.race_id})
            MATCH (constructor:Constructor {constructor_id: row.constructor_id})
            MATCH (status:Status {status_id: row.status_id})
            CREATE (driver)-[:SPRINT_RESULT {
                result_id: row.result_id,
                constructor_id: row.constructor_id,
                status_id: row.status_id,
                number: row.number,
                grid: row.grid,
                position: row.position,
                position_text: row.position_text,
                position_order: row.position_order,
                points: row.points,
                laps: row.laps,
                time: row.time,
                milliseconds: row.milliseconds,
                fastest_lap: row.fastest_lap,
                fastest_lap_time: row.fastest_lap_time
            }]->(race)
            CREATE (driver)-[:SPRINT_DROVE_FOR {
                result_id: row.result_id,
                race_id: row.race_id,
                number: row.number,
                grid: row.grid,
                points: row.points,
                position_order: row.position_order
            }]->(constructor)
            CREATE (race)-[:SPRINT_FINISHED_WITH_STATUS {
                result_id: row.result_id,
                driver_id: row.driver_id,
                constructor_id: row.constructor_id
            }]->(status)
        """,
    ),
    CsvImport(
        file_name="qualifying.csv",
        integer_columns=("qualify_id", "race_id", "driver_id", "constructor_id", "number", "position"),
        cypher="""
            UNWIND $rows AS row
            MATCH (driver:Driver {driver_id: row.driver_id})
            MATCH (race:Race {race_id: row.race_id})
            MATCH (constructor:Constructor {constructor_id: row.constructor_id})
            CREATE (driver)-[:QUALIFIED {
                qualify_id: row.qualify_id,
                constructor_id: row.constructor_id,
                number: row.number,
                position: row.position,
                q1: row.q1,
                q2: row.q2,
                q3: row.q3
            }]->(race)
            CREATE (driver)-[:QUALIFIED_FOR {
                qualify_id: row.qualify_id,
                race_id: row.race_id,
                number: row.number,
                position: row.position
            }]->(constructor)
        """,
    ),
    CsvImport(
        file_name="lap_times.csv",
        integer_columns=("race_id", "driver_id", "lap", "position", "milliseconds"),
        cypher="""
            UNWIND $rows AS row
            MATCH (driver:Driver {driver_id: row.driver_id})
            MATCH (race:Race {race_id: row.race_id})
            CREATE (driver)-[:LAP_TIME {
                lap: row.lap,
                position: row.position,
                time: row.time,
                milliseconds: row.milliseconds
            }]->(race)
        """,
    ),
    CsvImport(
        file_name="pit_stops.csv",
        integer_columns=("race_id", "driver_id", "stop", "lap", "milliseconds"),
        cypher="""
            UNWIND $rows AS row
            MATCH (driver:Driver {driver_id: row.driver_id})
            MATCH (race:Race {race_id: row.race_id})
            CREATE (driver)-[:PIT_STOP {
                stop: row.stop,
                lap: row.lap,
                time: row.time,
                duration: row.duration,
                milliseconds: row.milliseconds
            }]->(race)
        """,
    ),
    CsvImport(
        file_name="driver_standings.csv",
        integer_columns=("driver_standings_id", "race_id", "driver_id", "position", "wins"),
        float_columns=("points",),
        cypher="""
            UNWIND $rows AS row
            MATCH (driver:Driver {driver_id: row.driver_id})
            MATCH (race:Race {race_id: row.race_id})
            CREATE (driver)-[:DRIVER_STANDING {
                driver_standings_id: row.driver_standings_id,
                points: row.points,
                position: row.position,
                position_text: row.position_text,
                wins: row.wins
            }]->(race)
        """,
    ),
    CsvImport(
        file_name="constructor_standings.csv",
        integer_columns=("constructor_standings_id", "race_id", "constructor_id", "position", "wins"),
        float_columns=("points",),
        cypher="""
            UNWIND $rows AS row
            MATCH (constructor:Constructor {constructor_id: row.constructor_id})
            MATCH (race:Race {race_id: row.race_id})
            CREATE (constructor)-[:CONSTRUCTOR_STANDING {
                constructor_standings_id: row.constructor_standings_id,
                points: row.points,
                position: row.position,
                position_text: row.position_text,
                wins: row.wins
            }]->(race)
        """,
    ),
    CsvImport(
        file_name="constructor_results.csv",
        integer_columns=("constructor_results_id", "race_id", "constructor_id"),
        float_columns=("points",),
        cypher="""
            UNWIND $rows AS row
            MATCH (constructor:Constructor {constructor_id: row.constructor_id})
            MATCH (race:Race {race_id: row.race_id})
            CREATE (constructor)-[:CONSTRUCTOR_RESULT {
                constructor_results_id: row.constructor_results_id,
                points: row.points,
                status: row.status
            }]->(race)
        """,
    ),
)


def connect():
    uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
    user = os.getenv("NEO4J_USER", "neo4j")
    password = os.getenv("NEO4J_PASSWORD", "f1_password")
    return GraphDatabase.driver(uri, auth=(user, password))


def clean_value(value: Any) -> Any:
    if pd.isna(value):
        return None
    if value == "":
        return None
    return value


def convert_dataframe(df: pd.DataFrame, csv_import: CsvImport) -> pd.DataFrame:
    converted = df.astype(object).where(pd.notna(df), None)

    for column in csv_import.integer_columns:
        if column in converted.columns:
            converted[column] = pd.to_numeric(converted[column], errors="coerce").astype("Int64")

    for column in csv_import.float_columns:
        if column in converted.columns:
            converted[column] = pd.to_numeric(converted[column], errors="coerce").astype("Float64")

    return converted


def dataframe_to_rows(df: pd.DataFrame) -> list[dict[str, Any]]:
    rows = []
    for record in df.to_dict("records"):
        rows.append({key: clean_value(value) for key, value in record.items()})
    return rows


def read_csv_batches(csv_import: CsvImport) -> Iterable[list[dict[str, Any]]]:
    path = DATA_DIR / csv_import.file_name
    if not path.exists():
        raise FileNotFoundError(f"Missing CSV file: {path}")

    for chunk in pd.read_csv(path, keep_default_na=False, chunksize=BATCH_SIZE):
        converted = convert_dataframe(chunk, csv_import)
        yield dataframe_to_rows(converted)


def run_write(session: Session, cypher: str, rows: list[dict[str, Any]]) -> None:
    session.execute_write(lambda tx: tx.run(cypher, rows=rows).consume())


def run_write_batches(session: Session, cypher: str, rows: list[dict[str, Any]]) -> None:
    for start in range(0, len(rows), BATCH_SIZE):
        run_write(session, cypher, rows[start : start + BATCH_SIZE])


def clear_database(session: Session) -> None:
    print("Clearing existing Neo4j graph")
    deleted_relationships = 0
    while True:
        result = session.run(
            """
            MATCH ()-[relationship]->()
            WITH relationship LIMIT $batch_size
            DELETE relationship
            RETURN count(relationship) AS deleted_count
            """,
            batch_size=CLEAR_BATCH_SIZE,
        ).single()
        deleted_count = result["deleted_count"] if result else 0
        deleted_relationships += deleted_count
        if deleted_count == 0:
            break

    deleted_total = 0
    while True:
        result = session.run(
            """
            MATCH (node)
            WITH node LIMIT $batch_size
            DELETE node
            RETURN count(node) AS deleted_count
            """,
            batch_size=CLEAR_BATCH_SIZE,
        ).single()
        deleted_count = result["deleted_count"] if result else 0
        deleted_total += deleted_count
        if deleted_count == 0:
            break
    print(f"Deleted {deleted_relationships} existing Neo4j relationships")
    print(f"Deleted {deleted_total} existing Neo4j nodes")


def create_constraints_and_indexes(session: Session) -> None:
    print("Creating Neo4j constraints and indexes")
    for statement in CONSTRAINTS_AND_INDEXES:
        session.run(statement).consume()


def import_csv(session: Session, csv_import: CsvImport) -> int:
    total_rows = 0
    for rows in read_csv_batches(csv_import):
        run_write(session, csv_import.cypher, rows)
        total_rows += len(rows)
    return total_rows


def import_all(session: Session) -> None:
    for csv_import in NODE_IMPORTS:
        row_count = import_csv(session, csv_import)
        print(f"Imported {row_count} rows from {csv_import.file_name} as nodes")

    for csv_import in RELATIONSHIP_IMPORTS:
        row_count = import_csv(session, csv_import)
        print(f"Imported {row_count} rows from {csv_import.file_name} as relationships")

    create_derived_relationships(session)


def create_derived_relationships(session: Session) -> None:
    print("Creating derived Neo4j relationships")
    session.run(
        """
        MATCH ()-[relationship:TEAMMATE_FOR|TEAMMATE_WITH|RECORDED_LAP|HAS_LAP]->()
        DELETE relationship
        """
    ).consume()
    session.run("MATCH (lap:RaceLap) DELETE lap").consume()

    results = pd.read_csv(DATA_DIR / "results.csv")
    races = pd.read_csv(DATA_DIR / "races.csv", usecols=["race_id", "year", "name"])
    drivers = pd.read_csv(DATA_DIR / "drivers.csv", usecols=["driver_id", "forename", "surname"])
    lap_times = pd.read_csv(
        DATA_DIR / "lap_times.csv",
        usecols=["race_id", "driver_id", "lap", "position", "time", "milliseconds"],
    )

    create_teammate_relationships(session, results)
    create_race_lap_model(session, lap_times, races)


def create_teammate_relationships(session: Session, results: pd.DataFrame) -> None:
    pair_constructor_counts: Counter[tuple[int, int, int]] = Counter()
    pair_counts: Counter[tuple[int, int]] = Counter()

    for (_, constructor_id), frame in results.groupby(["race_id", "constructor_id"], sort=False):
        driver_ids = sorted({int(driver_id) for driver_id in frame["driver_id"].dropna()})
        for driver_a_id, driver_b_id in combinations(driver_ids, 2):
            pair_constructor_counts[(driver_a_id, driver_b_id, int(constructor_id))] += 1
            pair_counts[(driver_a_id, driver_b_id)] += 1

    teammate_for_rows = [
        {
            "driver_a_id": driver_a_id,
            "driver_b_id": driver_b_id,
            "constructor_id": constructor_id,
            "shared_races": shared_races,
        }
        for (driver_a_id, driver_b_id, constructor_id), shared_races in pair_constructor_counts.items()
    ]
    teammate_with_rows = [
        {"driver_a_id": driver_a_id, "driver_b_id": driver_b_id, "shared_races": shared_races}
        for (driver_a_id, driver_b_id), shared_races in pair_counts.items()
    ]

    run_write_batches(
        session,
        """
        UNWIND $rows AS row
        MATCH (driver_a:Driver {driver_id: row.driver_a_id})
        MATCH (driver_b:Driver {driver_id: row.driver_b_id})
        MERGE (driver_a)-[teammate:TEAMMATE_FOR {constructor_id: row.constructor_id}]->(driver_b)
        SET teammate.shared_races = row.shared_races
        """,
        teammate_for_rows,
    )
    run_write_batches(
        session,
        """
        UNWIND $rows AS row
        MATCH (driver_a:Driver {driver_id: row.driver_a_id})
        MATCH (driver_b:Driver {driver_id: row.driver_b_id})
        MERGE (driver_a)-[teammate:TEAMMATE_WITH]->(driver_b)
        SET teammate.shared_races = row.shared_races
        """,
        teammate_with_rows,
    )
    print(f"Created {len(teammate_for_rows)} TEAMMATE_FOR relationships")
    print(f"Created {len(teammate_with_rows)} TEAMMATE_WITH relationships")


def create_race_lap_model(
    session: Session,
    lap_times: pd.DataFrame,
    races: pd.DataFrame,
) -> None:
    race_lookup = races.set_index("race_id").to_dict("index")
    race_lap_rows = []
    for race_id, lap in lap_times[["race_id", "lap"]].drop_duplicates().itertuples(index=False):
        race = race_lookup[int(race_id)]
        race_lap_rows.append(
            {
                "race_lap_id": f"{int(race_id)}-{int(lap)}",
                "race_id": int(race_id),
                "lap": int(lap),
                "year": int(race["year"]),
                "race_name": str(race["name"]),
            }
        )

    run_write_batches(
        session,
        """
        UNWIND $rows AS row
        MATCH (race:Race {race_id: row.race_id})
        MERGE (lap:RaceLap {race_lap_id: row.race_lap_id})
        SET lap.race_id = row.race_id,
            lap.lap = row.lap,
            lap.year = row.year,
            lap.race_name = row.race_name
        MERGE (race)-[:HAS_LAP]->(lap)
        """,
        race_lap_rows,
    )

    recorded_lap_rows = []
    for row in lap_times.itertuples(index=False):
        recorded_lap_rows.append(
            {
                "race_lap_id": f"{int(row.race_id)}-{int(row.lap)}",
                "driver_id": int(row.driver_id),
                "position": int(row.position),
                "time": row.time,
                "milliseconds": int(row.milliseconds),
            }
        )

    run_write_batches(
        session,
        """
        UNWIND $rows AS row
        MATCH (driver:Driver {driver_id: row.driver_id})
        MATCH (lap:RaceLap {race_lap_id: row.race_lap_id})
        CREATE (driver)-[:RECORDED_LAP {
            position: row.position,
            time: row.time,
            milliseconds: row.milliseconds
        }]->(lap)
        """,
        recorded_lap_rows,
    )
    print(f"Created {len(race_lap_rows)} RaceLap nodes")
    print(f"Created {len(recorded_lap_rows)} RECORDED_LAP relationships")


def print_graph_summary(session: Session) -> None:
    node_count = session.run("MATCH (n) RETURN count(n) AS count").single()["count"]
    relationship_count = session.run("MATCH ()-[r]->() RETURN count(r) AS count").single()["count"]
    print(f"Neo4j graph contains {node_count} nodes and {relationship_count} relationships")


def main() -> None:
    print("Connecting to Neo4j")
    with connect() as driver:
        driver.verify_connectivity()
        with driver.session(database=os.getenv("NEO4J_DATABASE", "neo4j")) as session:
            if RESET_DATABASE:
                clear_database(session)

            create_constraints_and_indexes(session)

            if LOAD_DATA:
                import_all(session)

            print_graph_summary(session)

    print("Neo4j graph initialization completed")


if __name__ == "__main__":
    main()
