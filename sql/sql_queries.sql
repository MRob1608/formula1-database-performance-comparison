-- Query Q1_REL_YEARLY_WINNERS
-- Objective: list race winners for recent seasons.
-- Expected profile: favorable to PostgreSQL because it is a selective relational join over indexed keys.
SELECT
    r.year,
    r.round,
    r.name AS race_name,
    d.forename || ' ' || d.surname AS winner,
    c.name AS constructor,
    res.time AS winning_time
FROM results AS res
JOIN races AS r ON r.race_id = res.race_id
JOIN drivers AS d ON d.driver_id = res.driver_id
JOIN constructors AS c ON c.constructor_id = res.constructor_id
WHERE res.position_order = 1
  AND r.year >= 2020
ORDER BY r.year DESC, r.round DESC;

-- Query Q2_REL_CONSTRUCTOR_POINTS_BY_SEASON
-- Objective: aggregate constructor points by season.
-- Expected profile: favorable to PostgreSQL because it is a classic GROUP BY aggregate.
SELECT
    r.year,
    c.name AS constructor,
    SUM(res.points) AS total_points,
    COUNT(*) AS classified_results
FROM results AS res
JOIN races AS r ON r.race_id = res.race_id
JOIN constructors AS c ON c.constructor_id = res.constructor_id
GROUP BY r.year, c.constructor_id, c.name
HAVING SUM(res.points) > 0
ORDER BY r.year DESC, total_points DESC;

-- Query Q3_REL_RACE_PACE_LAP_AGGREGATION
-- Objective: compare average lap pace by driver and season across all recorded laps.
-- Expected profile: favorable to PostgreSQL because it scans and aggregates the largest table with relational joins.
SELECT
    r.year,
    d.forename || ' ' || d.surname AS driver,
    COUNT(*) AS laps_recorded,
    ROUND(AVG(lt.milliseconds)::numeric, 2) AS avg_lap_ms,
    MIN(lt.milliseconds) AS best_lap_ms,
    MAX(lt.milliseconds) AS slowest_lap_ms
FROM lap_times AS lt
JOIN races AS r ON r.race_id = lt.race_id
JOIN drivers AS d ON d.driver_id = lt.driver_id
GROUP BY r.year, d.driver_id, d.forename, d.surname
--HAVING COUNT(*) >= 100
ORDER BY r.year DESC, avg_lap_ms ASC
--LIMIT 100;

-- Query Q4_GRAPH_DRIVER_TEAMMATE_NETWORK
-- Objective: find driver pairs who were teammates and count shared races.
-- Expected profile: favorable to graph databases because it is naturally a relationship/path query between drivers through constructors and races.
SELECT
    d1.forename || ' ' || d1.surname AS driver_a,
    d2.forename || ' ' || d2.surname AS driver_b,
    c.name AS constructor,
    COUNT(DISTINCT res1.race_id) AS shared_races
FROM results AS res1
JOIN results AS res2
  ON res2.race_id = res1.race_id
 AND res2.constructor_id = res1.constructor_id
 AND res2.driver_id > res1.driver_id
JOIN drivers AS d1 ON d1.driver_id = res1.driver_id
JOIN drivers AS d2 ON d2.driver_id = res2.driver_id
JOIN constructors AS c ON c.constructor_id = res1.constructor_id
GROUP BY d1.driver_id, d1.forename, d1.surname, d2.driver_id, d2.forename, d2.surname, c.constructor_id, c.name
HAVING COUNT(DISTINCT res1.race_id) >= 20
ORDER BY shared_races DESC, constructor
LIMIT 50;

-- Query Q5_GRAPH_DRIVER_SEPARATION
-- Objective: compute shortest teammate-network distances across all Formula 1 drivers and return the most distant connected driver pairs.
-- Expected profile: favorable to graph databases because shortest path expansion is native in Neo4j but requires recursive breadth-first traversal over a derived edge table in PostgreSQL.
WITH RECURSIVE teammate_edges AS MATERIALIZED (
    SELECT DISTINCT
        res1.driver_id AS from_driver_id,
        res2.driver_id AS to_driver_id
    FROM results AS res1
    JOIN results AS res2
      ON res2.race_id = res1.race_id
     AND res2.constructor_id = res1.constructor_id
     AND res2.driver_id <> res1.driver_id
),
eligible_drivers AS MATERIALIZED (
    SELECT DISTINCT driver_id
    FROM results
),
search AS (
    SELECT
        driver_id AS start_driver_id,
        driver_id AS current_driver_id,
        0 AS depth
    FROM eligible_drivers
    UNION
    SELECT
        search.start_driver_id,
        edge.to_driver_id AS current_driver_id,
        search.depth + 1 AS depth
    FROM search
    JOIN teammate_edges AS edge ON edge.from_driver_id = search.current_driver_id
    WHERE search.depth < 8
),
shortest_distances AS (
    SELECT
        start_driver_id,
        current_driver_id AS target_driver_id,
        MIN(depth) AS shortest_distance
    FROM search
    WHERE depth > 0
    GROUP BY start_driver_id, current_driver_id
)
SELECT
    start_driver.forename || ' ' || start_driver.surname AS start_driver,
    target_driver.forename || ' ' || target_driver.surname AS target_driver,
    shortest_distance
FROM shortest_distances AS sd
JOIN drivers AS start_driver ON start_driver.driver_id = sd.start_driver_id
JOIN drivers AS target_driver ON target_driver.driver_id = sd.target_driver_id
WHERE shortest_distance >= 6
ORDER BY shortest_distance DESC, start_driver, target_driver
LIMIT 100;

-- Query Q6_GRAPH_CONSTRUCTOR_CAREER_TRANSITIONS
-- Objective: identify common driver career transitions between constructors across consecutive constructor spells.
-- Expected profile: favorable to graph databases because constructor-to-constructor movement is naturally represented as paths through drivers.
WITH driver_constructor_years AS (
    SELECT
        res.driver_id,
        res.constructor_id,
        MIN(r.year) AS first_year,
        MAX(r.year) AS last_year,
        COUNT(DISTINCT res.race_id) AS races_with_constructor
    FROM results AS res
    JOIN races AS r ON r.race_id = res.race_id
    GROUP BY res.driver_id, res.constructor_id
),
ordered_constructor_spells AS (
    SELECT
        dcy.*,
        LEAD(dcy.constructor_id) OVER (
            PARTITION BY dcy.driver_id
            ORDER BY dcy.first_year, dcy.last_year, dcy.constructor_id
        ) AS next_constructor_id,
        LEAD(dcy.first_year) OVER (
            PARTITION BY dcy.driver_id
            ORDER BY dcy.first_year, dcy.last_year, dcy.constructor_id
        ) AS next_first_year
    FROM driver_constructor_years AS dcy
),
career_transitions AS (
    SELECT
        driver_id,
        constructor_id AS from_constructor_id,
        next_constructor_id AS to_constructor_id,
        first_year,
        last_year,
        next_first_year
    FROM ordered_constructor_spells
    WHERE next_constructor_id IS NOT NULL
      AND next_constructor_id <> constructor_id
)
SELECT
    from_constructor.name AS from_constructor,
    to_constructor.name AS to_constructor,
    COUNT(DISTINCT ct.driver_id) AS driver_count,
    MIN(ct.first_year) AS earliest_from_year,
    MAX(ct.next_first_year) AS latest_to_year,
    STRING_AGG(DISTINCT driver.forename || ' ' || driver.surname, ', ' ORDER BY driver.forename || ' ' || driver.surname) AS example_drivers
FROM career_transitions AS ct
JOIN constructors AS from_constructor ON from_constructor.constructor_id = ct.from_constructor_id
JOIN constructors AS to_constructor ON to_constructor.constructor_id = ct.to_constructor_id
JOIN drivers AS driver ON driver.driver_id = ct.driver_id
GROUP BY from_constructor.constructor_id, from_constructor.name, to_constructor.constructor_id, to_constructor.name
HAVING COUNT(DISTINCT ct.driver_id) >= 2
ORDER BY driver_count DESC, from_constructor, to_constructor
LIMIT 50;

-- Query Q7_GRAPH_LAP_BATTLE_NETWORK
-- Objective: find driver pairs who were closely matched on the same laps in recent races.
-- Expected profile: favorable to graph databases when modeled with Race/Lap event relationships; PostgreSQL must self-join the largest table by race and lap.
WITH recent_laps AS (
    SELECT
        lt.race_id,
        r.year,
        r.name AS race_name,
        lt.lap,
        lt.driver_id,
        lt.position,
        lt.milliseconds
    FROM lap_times AS lt
    JOIN races AS r ON r.race_id = lt.race_id
    -- WHERE r.year >= 2020
),
close_lap_pairs AS (
    SELECT
        lap_a.year,
        lap_a.race_id,
        lap_a.race_name,
        lap_a.driver_id AS driver_a_id,
        lap_b.driver_id AS driver_b_id,
        COUNT(*) AS close_laps,
        ROUND(AVG(ABS(lap_a.milliseconds - lap_b.milliseconds))::numeric, 2) AS avg_gap_ms
    FROM recent_laps AS lap_a
    JOIN recent_laps AS lap_b
      ON lap_b.race_id = lap_a.race_id
     AND lap_b.lap = lap_a.lap
     AND lap_b.driver_id > lap_a.driver_id
     AND ABS(lap_a.milliseconds - lap_b.milliseconds) <= 500
    GROUP BY lap_a.year, lap_a.race_id, lap_a.race_name, lap_a.driver_id, lap_b.driver_id
    HAVING COUNT(*) >= 10
)
SELECT
    clp.year,
    clp.race_name,
    driver_a.forename || ' ' || driver_a.surname AS driver_a,
    driver_b.forename || ' ' || driver_b.surname AS driver_b,
    clp.close_laps,
    clp.avg_gap_ms
FROM close_lap_pairs AS clp
JOIN drivers AS driver_a ON driver_a.driver_id = clp.driver_a_id
JOIN drivers AS driver_b ON driver_b.driver_id = clp.driver_b_id
ORDER BY clp.close_laps DESC, clp.avg_gap_ms ASC
LIMIT 100;
