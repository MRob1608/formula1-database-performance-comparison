# Formula 1 Database Performance Comparison

This project compares PostgreSQL and Neo4j using the same Formula 1 dataset. The goal is to observe how a relational database and a graph database perform with different types of queries, including aggregations, lap-time comparisons and graph traversals.

## Dataset

Download the [Formula 1 World Championship dataset](https://www.kaggle.com/datasets/rohanrao/formula-1-world-championship-1950-2020), place its CSV files inside `data/raw/`, then generate the cleaned files with:

```bash
python src/data_cleaning.py
```

## Setup

Create a virtual environment, activate it and install the dependencies:

```bash
python -m venv venv
pip install -r requirements.txt
```

## Running The Databases

To build the project, start both databases and import the data:

```bash
docker compose up --build
```

The compose file starts four services:

- `postgres`: the PostgreSQL database;
- `db_init`: creates the PostgreSQL tables and imports the CSV files;
- `neo4j`: the Neo4j database;
- `neo4j_init`: creates the graph and imports the CSV files.

It is also possible to start only one database.

PostgreSQL:

```bash
docker compose up --build postgres db_init
```

Neo4j:

```bash
docker compose up --build neo4j neo4j_init
```

## Database Structure

In PostgreSQL the data is stored in normal relational tables, with primary keys, foreign keys and indexes. Two extra tables, `teammate_edges` and `driver_constructor_edges`, are used for the graph-oriented queries.

In Neo4j the main entities, such as drivers, constructors, races and circuits, are nodes. Results, lap times, standings and the other connections are stored as relationships.

The graph also contains `TEAMMATE_WITH` relationships and `RaceLap` nodes. These make it easier to traverse the teammate network and compare drivers on the same lap.

## Running The Benchmarks

PostgreSQL benchmark:

```bash
python src/benchmark_postgres.py
```

Neo4j benchmark:

```bash
python src/benchmark_neo4j.py
```

Combined report:

```bash
python src/benchmark_summary.py
```

The queries are stored in:

```text
sql/sql_queries.sql
neo4j/neo4j_queries.cypher
```

The generated reports are saved in `benchmark_results/`. The scripts measure the total execution time seen by the Python client. They also save `EXPLAIN ANALYZE` for PostgreSQL and `PROFILE` for Neo4j. The timeout is set to 10 minutes.

There is also a small interactive script that lets the user choose a query and run it on both databases. This is the script used for the demo:

```bash
python src/demo_query_runner.py
```

## Queries

### Q1_REL_RACE_WINNERS_WITH_LAP_CONTEXT

Returns the winner of every race and adds some lap-time information when it is available, such as the winner's average and best lap, the race average and the number of recorded laps. It also keeps a running count of driver and constructor wins.

### Q2_REL_CUMULATIVE_CONSTRUCTOR_POINTS

Combines race and sprint points to calculate the running total of each constructor after every round, together with its position in that season.

### Q3_REL_RACE_PACE_LAP_AGGREGATION

Groups all recorded laps by season and driver. For each driver it returns the number of laps, average lap time, best lap and slowest lap.

### Q4_MIXED_SIMILAR_LAP_PACE_PAIRS

Finds pairs of drivers whose lap times were within 500 milliseconds on the same lap of the same race. Only pairs with at least ten similar laps are included.

### Q5_GRAPH_TEAMMATE_SHORTEST_PATH

Finds the shortest teammate chain from Juan Fangio to Lando Norris. Two drivers are connected when they raced for the same constructor in at least one race.

### Q6_GRAPH_TEAMMATE_NEIGHBORHOOD_REACH

Starts from Fernando Alonso and checks how many drivers can be reached within eight teammate connections. It also calculates the minimum, maximum and average number of hops.

### Q7_GRAPH_CONSTRUCTOR_DRIVER_BRIDGE

Finds the shortest path between Christensen and Manor Marussia, alternating between constructors and the drivers who raced for them.

The last three queries are all based on shortest paths, but they produce very different results. Q5 looks like the simplest one because it has only one start and one target, but it is the only PostgreSQL query that reaches the timeout. Fangio and Norris are eight hops apart and the recursive query creates a very large number of possible branches before finding the target. This is a good example of how much graph shape and fan-out can affect recursive SQL queries.

## Results

| Query | PostgreSQL time (s) | PostgreSQL rows | Neo4j time (s) | Neo4j rows |
| --- | ---: | ---: | ---: | ---: |
| `Q1_REL_RACE_WINNERS_WITH_LAP_CONTEXT` | 0.172118 | 1128 | 2.982222 | 1128 |
| `Q2_REL_CUMULATIVE_CONSTRUCTOR_POINTS` | 0.067678 | 9557 | 40.275411 | 9557 |
| `Q3_REL_RACE_PACE_LAP_AGGREGATION` | 0.097897 | 693 | 0.813163 | 693 |
| `Q4_MIXED_SIMILAR_LAP_PACE_PAIRS` | 1.020303 | 100 | 5.364244 | 100 |
| `Q5_GRAPH_TEAMMATE_SHORTEST_PATH` | >600 | timeout | 0.113772 | 1 |
| `Q6_GRAPH_TEAMMATE_NEIGHBORHOOD_REACH` | 12.620290 | 1 | 0.263846 | 1 |
| `Q7_GRAPH_CONSTRUCTOR_DRIVER_BRIDGE` | 110.729184 | 1 | 0.062907 | 1 |
