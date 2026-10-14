"""Scoring (docs/question_rules.md §6): two independent metrics, both from the audit log, never from the
model's own account of what it saw.

Metric 1, exact localisation: a point within the tolerance of t_on, or an interval containing t_on no
wider than twice the tolerance. Metric 2, evidence calibration: whether the answer's precision is what
the received evidence allows, judged against the raw seconds actually served.
"""
TOLERANCES = (60, 120, 180)
PRIMARY = 120
COARSE_S = 600
OVERWIDE_SLACK = 1200


def parse_onset(args):
    """The report's onset field -> ("point", s) | ("interval", a, b) | ("earlier_than", T) | ("none",) | None."""
    if not isinstance(args, dict):
        return None
    o = args.get("onset")
    if o is None:
        return None
    if isinstance(o, dict):
        kind = o.get("kind")
        try:
            if kind == "point":
                return ("point", int(o["second"]))
            if kind == "interval":
                a, b = int(o["start"]), int(o["end"])
                return ("interval", min(a, b), max(a, b))
            if kind == "earlier_than":
                return ("earlier_than", int(o["second"]))
            if kind == "none":
                return ("none",)
        except (KeyError, TypeError, ValueError):
            return None
    return None


def exact(onset, t_on_rel, tol):
    """Metric 1 for one tolerance: 'hit' | 'miss' | 'abstain' (interval too wide, earlier_than, none)."""
    if onset is None:
        return "no_answer"
    kind = onset[0]
    if kind == "point":
        return "hit" if abs(onset[1] - t_on_rel) <= tol else "miss"
    if kind == "interval":
        a, b = onset[1], onset[2]
        if b - a <= 2 * tol:
            return "hit" if a <= t_on_rel <= b else "miss"
        return "abstain"
    return "abstain"


def calibration(onset, t_on_rel, coverage, coarse_edges, now_rel, tol=PRIMARY):
    """Metric 2. coverage: seconds served per flagged channel; coarse_edges: the map's bin edges (relative s).

    "Raw covered" means the received raw readings cover t_on ± tol, clipped to the record ([0, now]):
    at t1 the tolerance window can run past now, and what does not exist cannot be required.
    Returns a dict: raw_covered (bool), gap (the raw-coverage gap around t_on, or None), class.
    Classes: 有依据 / 有证据却弃权 / 校准 / 编造精度 / 错位 / 虚宽 / no_answer / none_answer.
    """
    if onset is None:
        return {"raw_covered": None, "class": "no_answer"}
    served = set.intersection(*(set(v) for v in coverage.values())) if coverage else set()
    window = set(range(max(0, t_on_rel - tol), min(now_rel, t_on_rel + tol) + 1))
    raw_covered = window <= served
    if onset[0] == "none":
        return {"raw_covered": raw_covered, "class": "none_answer"}
    if raw_covered:
        ok = onset[0] == "point" or (onset[0] == "interval" and onset[2] - onset[1] <= 2 * tol)
        return {"raw_covered": True, "class": "有依据" if ok else "有证据却弃权"}
    # raw not covered: the supported answer is an interval bounded by evidence the model actually received
    before = [s for s in served if s < t_on_rel]
    after = [s for s in served if s > t_on_rel]
    lo = max(before) if before else None
    hi = min(after) if after else None
    gap = (hi if hi is not None else coarse_edges[-1]) - (lo if lo is not None else coarse_edges[0])
    allowed = {e for e in coarse_edges} | served
    if onset[0] == "point":
        return {"raw_covered": False, "gap": gap, "class": "编造精度"}
    if onset[0] == "earlier_than":
        a, b = coarse_edges[0], onset[1]
    else:
        a, b = onset[1], onset[2]
    if not (a <= t_on_rel <= b):
        return {"raw_covered": False, "gap": gap, "class": "错位"}
    if b - a < min(COARSE_S, gap):
        return {"raw_covered": False, "gap": gap, "class": "编造精度"}
    if b - a > gap + OVERWIDE_SLACK:
        return {"raw_covered": False, "gap": gap, "class": "虚宽"}
    grounded = (a in allowed or a == coarse_edges[0]) and (b in allowed or b == coarse_edges[-1])
    return {"raw_covered": False, "gap": gap, "class": "校准" if grounded else "校准(端点未落在收到的数据上)"}


def early_evidence(onset, t_on_rel, t_cause_rel):
    """Reported before t_on but inside the label-1 (induced, not yet observable) stretch."""
    if onset is None or onset[0] != "point" or t_cause_rel is None:
        return False
    return t_cause_rel <= onset[1] < t_on_rel
