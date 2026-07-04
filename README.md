# Formula 1 Database Performance Comparison

This project compares relational and graph database implementations of a cleaned Formula 1 dataset.

## PostgreSQL with Docker

Build the Python initialization image, start PostgreSQL, create the schema, and load the processed CSV files:

```bash
docker compose up --build
```

The compose stack contains:

- `postgres`: PostgreSQL 16 database container.
- `db_init`: Python container that creates the SQL schema and imports `data/processed/*.csv`.

Default connection settings:

```text
host: localhost
port: 5432
database: formula1
user: f1_user
password: f1_password
```

The initialization script is idempotent by default because `RESET_DATABASE=true` drops and recreates the Formula 1 tables each time `db_init` runs.

## Neo4j with Docker

Start Neo4j and load the graph model from the processed CSV files:

```bash
docker compose up --build neo4j neo4j_init
```

The compose stack contains:

- `neo4j`: Neo4j 5 Community database container.
- `neo4j_init`: Python container that creates graph constraints and imports `data/processed/*.csv`.

Default Neo4j connection settings:

```text
browser: http://localhost:7474
bolt: bolt://localhost:7687
user: neo4j
password: f1_password
```

The Neo4j graph follows the model documented in `Reports/neo4j_graph_model.md`. Stable entities such as seasons, races, circuits, drivers, constructors, and status values are modeled as nodes. Race facts such as results, qualifying, lap times, pit stops, and standings are modeled as relationships with properties.

The import also creates graph-oriented structures for benchmark workloads: teammate links between drivers and `RaceLap` event nodes for lap-level analysis. These additions keep the source facts available while modeling domain relationships that would otherwise require repeated expensive self-joins or recursive traversals at query time.

The initialization script is idempotent by default because `RESET_NEO4J_DATABASE=true` clears the existing graph before importing the processed CSV files.

## PostgreSQL Benchmark

The benchmark is designed to run locally, outside Docker, while the PostgreSQL container is running. This keeps the database isolated in Docker but measures query execution from a normal client process.

Run all benchmark queries:

```bash
venv\Scripts\python.exe src\benchmark_postgres.py
```

The benchmark reads:

```text
sql/sql_queries.sql
```

and writes timestamped results to:

```text
benchmark_results/
```

Each query is measured in two ways:

- Python wall-clock timing with `time.perf_counter()`.
- PostgreSQL execution details with `EXPLAIN ANALYZE`.
- Queries use a 10-minute statement timeout by default. Timed-out queries are recorded instead of stopping the benchmark.

The previous SQL benchmark suite is archived as:

```text
sql/sql_queries_previous.sql
```

## Neo4j Benchmark

Neo4j benchmark queries are stored in:

```text
neo4j/neo4j_queries.cypher
```

They are semantically paired with the PostgreSQL queries in `sql/sql_queries.sql`. The Neo4j benchmark records Python wall-clock timing and `PROFILE` output, which is the Neo4j equivalent of execution-plan analysis.

Run all Neo4j benchmark queries:

```bash
venv\Scripts\python.exe src\benchmark_neo4j.py
```

Create a combined comparison report from the latest PostgreSQL and Neo4j JSON benchmark outputs:

```bash
venv\Scripts\python.exe src\benchmark_summary.py
```

### Benchmark Queries

`Q1_REL_YEARLY_WINNERS`

Objective: retrieve every race winner in Formula 1 history, enrich each win with lap-time pace context from `lap_times`, and include cumulative career win numbers for both the driver and constructor. This keeps the query historically meaningful while forcing it to touch the largest table in the dataset.

PostgreSQL implementation: joins `results`, `races`, `drivers`, and `constructors`, filters winner rows with `position_order = 1`, aggregates lap pace context from `lap_times`, and uses window functions to calculate cumulative win counters. Neo4j traverses `RESULT`, `DROVE_FOR`, and `LAP_TIME` relationships and derives equivalent counters from collected graph rows.

`Q2_REL_CONSTRUCTOR_POINTS_BY_SEASON`

Objective: rebuild constructor standings after every championship round by combining race and sprint points, calculating each constructor's running season total, and ranking teams at each round. This answers a more realistic standings question than a final season aggregate.

PostgreSQL implementation: combines `results` and `sprint_results` with `UNION ALL`, groups by race round and constructor, then uses window functions for running season totals and per-round rankings. Neo4j traverses `DROVE_FOR` and `SPRINT_DROVE_FOR` relationships and performs equivalent grouping and ranking manually in Cypher.

`Q3_REL_RACE_PACE_LAP_AGGREGATION`

Objective: compare each driver's average race pace per season by aggregating every recorded lap in `lap_times`. This is meant to identify which drivers were consistently fast over full seasons, not just who set one isolated fastest lap.

PostgreSQL implementation: scans `lap_times`, joins `races` and `drivers`, groups by season and driver, and computes average, best, and slowest lap times. This favors PostgreSQL because it is a large relational aggregate over the biggest table.

`Q4_MIXED_LAP_BATTLE_AGGREGATION`

Objective: find driver pairs who were closely matched on the same laps of the same race, using a maximum lap-time gap of 500 milliseconds. This identifies repeated race battles or closely matched pace patterns.

PostgreSQL implementation: self-joins `lap_times` on `(race_id, lap)`, filters pairs within 500 milliseconds, groups by race and driver pair, and ranks by repeated close laps. Neo4j implements the same logic through `RaceLap` nodes and `RECORDED_LAP` relationships.

`Q5_GRAPH_TEAMMATE_SHORTEST_PATH`

Objective: find the shortest teammate chain connecting Juan Manuel Fangio to Lando Norris, returning the full driver path. Each graph edge means two drivers were teammates for the same constructor in the same race.

PostgreSQL implementation: reads the precomputed `teammate_edges` table created during database setup, then recursively searches acyclic paths while storing the full path. Neo4j traverses the materialized `TEAMMATE_WITH` relationship directly with `shortestPath`.

`Q6_GRAPH_TEAMMATE_NEIGHBORHOOD_REACH`

Objective: starting from Fernando Alonso, compute the shortest teammate-network distance to every distinct driver reachable within eight `TEAMMATE_WITH` hops. This is a neighborhood distance map, not a single target shortest path.

PostgreSQL implementation: recursively expands simple paths over the precomputed `teammate_edges` table, prevents cycles per branch, and deduplicates the nearest distance per reached driver. Neo4j runs shortest path expansion to many target drivers over native `TEAMMATE_WITH` adjacency.

`Q7_GRAPH_CONSTRUCTOR_DRIVER_BRIDGE`

Objective: find the shortest constructor-driver bridge connecting Christensen to Manor Marussia through drivers who raced for adjacent constructor links. This pair was chosen because it requires several alternating constructor and driver steps instead of a direct shared-driver bridge.

PostgreSQL implementation: reads the precomputed `driver_constructor_edges` table, then recursively alternates constructor and driver nodes while storing path names. Neo4j expresses the same traversal directly over `DROVE_FOR` relationships.
