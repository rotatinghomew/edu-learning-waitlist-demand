import csv
from pathlib import Path

COURSE_FIELDS = ("course_id", "title", "teacher", "slot", "capacity", "min_enrollment")
EVENT_FIELDS = ("seq", "date", "event", "learner_id", "course_id", "detail")


def _read_csv(path, required):
    with Path(path).open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    if not rows:
        return []
    missing = set(required) - set(rows[0])
    if missing:
        raise ValueError(f"缺少字段: {', '.join(sorted(missing))}")
    return rows


def read_courses(path):
    """读取课程静态属性：教师、时段、容量、最低成班人数。"""
    courses = []
    for row in _read_csv(path, COURSE_FIELDS):
        courses.append({
            "course_id": row["course_id"].strip(),
            "title": row["title"].strip(),
            "teacher": row["teacher"].strip(),
            "slot": row["slot"].strip(),
            "capacity": int(row["capacity"]),
            "min_enrollment": int(row["min_enrollment"]),
        })
    return courses


def read_events(path):
    """读取带时间的事件流，按 seq 排序保证重放顺序。"""
    events = []
    for row in _read_csv(path, EVENT_FIELDS):
        events.append({
            "seq": int(row["seq"]),
            "date": row["date"].strip(),
            "event": row["event"].strip(),
            "learner_id": row["learner_id"].strip(),
            "course_id": row["course_id"].strip(),
            "detail": row["detail"].strip(),
        })
    events.sort(key=lambda event: event["seq"])
    return events
