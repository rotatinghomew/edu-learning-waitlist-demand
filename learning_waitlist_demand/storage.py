import sqlite3


def replace_records(path, rows):
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE IF NOT EXISTS observations (period TEXT, group_name TEXT, count INTEGER, value REAL)")
        connection.execute("DELETE FROM observations")
        connection.executemany("INSERT INTO observations VALUES (?, ?, ?, ?)",
                               [(row["period"], row["group"], int(row["count"]), float(row["value"]))
                                for row in rows])
        return connection.execute("SELECT period, group_name, count, value FROM observations ORDER BY period, group_name").fetchall()
