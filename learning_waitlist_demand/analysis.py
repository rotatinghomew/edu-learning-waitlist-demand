from collections import defaultdict


def summarize(rows):
    grouped = defaultdict(list)
    for row in rows:
        grouped[(row["period"], row["group"])].append(row)
    result = []
    for (period, group), members in sorted(grouped.items()):
        count = sum(int(row["count"]) for row in members)
        values = [float(row["value"]) for row in members]
        result.append({"period": period, "group": group, "count": count,
                       "mean": sum(values) / len(values) if values else None})
    return result
