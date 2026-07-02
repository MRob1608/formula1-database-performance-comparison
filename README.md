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

### Benchmark Queries

`Q1_REL_YEARLY_WINNERS`

Objective: retrieve the winner of every race from recent Formula 1 seasons, including the race year, round, Grand Prix name, winning driver, winning constructor, and winning time. This answers a common historical question: "Who won each recent race, and with which team?"

PostgreSQL implementation: joins `results`, `races`, `drivers`, and `constructors`, filters winner rows with `position_order = 1`, and orders by season and round. This favors the relational model because it is a direct indexed join over normalized tables.

`Q2_REL_CONSTRUCTOR_POINTS_BY_SEASON`

Objective: calculate how many points each constructor scored in every season and rank constructors by seasonal performance. This answers questions such as "Which teams were strongest in each year?" and "How did constructor performance change over time?"

PostgreSQL implementation: joins `results`, `races`, and `constructors`, then groups by season and constructor. This is a classic relational aggregation and should be a comfortable workload for PostgreSQL.

`Q3_REL_RACE_PACE_LAP_AGGREGATION`

Objective: compare each driver's average race pace per season by aggregating every recorded lap in `lap_times`. This is meant to identify which drivers were consistently fast over full seasons, not just who set one isolated fastest lap.

PostgreSQL implementation: scans `lap_times`, joins `races` and `drivers`, groups by season and driver, and computes average, best, and slowest lap times. This favors PostgreSQL because it is a large relational aggregate over the biggest table.

`Q4_GRAPH_DRIVER_TEAMMATE_NETWORK`

Objective: discover pairs of drivers who raced as teammates for the same constructor in the same races, then count how often each pairing occurred. This answers a network-style question: "Which driver pairings were the most frequent teammates?"

PostgreSQL implementation: self-joins `results` on the same `race_id` and `constructor_id`, then joins driver and constructor metadata. This is a meaningful graph-style query because it asks for connections between drivers through shared teams and races.

`Q5_GRAPH_DRIVER_SEPARATION`

Objective: compute shortest teammate-network distances across all Formula 1 drivers and return the most distant connected driver pairs. Each graph edge means two drivers were teammates in the same race for the same constructor, so the query asks: "Which drivers are connected only through long chains of teammate relationships?"

PostgreSQL implementation: derives teammate edges by self-joining `results`, starts a recursive breadth-first traversal from every driver, expands the teammate network up to depth eight, computes the minimum distance for every reachable driver pair, and returns the pairs with the largest shortest-path distances. This is intentionally graph-like because Neo4j can express the same task with shortest-path traversal over driver relationships.

`Q6_GRAPH_CONSTRUCTOR_CAREER_TRANSITIONS`

Objective: identify repeated career movement patterns between constructors by tracking each driver's constructor history and counting common team-to-team transitions. This answers questions such as "Which constructor moves happened most often across driver careers?"

PostgreSQL implementation: builds driver-constructor spells, uses window functions to find the next constructor in each driver's career, then aggregates repeated constructor-to-constructor transitions. In Neo4j, this is naturally modeled as paths from constructor to driver to next constructor.

`Q7_GRAPH_LAP_BATTLE_NETWORK`

Objective: find driver pairs who were closely matched on the same lap of the same race, using a maximum lap-time gap of 500 milliseconds. This identifies on-track battles or closely matched pace patterns by comparing drivers lap-by-lap across the largest table in the dataset.

PostgreSQL implementation: filters recent `lap_times`, self-joins the largest table on `(race_id, lap)`, checks lap-time gaps within 500 milliseconds, and aggregates close battles by driver pair and race. This is intentionally demanding for PostgreSQL and would map naturally to graph/event traversal if laps are modeled as race events in Neo4j.
