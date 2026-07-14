
-- Query Q1_REL_RACE_WINNERS_WITH_LAP_CONTEXT
-- Objective: retrieve every race winner and, where lap-time data are available, enrich each win with race-pace context and cumulative career win counters for both the driver and constructor.
WITH winners AS (
    SELECT
        r.race_id,
        r.year,
        r.round,
        r.name AS race_name,
        d.driver_id,
        d.forename || ' ' || d.surname AS winner,
        c.constructor_id,
        c.name AS constructor,
        res.time AS winning_time
    FROM results AS res
    JOIN races AS r ON r.race_id = res.race_id
    JOIN drivers AS d ON d.driver_id = res.driver_id
    JOIN constructors AS c ON c.constructor_id = res.constructor_id
    WHERE res.position_order = 1
),
lap_context AS (
    SELECT
        winners.race_id,
        winners.driver_id,
        COUNT(lt.milliseconds) AS race_lap_records,
        COUNT(lt.milliseconds) FILTER (WHERE lt.driver_id = winners.driver_id) AS winner_laps_recorded,
        ROUND(AVG(lt.milliseconds) FILTER (WHERE lt.driver_id = winners.driver_id)::numeric, 2) AS winner_avg_lap_ms,
        MIN(lt.milliseconds) FILTER (WHERE lt.driver_id = winners.driver_id) AS winner_best_lap_ms,
        ROUND(AVG(lt.milliseconds)::numeric, 2) AS race_avg_lap_ms
    FROM winners
    LEFT JOIN lap_times AS lt ON lt.race_id = winners.race_id
    GROUP BY winners.race_id, winners.driver_id
)
SELECT
    winners.year,
    winners.round,
    winners.race_name,
    winners.winner,
    winners.constructor,
    winners.winning_time,
    lap_context.winner_laps_recorded,
    lap_context.winner_avg_lap_ms,
    lap_context.winner_best_lap_ms,
    lap_context.race_avg_lap_ms,
    lap_context.race_lap_records,
    COUNT(*) OVER (
        PARTITION BY winners.driver_id
        ORDER BY winners.year, winners.round
        ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
    ) AS driver_career_win_number,
    COUNT(*) OVER (
        PARTITION BY winners.constructor_id
        ORDER BY winners.year, winners.round
        ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
    ) AS constructor_career_win_number
FROM winners
JOIN lap_context ON lap_context.race_id = winners.race_id
                AND lap_context.driver_id = winners.driver_id
ORDER BY winners.year DESC, winners.round DESC;

-- Query Q2_REL_CUMULATIVE_CONSTRUCTOR_POINTS
-- Objective: rebuild the constructor standings after every championship round by combining race and sprint points, calculating each constructor's running season total, and ranking teams at each round.
WITH scoring_events AS (
    SELECT
        r.year,
        r.round,
        r.race_id,
        r.name AS race_name,
        res.constructor_id,
        res.points,
        'race' AS event_type
    FROM results AS res
    JOIN races AS r ON r.race_id = res.race_id
    UNION ALL
    SELECT
        r.year,
        r.round,
        r.race_id,
        r.name AS race_name,
        sprint.constructor_id,
        sprint.points,
        'sprint' AS event_type
    FROM sprint_results AS sprint
    JOIN races AS r ON r.race_id = sprint.race_id
),
constructor_round_points AS (
    SELECT
        event.year,
        event.round,
        event.race_id,
        event.race_name,
        c.constructor_id,
        c.name AS constructor,
        SUM(event.points) AS round_points,
        COUNT(*) AS classified_results,
        COUNT(*) FILTER (WHERE event.event_type = 'sprint') AS sprint_results
    FROM scoring_events AS event
    JOIN constructors AS c ON c.constructor_id = event.constructor_id
    GROUP BY event.year, event.round, event.race_id, event.race_name, c.constructor_id, c.name
),
running_points AS (
    SELECT
        *,
        SUM(round_points) OVER (
            PARTITION BY year, constructor_id
            ORDER BY round
            ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
        ) AS season_points_to_date
    FROM constructor_round_points
),
ranked_points AS (
    SELECT
        *,
        RANK() OVER (
            PARTITION BY year, round
            ORDER BY season_points_to_date DESC, constructor ASC
        ) AS season_rank_after_round
    FROM running_points
)
SELECT
    year,
    round,
    race_name,
    constructor,
    round_points,
    season_points_to_date,
    season_rank_after_round,
    classified_results,
    sprint_results
FROM ranked_points
WHERE season_points_to_date > 0
ORDER BY year DESC, round DESC, season_rank_after_round ASC;

-- Query Q3_REL_RACE_PACE_LAP_AGGREGATION
-- Objective: compare average lap pace by driver and season across all recorded laps.
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
ORDER BY r.year DESC, avg_lap_ms ASC;

-- Query Q4_MIXED_SIMILAR_LAP_PACE_PAIRS
-- Objective: find driver pairs with similar lap times on the same laps of the same race, highlighting repeated closely matched pace patterns.
WITH close_lap_pairs AS (
    SELECT
        r.year,
        lt_a.race_id,
        r.name AS race_name,
        lt_a.driver_id AS driver_a_id,
        lt_b.driver_id AS driver_b_id,
        COUNT(*) AS close_laps,
        ROUND(AVG(ABS(lt_a.milliseconds - lt_b.milliseconds))::numeric, 2) AS avg_gap_ms
    FROM lap_times AS lt_a
    JOIN lap_times AS lt_b
      ON lt_b.race_id = lt_a.race_id
     AND lt_b.lap = lt_a.lap
     AND lt_b.driver_id > lt_a.driver_id
     AND ABS(lt_a.milliseconds - lt_b.milliseconds) <= 500
    JOIN races AS r ON r.race_id = lt_a.race_id
    GROUP BY r.year, lt_a.race_id, r.name, lt_a.driver_id, lt_b.driver_id
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

-- Query Q5_GRAPH_TEAMMATE_SHORTEST_PATH
-- Objective: find the shortest teammate chain connecting Juan Manuel Fangio to Lando Norris, returning the full driver sequence where each hop means the two adjacent drivers were teammates in at least one race.
WITH RECURSIVE selected_drivers AS MATERIALIZED (
    SELECT
        MAX(driver_id) FILTER (WHERE forename = 'Juan' AND surname = 'Fangio') AS start_driver_id,
        MAX(driver_id) FILTER (WHERE forename = 'Lando' AND surname = 'Norris') AS target_driver_id
    FROM drivers
),
search AS (
    SELECT
        selected_drivers.start_driver_id AS current_driver_id,
        ARRAY[selected_drivers.start_driver_id] AS path,
        '|' || selected_drivers.start_driver_id::text || '|' AS visited_key,
        0 AS depth
    FROM selected_drivers
    UNION ALL
    SELECT
        edge.driver_b_id AS current_driver_id,
        search.path || edge.driver_b_id,
        search.visited_key || edge.driver_b_id::text || '|',
        search.depth + 1 AS depth
    FROM search
    JOIN teammate_edges AS edge ON edge.driver_a_id = search.current_driver_id
    CROSS JOIN selected_drivers
    WHERE search.depth < 8
      AND POSITION('|' || edge.driver_b_id::text || '|' IN search.visited_key) = 0
      AND search.current_driver_id <> selected_drivers.target_driver_id
),
shortest_path AS (
    SELECT search.path, search.depth
    FROM search
    CROSS JOIN selected_drivers
    WHERE search.current_driver_id = selected_drivers.target_driver_id
    ORDER BY search.depth
    LIMIT 1
)
SELECT
    shortest_path.depth AS teammate_hops,
    STRING_AGG(driver.forename || ' ' || driver.surname, ' -> ' ORDER BY path_nodes.ordinality) AS teammate_chain
FROM shortest_path
CROSS JOIN LATERAL UNNEST(shortest_path.path) WITH ORDINALITY AS path_nodes(driver_id, ordinality)
JOIN drivers AS driver ON driver.driver_id = path_nodes.driver_id
GROUP BY shortest_path.depth;

-- Query Q6_GRAPH_TEAMMATE_NEIGHBORHOOD_REACH
-- Objective: starting from Fernando Alonso, compute the shortest teammate-network distance to every distinct driver reachable within eight hops, producing a neighborhood distance map instead of a single target path.
WITH RECURSIVE selected_driver AS MATERIALIZED (
    SELECT driver_id AS start_driver_id
    FROM drivers
    WHERE driver_ref = 'alonso'
),
paths AS (
    SELECT
        selected_driver.start_driver_id AS current_driver_id,
        ARRAY[selected_driver.start_driver_id] AS path,
        '|' || selected_driver.start_driver_id::text || '|' AS visited_key,
        0 AS depth
    FROM selected_driver
    UNION ALL
    SELECT
        edge.driver_b_id AS current_driver_id,
        paths.path || edge.driver_b_id,
        paths.visited_key || edge.driver_b_id::text || '|',
        paths.depth + 1 AS depth
    FROM paths
    JOIN teammate_edges AS edge ON edge.driver_a_id = paths.current_driver_id
    CROSS JOIN selected_driver
    WHERE paths.depth < 8
      AND POSITION('|' || edge.driver_b_id::text || '|' IN paths.visited_key) = 0
      AND edge.driver_b_id <> selected_driver.start_driver_id
),
shortest_reach AS (
    SELECT
        current_driver_id,
        MIN(depth) AS min_hops
    FROM paths
    CROSS JOIN selected_driver
    WHERE current_driver_id <> selected_driver.start_driver_id
    GROUP BY current_driver_id
),
named_reach AS (
    SELECT
        reached.min_hops,
        driver.forename || ' ' || driver.surname AS driver_name
    FROM shortest_reach AS reached
    JOIN drivers AS driver ON driver.driver_id = reached.current_driver_id
)
SELECT
    COUNT(*) AS reachable_driver_count,
    MIN(min_hops) AS nearest_hops,
    MAX(min_hops) AS farthest_hops,
    ROUND(AVG(min_hops)::numeric, 2) AS avg_hops,
    ARRAY_TO_STRING((ARRAY_AGG(driver_name ORDER BY min_hops, driver_name))[1:25], ' | ') AS sample_reachable_drivers
FROM named_reach;

-- Query Q7_GRAPH_CONSTRUCTOR_DRIVER_BRIDGE
-- Objective: find the shortest constructor-driver bridge connecting Christensen to Manor Marussia, two constructors without a direct shared-driver bridge, so the result must traverse several alternating constructor and driver steps across eras.
WITH RECURSIVE selected_constructors AS MATERIALIZED (
    SELECT
        MAX(constructor_id) FILTER (WHERE constructor_ref = 'vhristensen') AS start_constructor_id,
        MAX(constructor_id) FILTER (WHERE constructor_ref = 'manor') AS target_constructor_id
    FROM constructors
),
search AS (
    SELECT
        'constructor'::text AS current_type,
        selected_constructors.start_constructor_id AS current_id,
        '|constructor:' || selected_constructors.start_constructor_id::text || '|' AS visited_key,
        ARRAY[(SELECT name FROM constructors WHERE constructor_id = selected_constructors.start_constructor_id)] AS path_names,
        0 AS depth
    FROM selected_constructors
    UNION ALL
    SELECT
        next_step.next_type AS current_type,
        next_step.next_id AS current_id,
        search.visited_key || next_step.next_key || '|',
        search.path_names || next_step.next_name,
        search.depth + 1 AS depth
    FROM search
    JOIN driver_constructor_edges AS edge
      ON (search.current_type = 'constructor' AND edge.constructor_id = search.current_id)
      OR (search.current_type = 'driver' AND edge.driver_id = search.current_id)
    LEFT JOIN drivers AS driver
      ON search.current_type = 'constructor'
     AND driver.driver_id = edge.driver_id
    LEFT JOIN constructors AS constructor
      ON search.current_type = 'driver'
     AND constructor.constructor_id = edge.constructor_id
    CROSS JOIN LATERAL (
        SELECT
            CASE WHEN search.current_type = 'constructor' THEN 'driver' ELSE 'constructor' END AS next_type,
            CASE WHEN search.current_type = 'constructor' THEN edge.driver_id ELSE edge.constructor_id END AS next_id,
            CASE
                WHEN search.current_type = 'constructor' THEN 'driver:' || edge.driver_id::text
                ELSE 'constructor:' || edge.constructor_id::text
            END AS next_key,
            CASE
                WHEN search.current_type = 'constructor' THEN driver.forename || ' ' || driver.surname
                ELSE constructor.name
            END AS next_name
    ) AS next_step
    WHERE search.depth < 10
      AND POSITION('|' || next_step.next_key || '|' IN search.visited_key) = 0
),
shortest_path AS (
    SELECT search.depth, search.path_names
    FROM search
    CROSS JOIN selected_constructors
    WHERE search.current_type = 'constructor'
      AND search.current_id = selected_constructors.target_constructor_id
      AND search.depth > 0
    ORDER BY search.depth
    LIMIT 1
)
SELECT
    shortest_path.depth AS relationship_hops,
    ARRAY_TO_STRING(shortest_path.path_names, ' -> ') AS constructor_driver_chain
FROM shortest_path;
