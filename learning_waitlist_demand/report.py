import tempfile
from pathlib import Path

from .analysis import summarize
from .operations import review
from .records import read_records
from .storage import replace_records


def main():
    data = Path(__file__).parent.parent / "data" / "observations.csv"
    rows = read_records(data)
    with tempfile.TemporaryDirectory() as directory:
        stored = replace_records(Path(directory) / "observations.db", rows)
        rows = [{"period": period, "group": group, "count": count, "value": value}
                for period, group, count, value in stored]
    for row in review(summarize(rows)):
        print(f"{row['period']} {row['group']}: {row['count']} 条，均值 {row['mean']:.2f}，{row['review']}")


if __name__ == "__main__":
    main()
