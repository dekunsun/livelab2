"""Three mock agents that exercise the pipeline, the budget accounting and both metrics before any
model is called (docs/question_rules.md §8, step 3). They never see the truth except the oracle, which
is given t_on on purpose so a perfect agent's scores are known in advance.

- now:    reports onset = the current time, in every arm (should hit only when delta <= tolerance at t1).
- random: in D, fetches random windows inside the budget, then reports a random second it has seen;
          in A/E/B reports a random second among the raw seconds it was given (or earlier_than if none).
- oracle: in D, fetches a window around t_on; everywhere reports t_on if the raw evidence covers it,
          an interval bounded by its evidence otherwise (should score 'hit' / '校准' by construction).
"""
import random

from .archive import MAX_CALLS


def run_mock(kind, archive, arm, t_on_rel, seed):
    rng = random.Random(seed)
    now = archive.rel(archive.t)
    if arm == "D":
        if kind == "random":
            for _ in range(rng.randint(1, MAX_CALLS)):
                left = archive.remaining()
                if left <= 0:
                    break
                n = rng.randint(1, min(left, 900))
                start = rng.randint(0, max(0, now - n + 1))
                archive.get_window(start, start + n - 1)
        elif kind == "oracle":
            n = min(archive.k, archive.length())
            start = max(0, min(t_on_rel - n // 2, now - n + 1))
            archive.get_window(start, start + n - 1)
    served = set.intersection(*(set(v) for v in archive.coverage().values())) if archive.coverage() else set()
    if kind == "now":
        onset = {"kind": "point", "second": now}
    elif kind == "random":
        onset = ({"kind": "point", "second": rng.choice(sorted(served))} if served
                 else {"kind": "earlier_than", "second": now})
    else:  # oracle
        if t_on_rel in served:
            onset = {"kind": "point", "second": t_on_rel}
        else:
            before = [s for s in served if s < t_on_rel]
            after = [s for s in served if s > t_on_rel]
            a = max(before) if before else archive.coarse_edges()[0]
            b = min(after) if after else now
            onset = {"kind": "interval", "start": a, "end": b}
    report = {"onset": onset, "evidence": [], "cause": "unknown", "state": "anomalous"}
    return {"outcome": "submitted", "report": report, "reminders": 0, "stop_reasons": [], "usage": {},
            "spend_usd": 0.0, "audit": archive.audit, "coverage": archive.coverage(), "error": None, "exchanges": []}
