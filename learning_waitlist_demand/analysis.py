"""需求上下界与联合需求可行性。

单课上下界只说明"有哪些人可能来"；联合分析用最大流回答"这些需求
能否同时成立"，避免把各课分别算出的最大值拼成一个不可能存在的人群。
"""
from collections import deque

from .knowledge import committed, possible

SOURCE = "__source__"
SINK = "__sink__"


def demand_bounds(states, cancelled, course_ids):
    """每门课的需求区间：保留学位、确定新增、可能新增（同一学员在一门课内只计一次）。

    可能新增只统计当前无学位的学员；在册者的转入倾向属于未辨认信息，
    在学员分类中单独标注，不进上下界。
    """
    bounds = {}
    for cid in course_ids:
        reserved, committed_extra, possible_extra = [], [], []
        for state in states.values():
            if cid in state.seats:
                reserved.append(state.learner_id)
            elif cid in committed(state):
                committed_extra.append(state.learner_id)
            elif not state.seats and cid in possible(state, cancelled):
                possible_extra.append(state.learner_id)
        bounds[cid] = {
            "reserved": sorted(reserved),
            "committed_extra": sorted(committed_extra),
            "possible_extra": sorted(possible_extra),
            "lower": len(reserved) + len(committed_extra),
            "upper": len(reserved) + len(committed_extra) + len(possible_extra),
        }
    return bounds


def _learner_node(learner_id):
    return f"L:{learner_id}"


def _course_node(course_id):
    return f"C:{course_id}"


def build_network(learner_options, capacities):
    network = {SOURCE: {}}
    for lid, options in learner_options.items():
        network[SOURCE][_learner_node(lid)] = 1
        network[_learner_node(lid)] = {}
        for cid in options:
            network[_learner_node(lid)][_course_node(cid)] = 1
    for cid, capacity in capacities.items():
        network.setdefault(_course_node(cid), {})[SINK] = capacity
    return network


def max_flow(network):
    """Edmonds-Karp；返回 (最大流量, 残量网络)。"""
    residual = {}
    for u, neighbors in network.items():
        row = residual.setdefault(u, {})
        for v, capacity in neighbors.items():
            row[v] = row.get(v, 0) + capacity
            residual.setdefault(v, {})
    flow = 0
    while True:
        prev = {SOURCE: None}
        queue = deque([SOURCE])
        while queue and SINK not in prev:
            u = queue.popleft()
            for v, capacity in residual.get(u, {}).items():
                if capacity > 0 and v not in prev:
                    prev[v] = u
                    queue.append(v)
        if SINK not in prev:
            return flow, residual
        bottleneck = None
        v = SINK
        while prev[v] is not None:
            u = prev[v]
            capacity = residual[u][v]
            bottleneck = capacity if bottleneck is None else min(bottleneck, capacity)
            v = u
        v = SINK
        while prev[v] is not None:
            u = prev[v]
            residual[u][v] -= bottleneck
            residual[v][u] = residual[v].get(u, 0) + bottleneck
            v = u
        flow += bottleneck


def _assignment(residual, learner_options):
    assigned = {}
    for lid in learner_options:
        for node, capacity in residual.get(_learner_node(lid), {}).items():
            if node.startswith("C:") and capacity == 0:
                assigned[lid] = node[2:]
    return assigned


def evaluate_offering(states, cancelled, offering_ids, capacities):
    """对一组同时开出的课程做联合分析。

    capacities 为各课可用学位（已扣除确认保留的学位，保留学位不再承诺给候补者）。
    返回每门课的保证需求（任意合理替代下都成立的最小值）、联合可兑现总量、
    联合上限以及确定落空的学员。
    """
    offering = list(offering_ids)
    committed_options = {}
    for state in states.values():
        if state.seats:
            continue
        options = committed(state) & set(offering)
        if options:
            committed_options[state.learner_id] = options

    flow_committed, residual = max_flow(build_network(committed_options, capacities))
    assignment = _assignment(residual, committed_options)

    # 课程 c 的保证需求 = 联合最大流 - 去掉 c 后的最大流：
    # 即使所有学员都尽量避开 c，也至少有这么多人只能选 c。
    guaranteed = {}
    for cid in offering:
        reduced = dict(capacities)
        reduced[cid] = 0
        flow_without, _ = max_flow(build_network(committed_options, reduced))
        guaranteed[cid] = flow_committed - flow_without

    unmet = sorted(set(committed_options) - set(assignment))

    used = {}
    for cid in assignment.values():
        used[cid] = used.get(cid, 0) + 1
    residual_capacities = {cid: capacities.get(cid, 0) - used.get(cid, 0) for cid in offering}

    possible_options = {}
    for state in states.values():
        if state.seats:
            continue
        options = (possible(state, cancelled) - committed(state)) & set(offering)
        if options:
            possible_options[state.learner_id] = options
    flow_possible, _ = max_flow(build_network(possible_options, residual_capacities))

    return {
        "committed_options": committed_options,
        "committed_assigned": flow_committed,
        "guaranteed": guaranteed,
        "unmet_committed": unmet,
        "possible_options": possible_options,
        "possible_assigned": flow_possible,
        "upper_total": flow_committed + flow_possible,
    }
