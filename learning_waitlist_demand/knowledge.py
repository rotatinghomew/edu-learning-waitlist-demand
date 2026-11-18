"""按事件流重放，得到每位学员在分析截止日可确认的知识状态。

原则：
- 同一学员的正选与候补记录只汇聚成一个人，绝不重复计数；
- 备选意向只增加可接受的课程，不会移除历史选择——提交备选时未展示
  （停课/未开放）的课程不出现在名单中，不能解释为不喜欢；
- 没有留下备选次序的学员不编造偏好，其可能集合只含记录过的课程。
"""
from dataclasses import dataclass, field

ENROLL = "报名"
WAITLIST = "候补"
ALTERNATES = "备选"
DROP = "退课"
WAITLIST_DROP = "候补退出"
CANCEL = "停课"
TRANSFER = "转班"
GIVE_UP = "放弃"
OPEN = "开放"
REOPEN = "复开"
INTENT = "意向登记"

CONFLICT_DETAIL = "时段冲突"


@dataclass
class LearnerState:
    learner_id: str
    seats: set = field(default_factory=set)          # 当前持有的学位（正选/转班）
    waitlisted: list = field(default_factory=list)   # 活跃候补（被满额挤走的选择）
    alternates: list | None = None                   # 备选次序；None 表示从未提供
    intents: set = field(default_factory=set)        # 复开意向登记
    gave_up: bool = False                            # 停课后明确放弃
    historical_seats: set = field(default_factory=set)  # 曾持有过的学位
    historical_waitlists: set = field(default_factory=set)  # 因停课中断的候补
    conflict_displaced: set = field(default_factory=set)  # 因时段冲突被挤走的课程


def build_states(events):
    """重放事件，返回 (学员状态表, 截至目前的停课课程集合)。"""
    states = {}
    cancelled = set()

    def learner(learner_id):
        if learner_id not in states:
            states[learner_id] = LearnerState(learner_id=learner_id)
        return states[learner_id]

    for event in events:
        kind = event["event"]
        lid = event["learner_id"]
        cid = event["course_id"]
        if kind in (OPEN, REOPEN):
            cancelled.discard(cid)
        elif kind == CANCEL:
            cancelled.add(cid)
            for state in states.values():
                state.seats.discard(cid)
                if cid in state.waitlisted:
                    # 停课中断的候补转为历史证据：是课程没了，不是学员改主意
                    state.waitlisted.remove(cid)
                    state.historical_waitlists.add(cid)
                state.intents.discard(cid)
        elif kind in (ENROLL, TRANSFER):
            state = learner(lid)
            state.seats.add(cid)
            state.historical_seats.add(cid)
            state.gave_up = False
        elif kind == WAITLIST:
            state = learner(lid)
            if cid not in state.waitlisted:
                state.waitlisted.append(cid)
            state.gave_up = False
        elif kind == ALTERNATES:
            state = learner(lid)
            state.alternates = [c for c in event["detail"].split(">") if c]
            state.gave_up = False
        elif kind == INTENT:
            state = learner(lid)
            state.intents.add(cid)
            state.gave_up = False
        elif kind == DROP:
            state = learner(lid)
            state.seats.discard(cid)
            if event["detail"] == CONFLICT_DETAIL:
                state.conflict_displaced.add(cid)
        elif kind == WAITLIST_DROP:
            state = learner(lid)
            if cid in state.waitlisted:
                state.waitlisted.remove(cid)
        elif kind == GIVE_UP:
            state = learner(lid)
            state.seats.clear()
            state.waitlisted.clear()
            state.intents.clear()
            state.gave_up = True
    return states, cancelled


def course_status(events):
    """返回 (当前在办课程, 当前停课课程)。"""
    offered, cancelled = set(), set()
    for event in events:
        if event["event"] in (OPEN, REOPEN):
            offered.add(event["course_id"])
            cancelled.discard(event["course_id"])
        elif event["event"] == CANCEL:
            offered.discard(event["course_id"])
            cancelled.add(event["course_id"])
    return offered, cancelled


def committed(state):
    """确定的选择：持有学位、活跃候补、已登记意向。"""
    return set(state.seats) | set(state.waitlisted) | set(state.intents)


def possible(state, cancelled):
    """兼容偏好集合：确定选择 + 有记录的备选 + 无法辨认去向的历史选择。

    只有在学员当前没有学位时，其历史选择（已停课）才计入可能集合——
    已转班者已作出新的确定选择，不替他们假设会回流。
    """
    pool = committed(state) | set(state.conflict_displaced)
    if state.alternates:
        pool |= set(state.alternates)
    if not state.seats:
        pool |= (state.historical_seats | state.historical_waitlists) & cancelled
    return pool


def classify(states, cancelled):
    """把学员分到互斥的口径桶，同一人只计一次（在册者另标注候补/冲突）。"""
    buckets = {
        "在册": [],
        "在册且候补未满足": [],
        "候补无座": [],
        "意向登记无座": [],
        "仅备选意向": [],
        "放弃或未表态": [],
        "已退出": [],
        "时段冲突挤走": [],
    }
    for state in states.values():
        lid = state.learner_id
        if state.seats:
            buckets["在册"].append(lid)
            if state.waitlisted:
                buckets["在册且候补未满足"].append(lid)
        elif state.waitlisted:
            buckets["候补无座"].append(lid)
        elif state.intents:
            buckets["意向登记无座"].append(lid)
        elif state.alternates:
            buckets["仅备选意向"].append(lid)
        elif state.gave_up or ((state.historical_seats | state.historical_waitlists) & cancelled):
            buckets["放弃或未表态"].append(lid)
        else:
            buckets["已退出"].append(lid)
        if state.conflict_displaced:
            buckets["时段冲突挤走"].append(lid)
    return buckets
