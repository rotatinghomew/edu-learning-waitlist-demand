"""课程需求区间与复开方案评估报告。

分析只使用截止日之前已知的事件；之后才到达的信息（候补退出、
迟到的备选、复开意向登记）不伪装成当时已知事实。
"""
import tempfile
from pathlib import Path

from .analysis import demand_bounds, evaluate_offering
from .knowledge import build_states, classify, course_status
from .operations import evaluate_plan
from .records import read_courses, read_events
from .storage import fetch_courses, fetch_events, stage_records

DECISION_DATE = "2026-04-30"
PRE_INTENT_DATE = "2026-04-14"   # 复开意向登记（04-15）之前
PRE_WITHDRAW_DATE = "2026-04-05"  # S25 候补退出（04-10）之前

PLANS = [
    ("方案一", ("C5", "C6")),
    ("方案二", ("C6", "C7")),
    ("方案三", ("C5", "C8")),
]


def _ids(learner_ids, limit=9):
    ids = sorted(learner_ids)
    if len(ids) <= limit:
        return "、".join(ids)
    return "、".join(ids[:limit]) + f" 等 {len(ids)} 人"


def main():
    base = Path(__file__).resolve().parent.parent
    with tempfile.TemporaryDirectory() as directory:
        db_path = Path(directory) / "demand.db"
        stage_records(db_path, read_courses(base / "data" / "courses.csv"),
                      read_events(base / "data" / "events.csv"))
        courses = {row["course_id"]: row for row in fetch_courses(db_path)}
        events = fetch_events(db_path, as_of=DECISION_DATE)
        events_pre_intent = fetch_events(db_path, as_of=PRE_INTENT_DATE)
        events_pre_withdraw = fetch_events(db_path, as_of=PRE_WITHDRAW_DATE)

    states, cancelled = build_states(events)
    offered, _ = course_status(events)
    buckets = classify(states, cancelled)
    bounds = demand_bounds(states, cancelled, courses.keys())

    lines = []
    lines.append(f"课程需求区间与复开方案评估（分析截止 {DECISION_DATE}）")
    lines.append("=" * 46)

    lines.append("")
    lines.append("一、记录概览")
    lines.append(f"  课程 {len(courses)} 门：在办 {len(offered)} 门（{'、'.join(sorted(offered))}），"
                 f"停课 {len(cancelled)} 门（{'、'.join(sorted(cancelled))}），"
                 f"其余为拟新开课程")
    lines.append(f"  学员 {len(states)} 人，事件 {len(events)} 条"
                 f"（{events[0]['date']} 至 {events[-1]['date']}）")

    lines.append("")
    lines.append("二、学员分类（同一学员只计一次）")
    lines.append(f"  在册（学位已确认）…… {len(buckets['在册'])} 人"
                 f"（其中 {len(buckets['在册且候补未满足'])} 人候补他课未满足，"
                 f"{len(buckets['时段冲突挤走'])} 人曾被时段冲突挤走）")
    lines.append(f"  候补无座（被满额挤走）…… {len(buckets['候补无座'])} 人：{_ids(buckets['候补无座'])}")
    lines.append(f"  停课后登记复开意向…… {len(buckets['意向登记无座'])} 人：{_ids(buckets['意向登记无座'])}")
    lines.append(f"  仅留备选意向（无座）…… {len(buckets['仅备选意向'])} 人：{_ids(buckets['仅备选意向'])}")
    lines.append(f"  放弃或未表态（替代关系无法辨认）…… {len(buckets['放弃或未表态'])} 人："
                 f"{_ids(buckets['放弃或未表态'])}")
    lines.append(f"  已退出（无有效记录）…… {len(buckets['已退出'])} 人：{_ids(buckets['已退出'])}")

    lines.append("")
    lines.append("三、课程需求区间（下界＝确定需求，上界＝含可能需求）")
    lines.append(f"  {'课程':<6}{'保留学位':>6}{'确定新增':>6}{'可能新增':>6}   需求区间")
    for cid in sorted(courses):
        row = bounds[cid]
        new_lower = len(row["committed_extra"])
        new_upper = len(row["possible_extra"])
        lines.append(f"  {cid:<6}{len(row['reserved']):>6}{new_lower:>6}{new_upper:>6}   "
                     f"{row['lower']}–{row['upper']}")
    c1 = bounds["C1"]
    seated_waiters = [lid for lid in c1["committed_extra"] if lid in buckets["在册且候补未满足"]]
    lines.append(f"  说明：C1 确定新增 {len(c1['committed_extra'])} 人中 {len(seated_waiters)} 人"
                 f"正选他课（候补占座：{_ids(seated_waiters)}），不是两个需求。")
    lines.append("  说明：P11 的备选提交于 C5 停课后，C5 当时未展示，未列入备选"
                 "不能解释为放弃 C5，C5 仍计入其可能集合。")

    joint_offering = sorted(offered) + ["C5", "C6"]
    reserved = {cid: len(bounds[cid]["reserved"]) for cid in joint_offering}
    available = {cid: courses[cid]["capacity"] - reserved[cid] for cid in joint_offering}
    joint = evaluate_offering(states, cancelled, joint_offering, available)
    sum_upper = sum(len(bounds[cid]["committed_extra"]) + len(bounds[cid]["possible_extra"])
                    for cid in joint_offering)

    lines.append("")
    lines.append("四、联合需求（各课上界不能相加）")
    lines.append(f"  各课新增上界之和 {sum_upper} 人，联合可同时成立的新增上限 "
                 f"{joint['upper_total']} 人。")
    lines.append("  原因：同一学员出现在多门课的可能集合中只能兑现一次；"
                 f"C2 仅剩 {available['C2']} 个可用学位。")
    c6_committed = [lid for lid, options in joint["committed_options"].items()
                    if options == {"C6"}]
    lines.append(f"  联合确定新增 {joint['committed_assigned']} 人"
                 f"（{_ids(c6_committed)} → C6），"
                 f"其余 {joint['possible_assigned']} 个上限名额取决于未确认意向。")

    lines.append("")
    lines.append("五、复开方案比较（在办课程保留学位已锁定，不再承诺给候补者）")
    for plan_name, candidate_ids in PLANS:
        plan = evaluate_plan(plan_name, candidate_ids, states, offered, cancelled, courses)
        titles = "、".join(f"{cid} {courses[cid]['title']}" for cid in candidate_ids)
        lines.append(f"  {plan['name']}：复开 {titles}")
        if not plan["feasible"]:
            for first, second, teacher, slot in plan["conflicts"]:
                lines.append(f"    不可行：{first} 与 {second} 同为{teacher}{slot}，教师时段冲突")
            continue
        for cid, row in plan["courses"].items():
            lines.append(f"    {cid}：{row['verdict']}"
                         f"（确定 {row['guaranteed']}，可能 {row['upper']}，"
                         f"成班线 {row['min_enrollment']}，可用学位 {row['available']}）")
        lines.append(f"    可兑现新增学位：确定 {plan['deliverable_guaranteed']}，"
                     f"乐观上限 {plan['deliverable_upper']}；"
                     f"可能仍落空 {len(plan['unmet'])} 人（{_ids(plan['unmet'])}）；"
                     f"证据缺口 {len(plan['unconfirmed'])} 人意向未确认"
                     + (f"，其中 {len(plan['unconfirmed_nowhere'])} 人在本方案内无去向"
                        if plan["unconfirmed_nowhere"] else ""))

    states_pre, cancelled_pre = build_states(events_pre_intent)
    c6_pre = demand_bounds(states_pre, cancelled_pre, ["C6"])["C6"]
    states_early, _ = build_states(events_pre_withdraw)
    c1_early = demand_bounds(states_early, cancelled, ["C1"])["C1"]

    lines.append("")
    lines.append("六、时序纪律")
    lines.append(f"  本分析只使用 {DECISION_DATE} 及之前的记录。")
    lines.append(f"  若截止 {PRE_INTENT_DATE}：C6 确定需求为 {c6_pre['lower']}"
                 f"（复开意向 04-15 才登记），只能判“需补充意向”。")
    lines.append(f"  S25 于 04-10 退出候补：{PRE_WITHDRAW_DATE} 前的分析计入 C1 需求"
                 f"（当时确定新增 {len(c1_early['committed_extra'])} 人），之后不计。")

    print("\n".join(lines))


if __name__ == "__main__":
    main()
