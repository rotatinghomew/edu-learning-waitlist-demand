import csv
from pathlib import Path


def read_records(path):
    with Path(path).open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    if not rows:
        return []
    required = {"period", "group", "count", "value"}
    missing = required - set(rows[0])
    if missing:
        raise ValueError(f"缺少字段: {', '.join(sorted(missing))}")
    return rows
