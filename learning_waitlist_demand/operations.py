def review(summary, minimum_count=1):
    return [{**row, "review": "可查看" if row["count"] >= minimum_count else "资料不足"}
            for row in summary]
