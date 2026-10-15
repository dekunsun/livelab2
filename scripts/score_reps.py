"""Score the repetition follow-up (docs/registration_reps.md): E and D, K = 1,800, t1 and t2, runs 0 (the formal
run), 1 and 2. Per run: P1's two parts. Pooled: an item counts as a hit in a cell if it is a hit in at least two
of the three runs (majority), and P1 is recomputed on those; every row is also split by subset.

  ./.venv/bin/python scripts/score_reps.py results/opus-5.5/main_public
"""
import json
import sys
from pathlib import Path

CELLS = [("E", "t1"), ("E", "t2"), ("D", "t1"), ("D", "t2")]


def load(tree, arm, when, rep):
    d = Path(tree) / (f"{arm}_K1800_{when}" + (f".rep{rep}" if rep else ""))
    return {json.load(open(p))["item_id"]: json.load(open(p)) for p in d.glob("*.json")}


def hit(r):
    return r["metrics"]["exact"]["120"] == "hit"


def p1(h, ids):
    s = sum((h["D", "t2"][i] - h["E", "t2"][i]) - (h["D", "t1"][i] - h["E", "t1"][i]) for i in ids)
    return {"interaction": s, "D_minus_E_t2": sum(h["D", "t2"][i] - h["E", "t2"][i] for i in ids),
            "D_minus_E_t1": sum(h["D", "t1"][i] - h["E", "t1"][i] for i in ids), "items": len(ids)}


def main(tree):
    runs = {rep: {c: load(tree, *c, rep) for c in CELLS} for rep in (0, 1, 2)}
    ids = sorted(set.intersection(*(set(runs[rep][c]) for rep in runs for c in CELLS)))
    subset = {i: runs[0][CELLS[0]][i]["subset"] for i in ids}
    for rep in runs:
        h = {c: {i: int(hit(runs[rep][c][i])) for i in ids} for c in CELLS}
        print(f"run {rep}: hits", {f"{a}_{w}": sum(h[a, w].values()) for a, w in CELLS}, "P1", p1(h, ids))
    maj = {c: {i: int(sum(hit(runs[rep][c][i]) for rep in runs) >= 2) for i in ids} for c in CELLS}
    print("majority of 3: hits", {f"{a}_{w}": sum(maj[a, w].values()) for a, w in CELLS}, "P1", p1(maj, ids))
    for sub in ("public_unused", "used_in_1.0"):
        sid = [i for i in ids if subset[i] == sub]
        print(f"  majority, {sub} ({len(sid)} items): P1", p1(maj, sid))
    every = {c: sum(all(hit(runs[rep][c][i]) for rep in runs) for i in ids) for c in CELLS}
    print("right in every run (pass^3):", {f"{a}_{w}": v for (a, w), v in every.items()})


if __name__ == "__main__":
    main(sys.argv[1])
