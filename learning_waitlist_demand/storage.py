import sqlite3

def stage_records(db_path, courses, events):
    """把 CSV 记录装入 SQLite，原始 CSV 保持不变。"""
    with sqlite3.connect(db_path) as connection:
        connection.execute("CREATE TABLE IF NOT EXISTS courses (course_id TEXT, title TEXT, teacher TEXT, slot TEXT, capacity INTEGER, min_enrollment INTEGER)")
        connection.execute("CREATE TABLE IF NOT EXISTS events (seq INTEGER, date TEXT, event TEXT, learner_id TEXT, course_id TEXT, detail TEXT)")
        connection.execute("DELETE FROM courses")
        connection.execute("DELETE FROM events")
        connection.executemany(
            "INSERT INTO courses VALUES (?, ?, ?, ?, ?, ?)",
            [(c["course_id"], c["title"], c["teacher"], c["slot"], c["capacity"], c["min_enrollment"])
             for c in courses])
        connection.executemany(
            "INSERT INTO events VALUES (?, ?, ?, ?, ?, ?)",
            [(e["seq"], e["date"], e["event"], e["learner_id"], e["course_id"], e["detail"])
             for e in events])


def fetch_courses(db_path):
    with sqlite3.connect(db_path) as connection:
        rows = connection.execute(
            "SELECT course_id, title, teacher, slot, capacity, min_enrollment FROM courses ORDER BY course_id"
        ).fetchall()
    keys = ("course_id", "title", "teacher", "slot", "capacity", "min_enrollment")
    return [dict(zip(keys, row)) for row in rows]


def fetch_events(db_path, as_of=None):
    """取出截至 as_of（含）已知的事件；之后的记录不得进入分析。"""
    sql = "SELECT seq, date, event, learner_id, course_id, detail FROM events"
    params = ()
    if as_of is not None:
        sql += " WHERE date <= ?"
        params = (as_of,)
    sql += " ORDER BY seq"
    with sqlite3.connect(db_path) as connection:
        rows = connection.execute(sql, params).fetchall()
    keys = ("seq", "date", "event", "learner_id", "course_id", "detail")
    return [dict(zip(keys, row)) for row in rows]
