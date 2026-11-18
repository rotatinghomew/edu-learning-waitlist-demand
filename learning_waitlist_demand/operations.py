"""复开方案评估：教师时段互斥、最低成班人数、保留学位回查。

数据支撑不了开班承诺时给出"需补充意向"，不产出看似精确的预测数。
"""
from .analysis import evaluate_offering
from .knowledge import committed, possible

VERDICT_OK = "可承诺"
VERDICT_NEED_MORE = "需补充意向"
VERDICT_NO_EVIDENCE = "需补充意向（无记录）"
VERDICT_NOT_ADVISED = "不建议"


def verdict(guaranteed, upper, minimum, has_evidence):
    """开班结论：保证需求过线才可承诺；上界过线但保证不足时留待补充意向。"""
    if guaranteed >= minimum:
        return VERDICT_OK
    if upper >= minimum:
        return VERDICT_NEED_MORE
    if has_evidence:
        return VERDICT_NOT_ADVISED
    return VERDICT_NO_EVIDENCE


def teacher_slot_conflicts(course_ids, courses):
    """同一教师同一时段只能开一门课。"""
    seen = {}
    conflicts = []
    for cid in course_ids:
        key = (courses[cid]["teacher"], courses[cid]["slot"])
        if key in seen:
            conflicts.append((seen[key], cid, key[0], key[1]))
        else:
            seen[key] = cid
    return conflicts


def evaluate_plan(name, candidate_ids, states, offered, cancelled, courses):
    """评估一个复开方案（在办课程自动包含在内，其保留学位已锁定）。"""
    offering = sorted(offered) + [cid for cid in candidate_ids if cid not in offered]
    conflicts = teacher_slot_conflicts(offering, courses)
    if conflicts:
        return {"name": name, "candidates": list(candidate_ids),
                "feasible": False, "conflicts": conflicts}

    reserved = {cid: 0 for cid in courses}
    for state in states.values():
        for seat in state.seats:
            reserved[seat] += 1
    available = {cid: courses[cid]["capacity"] - reserved.get(cid, 0) for cid in offering}

    joint = evaluate_offering(states, cancelled, offering, available)

    candidate_rows = {}
    for cid in candidate_ids:
        guaranteed = joint["guaranteed"].get(cid, 0)
        upper = guaranteed + sum(1 for options in joint["possible_options"].values() if cid in options)
        candidate_rows[cid] = {
            "guaranteed": guaranteed,
            "upper": upper,
            "available": available[cid],
            "min_enrollment": courses[cid]["min_enrollment"],
            "verdict": verdict(guaranteed, upper, courses[cid]["min_enrollment"], upper > 0),
        }

    continuing_rows = {
        cid: {"reserved": reserved[cid],
              "min_enrollment": courses[cid]["min_enrollment"],
              "ok": reserved[cid] >= courses[cid]["min_enrollment"]}
        for cid in sorted(offered)
    }

    unconfirmed = sorted(
        state.learner_id for state in states.values()
        if not state.seats and not committed(state)
        and not state.alternates and possible(state, cancelled)
    )
    offering_set = set(offering)
    unconfirmed_nowhere = [
        lid for lid in unconfirmed
        if not (possible(states[lid], cancelled) & offering_set)
    ]

    return {
        "name": name,
        "candidates": list(candidate_ids),
        "feasible": True,
        "conflicts": [],
        "courses": candidate_rows,
        "continuing": continuing_rows,
        "deliverable_guaranteed": sum(
            min(row["guaranteed"], row["available"]) for row in candidate_rows.values()),
        "deliverable_upper": joint["committed_assigned"] + joint["possible_assigned"],
        "unmet": joint["unmet_committed"],
        "unconfirmed": unconfirmed,
        "unconfirmed_nowhere": unconfirmed_nowhere,
        "joint": joint,
    }
