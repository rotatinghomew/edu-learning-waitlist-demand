import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from learning_waitlist_demand import report
from learning_waitlist_demand.analysis import demand_bounds, evaluate_offering
from learning_waitlist_demand.knowledge import (build_states, classify, committed,
                                                course_status, possible)
from learning_waitlist_demand.operations import evaluate_plan, verdict
from learning_waitlist_demand.records import read_courses, read_events
from learning_waitlist_demand.storage import fetch_courses, fetch_events, stage_records

DATA = Path(__file__).parent.parent / "data"
DECISION = "2026-04-30"
PRE_INTENT = "2026-04-14"    # 复开意向登记（04-15）之前
PRE_WITHDRAW = "2026-04-05"  # S25 候补退出（04-10）之前
PRE_ALTERNATES = "2026-04-11"  # P11 迟到备选（04-12）之前


def load(as_of=DECISION):
    with tempfile.TemporaryDirectory() as directory:
        db_path = Path(directory) / "test.db"
        stage_records(db_path, read_courses(DATA / "courses.csv"),
                      read_events(DATA / "events.csv"))
        courses = {row["course_id"]: row for row in fetch_courses(db_path)}
        events = fetch_events(db_path, as_of=as_of)
    return courses, events


def decision_fixture(as_of=DECISION):
    courses, events = load(as_of)
    states, cancelled = build_states(events)
    offered, _ = course_status(events)
    return courses, states, offered, cancelled


class RecordsTests(unittest.TestCase):
    def test_sample_data_loads(self):
        courses, events = load()
        self.assertEqual(len(courses), 8)
        self.assertEqual(len(events), 163)

    def test_missing_course_field_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad.csv"
            path.write_text("course_id,title,teacher,slot,min_enrollment\nC1,书法,王老师,周一上午,8\n",
                            encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "capacity"):
                read_courses(path)

    def test_missing_event_field_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad.csv"
            path.write_text("seq,date,event,learner_id,course_id\n1,2026-03-01,开放,,C1\n",
                            encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "detail"):
                read_events(path)

    def test_events_after_as_of_are_not_visible(self):
        _, events = load(PRE_INTENT)
        self.assertEqual(len(events), 154)  # 04-15 的 9 条意向登记不可见
        self.assertFalse(any(e["event"] == "意向登记" for e in events))


class KnowledgeTests(unittest.TestCase):
    def test_same_learner_in_seat_and_waitlist_counts_once(self):
        _, states, _, _ = decision_fixture()
        t01 = states["T01"]
        self.assertEqual(t01.seats, {"C3"})          # 正选 C3
        self.assertEqual(t01.waitlisted, ["C1"])     # 同时候补 C1
        self.assertEqual(committed(t01), {"C3", "C1"})  # 汇聚为一个人的两个口径

    def test_waitlist_withdrawal_respects_timeline(self):
        _, states_after, _, _ = decision_fixture(DECISION)
        self.assertNotIn("C1", committed(states_after["S25"]))
        _, states_before, _, _ = decision_fixture(PRE_WITHDRAW)
        self.assertIn("C1", committed(states_before["S25"]))

    def test_late_alternates_not_backdated(self):
        _, states_before, _, cancelled = decision_fixture(PRE_ALTERNATES)
        self.assertEqual(possible(states_before["P11"], cancelled), {"C5"})
        _, states_after, _, cancelled = decision_fixture(DECISION)
        self.assertEqual(possible(states_after["P11"], cancelled), {"C5", "C2", "C3"})

    def test_unshown_course_is_not_treated_as_disliked(self):
        # P11 的备选提交于 C5 停课后：备选名单没有 C5 不能解释为放弃 C5
        _, states, _, cancelled = decision_fixture()
        self.assertIn("C5", cancelled)
        self.assertIn("C5", possible(states["P11"], cancelled))

    def test_no_fabricated_preferences(self):
        # S25 从未留下备选：可能集合只有记录过的 C1，不编造其他课程
        _, states, _, cancelled = decision_fixture(PRE_WITHDRAW)
        s25 = states["S25"]
        self.assertIsNone(s25.alternates)
        self.assertEqual(possible(s25, cancelled), {"C1"})

    def test_schedule_conflict_displacement_is_recorded(self):
        _, states, _, cancelled = decision_fixture()
        t04 = states["T04"]
        self.assertEqual(t04.seats, {"C3"})
        self.assertEqual(t04.conflict_displaced, {"C6"})
        self.assertIn("C6", possible(t04, cancelled))

    def test_cancelled_waitlist_becomes_historical_evidence(self):
        # P18 曾候补 C5，停课后放弃：候补证据不因停课消失
        _, states, _, cancelled = decision_fixture()
        self.assertEqual(possible(states["P18"], cancelled), {"C5"})

    def test_classification_counts_each_learner_once(self):
        _, states, _, cancelled = decision_fixture()
        buckets = classify(states, cancelled)
        self.assertEqual(len(buckets["在册"]), 79)
        self.assertEqual(len(buckets["候补无座"]), 2)
        self.assertEqual(len(buckets["意向登记无座"]), 9)
        self.assertEqual(len(buckets["仅备选意向"]), 1)
        self.assertEqual(len(buckets["放弃或未表态"]), 8)
        self.assertEqual(len(buckets["已退出"]), 1)
        exclusive = (buckets["在册"] + buckets["候补无座"] + buckets["意向登记无座"]
                     + buckets["仅备选意向"] + buckets["放弃或未表态"] + buckets["已退出"])
        self.assertEqual(len(exclusive), len(set(exclusive)))


class AnalysisTests(unittest.TestCase):
    def test_demand_bounds(self):
        _, states, _, cancelled = decision_fixture()
        bounds = demand_bounds(states, cancelled, ["C1", "C5", "C6"])
        self.assertEqual((bounds["C6"]["lower"], bounds["C6"]["upper"]), (9, 11))
        self.assertEqual((bounds["C5"]["lower"], bounds["C5"]["upper"]), (0, 7))
        self.assertEqual((bounds["C1"]["lower"], bounds["C1"]["upper"]), (24, 25))

    def test_no_look_ahead_on_late_intent_registrations(self):
        _, states, _, cancelled = decision_fixture(PRE_INTENT)
        c6 = demand_bounds(states, cancelled, ["C6"])["C6"]
        self.assertEqual(c6["lower"], 0)   # 意向登记 04-15 才到达
        self.assertEqual(c6["upper"], 11)

    def test_reserved_seats_are_not_repromiseable(self):
        courses, states, offered, cancelled = decision_fixture()
        plan = evaluate_plan("测试", ("C5", "C6"), states, offered, cancelled, courses)
        c1 = plan["continuing"]["C1"]
        self.assertEqual(c1["reserved"], 20)  # 保留学位已锁定
        self.assertIn("S24", plan["unmet"])   # C1 可用学位为 0，候补者不能占用保留学位

    def test_joint_upper_is_not_sum_of_course_uppers(self):
        courses, states, offered, cancelled = decision_fixture()
        offering = sorted(offered) + ["C5", "C6"]
        bounds = demand_bounds(states, cancelled, offering)
        reserved = {cid: len(bounds[cid]["reserved"]) for cid in offering}
        available = {cid: courses[cid]["capacity"] - reserved[cid] for cid in offering}
        joint = evaluate_offering(states, cancelled, offering, available)
        sum_upper = sum(len(bounds[cid]["committed_extra"]) + len(bounds[cid]["possible_extra"])
                        for cid in offering)
        self.assertEqual(sum_upper, 30)
        self.assertEqual(joint["upper_total"], 19)  # 同一人只能兑现一次，且受容量约束
        self.assertLess(joint["upper_total"], sum_upper)

    def test_guaranteed_demand_survives_substitution(self):
        courses, states, offered, cancelled = decision_fixture()
        offering = sorted(offered) + ["C5", "C6"]
        available = {cid: courses[cid]["capacity"] - len(demand_bounds(states, cancelled, [cid])[cid]["reserved"])
                     for cid in offering}
        joint = evaluate_offering(states, cancelled, offering, available)
        self.assertEqual(joint["guaranteed"]["C6"], 9)  # 任意合理替代下都成立
        self.assertEqual(joint["guaranteed"]["C5"], 0)


class OperationsTests(unittest.TestCase):
    def test_plan_one_verdicts_and_deliverables(self):
        courses, states, offered, cancelled = decision_fixture()
        plan = evaluate_plan("方案一", ("C5", "C6"), states, offered, cancelled, courses)
        self.assertTrue(plan["feasible"])
        self.assertEqual(plan["courses"]["C6"]["verdict"], "可承诺")       # 确定 9 ≥ 成班线 8
        self.assertEqual(plan["courses"]["C5"]["verdict"], "需补充意向")   # 确定 0，可能 7
        self.assertEqual(plan["deliverable_guaranteed"], 9)
        self.assertEqual(plan["deliverable_upper"], 19)
        self.assertEqual(plan["unmet"], ["S24", "S26"])
        self.assertEqual(len(plan["unconfirmed"]), 8)

    def test_plan_two_flags_zero_evidence_course(self):
        courses, states, offered, cancelled = decision_fixture()
        plan = evaluate_plan("方案二", ("C6", "C7"), states, offered, cancelled, courses)
        self.assertTrue(plan["feasible"])
        self.assertEqual(plan["courses"]["C7"]["verdict"], "需补充意向（无记录）")
        self.assertEqual(len(plan["unconfirmed_nowhere"]), 6)  # C5 意向者在本方案内无去向

    def test_plan_three_rejected_by_teacher_slot_conflict(self):
        courses, states, offered, cancelled = decision_fixture()
        plan = evaluate_plan("方案三", ("C5", "C8"), states, offered, cancelled, courses)
        self.assertFalse(plan["feasible"])
        self.assertEqual(plan["conflicts"], [("C5", "C8", "陈老师", "周四上午")])

    def test_verdict_boundaries(self):
        self.assertEqual(verdict(8, 12, 8, True), "可承诺")
        self.assertEqual(verdict(5, 9, 8, True), "需补充意向")
        self.assertEqual(verdict(2, 5, 8, True), "不建议")
        self.assertEqual(verdict(0, 0, 8, False), "需补充意向（无记录）")

    def test_no_look_ahead_changes_plan_verdict(self):
        courses, states, offered, cancelled = decision_fixture(PRE_INTENT)
        plan = evaluate_plan("方案一", ("C5", "C6"), states, offered, cancelled, courses)
        self.assertEqual(plan["courses"]["C6"]["verdict"], "需补充意向")  # 意向登记尚未到达
        _, states, offered, cancelled = decision_fixture(DECISION)
        plan = evaluate_plan("方案一", ("C5", "C6"), states, offered, cancelled, courses)
        self.assertEqual(plan["courses"]["C6"]["verdict"], "可承诺")


class ReportTests(unittest.TestCase):
    def test_report_runs_and_marks_evidence_gaps(self):
        output = io.StringIO()
        with redirect_stdout(output):
            report.main()
        text = output.getvalue()
        self.assertIn("可承诺", text)
        self.assertIn("需补充意向", text)
        self.assertIn("不可行", text)
        self.assertIn("证据缺口", text)
        self.assertIn("时序纪律", text)


if __name__ == "__main__":
    unittest.main()
