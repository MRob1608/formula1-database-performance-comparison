// Changelog
// - Q1 now scans race winners plus lap_times pace context, forcing the query to use the largest table.
// - Q2 now builds round-by-round constructor standings from race and sprint points.
// - Q1 and Q2 now use DROVE_FOR / SPRINT_DROVE_FOR traversals instead of Constructor property lookups.
// - Q6 now maps Alonso's teammate-network distance to all drivers reachable within eight hops.
// - Q7 now uses Christensen -> Manor Marussia, a longer constructor-driver bridge verified in Neo4j.

// Query Q1_REL_YEARLY_WINNERS
// Objective: retrieve every race winner in Formula 1 history, enrich each win with lap-time pace context from the largest table, and keep cumulative career win counters for both the driver and constructor.
// Expected profile: favorable to PostgreSQL because Cypher must traverse lap-time relationships and derive analytic counters from collected graph rows.
MATCH (driver:Driver)-[result:RESULT]->(race:Race)
MATCH (driver)-[drive:DROVE_FOR]->(constructor:Constructor)
WHERE result.position_order = 1
  AND drive.result_id = result.result_id
OPTIONAL MATCH (lap_driver:Driver)-[lap_time:LAP_TIME]->(race)
WITH
    driver,
    result,
    race,
    constructor,
    count(lap_time.milliseconds) AS race_lap_records,
    count(CASE WHEN lap_driver.driver_id = driver.driver_id THEN lap_time.milliseconds END) AS winner_laps_recorded,
    avg(CASE WHEN lap_driver.driver_id = driver.driver_id THEN lap_time.milliseconds END) AS winner_avg_lap_ms,
    min(CASE WHEN lap_driver.driver_id = driver.driver_id THEN lap_time.milliseconds END) AS winner_best_lap_ms,
    avg(lap_time.milliseconds) AS race_avg_lap_ms
WITH collect({
    year: race.year,
    round: race.round,
    race_name: race.name,
    driver_id: driver.driver_id,
    winner: driver.forename + ' ' + driver.surname,
    constructor_id: constructor.constructor_id,
    constructor: constructor.name,
    winning_time: result.time,
    winner_laps_recorded: winner_laps_recorded,
    winner_avg_lap_ms: round(winner_avg_lap_ms * 100) / 100.0,
    winner_best_lap_ms: winner_best_lap_ms,
    race_avg_lap_ms: round(race_avg_lap_ms * 100) / 100.0,
    race_lap_records: race_lap_records
}) AS wins
UNWIND wins AS win
WITH
    win,
    [previous IN wins
     WHERE previous.driver_id = win.driver_id
       AND (previous.year < win.year OR (previous.year = win.year AND previous.round <= win.round))] AS driver_wins_to_date,
    [previous IN wins
     WHERE previous.constructor_id = win.constructor_id
       AND (previous.year < win.year OR (previous.year = win.year AND previous.round <= win.round))] AS constructor_wins_to_date
RETURN
    win.year AS year,
    win.round AS round,
    win.race_name AS race_name,
    win.winner AS winner,
    win.constructor AS constructor,
    win.winning_time AS winning_time,
    win.winner_laps_recorded AS winner_laps_recorded,
    win.winner_avg_lap_ms AS winner_avg_lap_ms,
    win.winner_best_lap_ms AS winner_best_lap_ms,
    win.race_avg_lap_ms AS race_avg_lap_ms,
    win.race_lap_records AS race_lap_records,
    size(driver_wins_to_date) AS driver_career_win_number,
    size(constructor_wins_to_date) AS constructor_career_win_number
ORDER BY year DESC, round DESC;

// Query Q2_REL_CONSTRUCTOR_POINTS_BY_SEASON
// Objective: rebuild the constructor standings after every championship round by combining race and sprint points, calculating each constructor's running season total, and ranking teams at each round.
// Expected profile: favorable to PostgreSQL because the workload is a tabular UNION-style aggregate with running totals and per-round ranking, while Cypher must assemble and rank grouped graph rows manually.
CALL {
    MATCH (driver:Driver)-[result:RESULT]->(race:Race)
    MATCH (driver)-[drive:DROVE_FOR]->(constructor:Constructor)
    WHERE drive.result_id = result.result_id
    RETURN
        race.year AS year,
        race.round AS round,
        race.race_id AS race_id,
        race.name AS race_name,
        constructor.constructor_id AS constructor_id,
        constructor.name AS constructor,
        result.points AS points,
        0 AS sprint_result_count
    UNION ALL
    MATCH (driver:Driver)-[result:SPRINT_RESULT]->(race:Race)
    MATCH (driver)-[drive:SPRINT_DROVE_FOR]->(constructor:Constructor)
    WHERE drive.result_id = result.result_id
    RETURN
        race.year AS year,
        race.round AS round,
        race.race_id AS race_id,
        race.name AS race_name,
        constructor.constructor_id AS constructor_id,
        constructor.name AS constructor,
        result.points AS points,
        1 AS sprint_result_count
}
WITH
    year,
    round,
    race_id,
    race_name,
    constructor_id,
    constructor,
    sum(points) AS round_points,
    count(*) AS classified_results,
    sum(sprint_result_count) AS sprint_results
WITH collect({
    year: year,
    round: round,
    race_id: race_id,
    race_name: race_name,
    constructor_id: constructor_id,
    constructor: constructor,
    round_points: round_points,
    classified_results: classified_results,
    sprint_results: sprint_results
}) AS rows
UNWIND rows AS row
WITH
    row,
    [previous IN rows
     WHERE previous.year = row.year
       AND previous.constructor_id = row.constructor_id
       AND previous.round <= row.round] AS previous_rounds
WITH row{.*, season_points_to_date: reduce(total = 0.0, previous IN previous_rounds | total + previous.round_points)} AS row
WITH collect(row) AS rows
UNWIND rows AS row
WITH
    row,
    [peer IN rows
     WHERE peer.year = row.year
       AND peer.round = row.round
       AND (
            peer.season_points_to_date > row.season_points_to_date
            OR (peer.season_points_to_date = row.season_points_to_date AND peer.constructor < row.constructor)
       )] AS better_rows
WHERE row.season_points_to_date > 0
RETURN
    row.year AS year,
    row.round AS round,
    row.race_name AS race_name,
    row.constructor AS constructor,
    row.round_points AS round_points,
    row.season_points_to_date AS season_points_to_date,
    size(better_rows) + 1 AS season_rank_after_round,
    row.classified_results AS classified_results,
    row.sprint_results AS sprint_results
ORDER BY year DESC, round DESC, season_rank_after_round ASC;

// Query Q3_REL_RACE_PACE_LAP_AGGREGATION
// Objective: compare average lap pace by driver and season across all recorded laps.
// Expected profile: favorable to PostgreSQL because it scans and aggregates the largest table with relational joins.
MATCH (driver:Driver)-[lap_time:LAP_TIME]->(race:Race)
WITH
    race.year AS year,
    driver,
    count(*) AS laps_recorded,
    round(avg(lap_time.milliseconds) * 100) / 100.0 AS avg_lap_ms,
    min(lap_time.milliseconds) AS best_lap_ms,
    max(lap_time.milliseconds) AS slowest_lap_ms
RETURN
    year,
    driver.forename + ' ' + driver.surname AS driver,
    laps_recorded,
    avg_lap_ms,
    best_lap_ms,
    slowest_lap_ms
ORDER BY year DESC, avg_lap_ms ASC;

// Query Q4_MIXED_LAP_BATTLE_AGGREGATION
// Objective: find driver pairs who were closely matched on the same laps of the same race.
// Expected profile: intermediate because both databases must aggregate many lap-level events.
MATCH (driver_a:Driver)-[lap_a:RECORDED_LAP]->(lap:RaceLap)<-[lap_b:RECORDED_LAP]-(driver_b:Driver)
WHERE driver_b.driver_id > driver_a.driver_id
  AND abs(lap_a.milliseconds - lap_b.milliseconds) <= 500
WITH
    lap.race_id AS race_id,
    lap.year AS year,
    lap.race_name AS race_name,
    driver_a,
    driver_b,
    count(*) AS close_laps,
    round(avg(abs(lap_a.milliseconds - lap_b.milliseconds)) * 100) / 100.0 AS avg_gap_ms
WHERE close_laps >= 10
RETURN
    year,
    race_name,
    driver_a.forename + ' ' + driver_a.surname AS driver_a,
    driver_b.forename + ' ' + driver_b.surname AS driver_b,
    close_laps,
    avg_gap_ms
ORDER BY close_laps DESC, avg_gap_ms ASC
LIMIT 100;

// Query Q5_GRAPH_TEAMMATE_SHORTEST_PATH
// Objective: find the shortest teammate chain connecting Juan Manuel Fangio to Lando Norris, returning the full driver sequence where each hop means the two adjacent drivers were teammates in at least one race.
// Expected profile: strongly favorable to Neo4j because TEAMMATE_WITH is a materialized graph relationship and shortestPath can traverse adjacency directly.
MATCH (fangio:Driver {forename: 'Juan', surname: 'Fangio'})
MATCH (norris:Driver {forename: 'Lando', surname: 'Norris'})
MATCH path = shortestPath((fangio)-[:TEAMMATE_WITH*..8]-(norris))
RETURN
    length(path) AS teammate_hops,
    reduce(chain = '', driver IN nodes(path) |
        chain + CASE WHEN chain = '' THEN '' ELSE ' -> ' END + driver.forename + ' ' + driver.surname
    ) AS teammate_chain;

// Query Q6_GRAPH_TEAMMATE_NEIGHBORHOOD_REACH
// Objective: starting from Fernando Alonso, compute the shortest teammate-network distance to every distinct driver reachable within eight hops, producing a neighborhood distance map instead of a single target path.
// Expected profile: favorable to Neo4j because shortest path expansion to many targets runs over native adjacency, while PostgreSQL must recursively expand simple paths and deduplicate distances.
MATCH (start:Driver {driver_ref: 'alonso'})
MATCH (other:Driver)
WHERE other.driver_id <> start.driver_id
MATCH path = shortestPath((start)-[:TEAMMATE_WITH*..8]-(other))
WITH other, length(path) AS min_hops
WHERE min_hops IS NOT NULL
WITH
    min_hops,
    other.forename + ' ' + other.surname AS driver_name
ORDER BY min_hops, driver_name
WITH
    count(*) AS reachable_driver_count,
    min(min_hops) AS nearest_hops,
    max(min_hops) AS farthest_hops,
    round(avg(min_hops) * 100) / 100.0 AS avg_hops,
    collect(driver_name)[0..25] AS sample_reachable_drivers
RETURN
    reachable_driver_count,
    nearest_hops,
    farthest_hops,
    avg_hops,
    reduce(sample = '', driver IN sample_reachable_drivers |
        sample + CASE WHEN sample = '' THEN '' ELSE ' | ' END + driver
    ) AS sample_reachable_drivers;

// Query Q7_GRAPH_CONSTRUCTOR_DRIVER_BRIDGE
// Objective: find the shortest constructor-driver bridge connecting Christensen to Manor Marussia, two constructors without a direct shared-driver bridge, so the result must traverse several alternating constructor and driver steps across eras.
// Expected profile: favorable to Neo4j because this is a bipartite path traversal over materialized DROVE_FOR relationships.
MATCH (start:Constructor {constructor_ref: 'vhristensen'})
MATCH (target:Constructor {constructor_ref: 'manor'})
MATCH path = shortestPath((start)-[:DROVE_FOR*..10]-(target))
RETURN
    length(path) AS relationship_hops,
    reduce(chain = '', node IN nodes(path) |
        chain + CASE WHEN chain = '' THEN '' ELSE ' -> ' END + coalesce(node.name, node.forename + ' ' + node.surname)
    ) AS constructor_driver_chain;
