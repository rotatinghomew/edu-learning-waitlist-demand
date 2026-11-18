import tempfile
import unittest
from pathlib import Path

from learning_waitlist_demand.analysis import summarize
from learning_waitlist_demand.operations import review
from learning_waitlist_demand.records import read_records


class WorkflowTests(unittest.TestCase):
    def test_sample_records_flow_through_summary_and_review(self):
        path = Path(__file__).parent.parent / "data" / "observations.csv"
        summary = summarize(read_records(path))
        reviewed = review(summary, minimum_count=6)
        self.assertEqual(len(summary), 4)
        self.assertEqual(sum(row["count"] for row in summary), 29)
        self.assertEqual([row["review"] for row in reviewed].count("资料不足"), 1)

    def test_missing_business_field_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad.csv"
            path.write_text("period,group,count\n2026-S1,甲,2\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "value"):
                read_records(path)


if __name__ == "__main__":
    unittest.main()
