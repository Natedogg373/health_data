from parse.db import get_connection

c = get_connection()
runs = c.execute(
    "SELECT COUNT(*), ROUND(SUM(distance_m)/1609.344,1) FROM workouts WHERE activity_type='HKWorkoutActivityTypeRunning'"
).fetchone()
print(f"Runs: {runs[0]}, total miles: {runs[1]}")
print(f"Workout stats: {c.execute('SELECT COUNT(*) FROM workout_statistics').fetchone()[0]}")
print(f"Routes linked: {c.execute('SELECT COUNT(*) FROM routes WHERE workout_id IS NOT NULL').fetchone()[0]}/265")
