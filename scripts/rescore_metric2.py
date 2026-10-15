"""Metric 2, version 2 (deviation 3 of docs/registration.md, decided after the results were seen).

v1 counted the raw evidence as covering the onset only if every second of t_on +- 120 s was served, so an
agent that fetched a window starting just before the onset was scored as inventing precision. v2 asks for
t_on +- 30 s. Everything else is unchanged. Records are not rewritten; this prints v1 and v2 side by side.

  ./.venv/bin/python scripts/rescore_metric2.py results/opus-5.5/main_public
"""
import collections
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from livelab2 import judge  # noqa: E402


def main(tree):
    rows = collections.defaultdict(lambda: [collections.Counter(), collections.Counter()])
    for p in sorted(x for x in Path(tree).glob("*/*.json") if ".rep" not in x.parent.name):
        r = json.load(open(p))
        if r.get("t_on_rel") is None:
            continue
        onset = judge.parse_onset(r["report"])
        edges = list(range(0, r["now_rel"] + 1, 600)) + [r["now_rel"] + 1]
        v2 = judge.calibration(onset, r["t_on_rel"], r["coverage"], edges, r["now_rel"], cover=30)["class"]
        key = (r["arm"], r["k"], r["when"])
        rows[key][0][r["metrics"]["calibration"]["class"]] += 1
        rows[key][1][v2] += 1
    classes = ["有依据", "有证据却弃权", "校准", "编造精度", "错位", "虚宽"]
    print("| arm | K | ask | " + " | ".join(f"{c} v1→v2" for c in classes) + " |")
    print("| --- " * (3 + len(classes)) + "|")
    tot = collections.Counter()
    for key in sorted(rows):
        v1, v2 = rows[key]
        print(f"| {key[0]} | {key[1]} | {key[2]} | " + " | ".join(f"{v1[c]}→{v2[c]}" for c in classes) + " |")
        if key[0] in "DE" and key[2] == "t2":
            for c in ("编造精度", "校准"):
                tot[c, "v1"] += v1[c]; tot[c, "v2"] += v2[c]
    print(f"\nP5 (E and D, t2, all budgets): 编造精度 vs 校准 — v1 {tot['编造精度','v1']} vs {tot['校准','v1']}; v2 {tot['编造精度','v2']} vs {tot['校准','v2']}")


if __name__ == "__main__":
    main(sys.argv[1])
