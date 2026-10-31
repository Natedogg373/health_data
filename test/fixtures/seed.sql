INSERT INTO user_profile (id, date_of_birth, biological_sex, blood_type, export_date)
VALUES (1, '1990-05-01', 'HKBiologicalSexMale', 'HKBloodTypeOPositive', '2026-01-15 12:00:00 -0500');

INSERT INTO sources (id, name, version) VALUES (1, 'Apple Watch', '11.0');

INSERT INTO workouts (
  id, activity_type, start_at, end_at, start_date_local, local_date,
  duration_sec, distance_m, energy_kcal, source_id, device, route_file, creation_date
) VALUES
  (
    'run001',
    'HKWorkoutActivityTypeRunning',
    '2026-01-10T12:00:00+00:00',
    '2026-01-10T12:32:00+00:00',
    '2026-01-10 07:00:00 -0500',
    '2026-01-10',
    1920,
    5000,
    380,
    1,
    'Watch',
    'route_2026-01-10_7.00am.gpx',
    '2026-01-10 07:32:00 -0500'
  ),
  (
    'run002',
    'HKWorkoutActivityTypeRunning',
    '2026-01-12T13:00:00+00:00',
    '2026-01-12T13:45:00+00:00',
    '2026-01-12 08:00:00 -0500',
    '2026-01-12',
    2700,
    8046.72,
    520,
    1,
    'Watch',
    NULL,
    '2026-01-12 08:45:00 -0500'
  ),
  (
    'walk001',
    'HKWorkoutActivityTypeWalking',
    '2026-01-11T15:00:00+00:00',
    '2026-01-11T15:40:00+00:00',
    '2026-01-11 10:00:00 -0500',
    '2026-01-11',
    2400,
    3200,
    140,
    1,
    'Watch',
    NULL,
    '2026-01-11 10:40:00 -0500'
  );

INSERT INTO workout_statistics (
  workout_id, stat_type, start_at, end_at, sum_value, avg_value, min_value, max_value, unit
) VALUES
  ('run001', 'HKQuantityTypeIdentifierHeartRate', NULL, NULL, NULL, 148, 122, 172, 'count/min'),
  ('run002', 'HKQuantityTypeIdentifierHeartRate', NULL, NULL, NULL, 151, 128, 176, 'count/min');

INSERT INTO workout_metadata (workout_id, key, value)
VALUES ('run001', 'HKIndoorWorkout', '0');

INSERT INTO routes (
  workout_id, gpx_filename, point_count, distance_m, elev_gain_m, duration_sec, avg_speed_mps, max_speed_mps
) VALUES (
  'run001', 'route_2026-01-10_7.00am.gpx', 12, 4980, 42.5, 1900, 2.62, 3.4
);

INSERT INTO daily_metrics (
  local_date, resting_hr, hrv_sdnn, vo2_max, body_mass_kg,
  sleep_total_min, sleep_deep_min, sleep_rem_min, sleep_core_min, sleep_awake_min,
  steps, active_energy_kcal, workout_count, run_count, run_distance_m, run_duration_sec
) VALUES
  ('2026-01-10', 52, 46, 48.2, 75.0, 430, 70, 90, 250, 20, 9800, 620, 1, 1, 5000, 1920),
  ('2026-01-11', 54, 41, 48.2, 75.1, 400, 60, 80, 240, 20, 7200, 410, 1, 0, 0, 0),
  ('2026-01-12', 51, 49, 48.4, 74.8, 450, 80, 95, 255, 20, 11000, 700, 1, 1, 8046.72, 2700);

INSERT INTO activity_summaries (
  date_components, local_date, active_energy_kcal, active_energy_goal,
  exercise_min, exercise_goal, stand_hours, stand_goal
) VALUES
  ('2026-01-10 00:00:00 -0500', '2026-01-10', 620, 600, 40, 30, 11, 12),
  ('2026-01-12 00:00:00 -0500', '2026-01-12', 700, 600, 50, 30, 12, 12);

INSERT INTO import_runs (started_at, finished_at, export_xml_path, records_parsed, workouts_parsed)
VALUES ('2026-01-15T12:00:00+00:00', '2026-01-15T12:05:00+00:00', '/tmp/export.xml', 12, 3);
