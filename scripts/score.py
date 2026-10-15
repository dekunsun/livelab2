"""Score a results tree: per arm × K × ask-time counts, both metrics, and the registered tests.

  ./.venv/bin/python scripts/score.py results/opus-5.5/main_public
  ./.venv/bin/python scripts/score.py results/mock-oracle/main_public --tol 120

Counts on fixed denominators (every registered item of the set); an item without a valid submission
counts as not done and is listed in the coverage column. P1 = sum over items of
(D_hit - E_hit at t2) - (D_hit - E_hit at t1) at K = 1800, plus the absolute condition (D - E at t2 >= 3).
"""
import argparse
import collections
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def load(tree):
    recs = collections.defaultdict(dict)   # (arm, k, when) -> item_id -> record
    for p in sorted(Path(tree).glob("*/*.json")):
        r = json.load(open(p))
        recs[(r["arm"], r["k"], r["when"])][r["item_id"]] = r
    return recs


def hit(r, tol):
    return r["metrics"].get("exact", {}).get(str(tol)) == "hit"


def table(recs, items_n, tol):
    rows = ["| arm | K | ask | answered / registered | hit@60 | hit@120 | hit@180 | 有依据 | 校准 | 编造精度 | 弃权(有证据) | 错位/虚宽 | 早于证据 | mean raw used | tokens in / out | spend US$ |",
            "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for key in sorted(recs):
        rs = recs[key].values()
        answered = sum(r["outcome"] == "submitted" and r["metrics"].get("onset") is not None for r in rs)
        cal = collections.Counter(r["metrics"].get("calibration", {}).get("class") for r in rs)
        tok_in = sum(r["usage"].get("input_tokens", 0) + r["usage"].get("cache_creation_input_tokens", 0) + r["usage"].get("cache_read_input_tokens", 0) for r in rs)
        tok_out = sum(r["usage"].get("output_tokens", 0) for r in rs)
        raw = [r["raw_used"] for r in rs]
        rows.append(f"| {key[0]} | {key[1]} | {key[2]} | {answered} / {items_n} | "
                    f"{sum(hit(r, 60) for r in rs)} | {sum(hit(r, 120) for r in rs)} | {sum(hit(r, 180) for r in rs)} | "
                    f"{cal['有依据']} | {cal['校准'] + cal['校准(端点未落在收到的数据上)']} | {cal['编造精度']} | {cal['有证据却弃权']} | "
                    f"{cal['错位'] + cal['虚宽']} | {sum(bool(r['metrics'].get('early_evidence')) for r in rs)} | "
                    f"{sum(raw) / len(raw) if raw else 0:.0f} | {tok_in:,} / {tok_out:,} | {sum(r['spend_usd'] for r in rs):.2f} |")
    return "\n".join(rows)


def loose(recs):
    """Exploratory, added after the public results were seen (2026-10-14): a point answer counts as grounded
    if any served raw second lies within 30 s of t_on, instead of requiring t_on +- 120 s fully covered."""
    lines = ["| arm | K | ask | 编造精度 (registered) | of which onset within 30 s of served data (loose: grounded) |", "| --- | --- | --- | --- | --- |"]
    for key in sorted(recs):
        fab = near = 0
        for r in recs[key].values():
            if r["metrics"].get("calibration", {}).get("class") != "编造精度":
                continue
            fab += 1
            served = set.intersection(*(set(v) for v in r["coverage"].values())) if r["coverage"] else set()
            near += any(abs(x - r["t_on_rel"]) <= 30 for x in served)
        lines.append(f"| {key[0]} | {key[1]} | {key[2]} | {fab} | {near} |")
    return "\n".join(lines)


def p1(recs, tol, k=1800):
    d1, d2, e1, e2 = recs.get(("D", k, "t1"), {}), recs.get(("D", k, "t2"), {}), recs.get(("E", k, "t1"), {}), recs.get(("E", k, "t2"), {})
    ids = set(d1) & set(d2) & set(e1) & set(e2)
    s = [(hit(d2[i], tol) - hit(e2[i], tol)) - (hit(d1[i], tol) - hit(e1[i], tol)) for i in sorted(ids)]
    pos, neg = sum(x > 0 for x in s), sum(x < 0 for x in s)
    abs_t2 = sum(hit(d2[i], tol) for i in ids) - sum(hit(e2[i], tol) for i in ids)
    abs_t1 = sum(hit(d1[i], tol) for i in ids) - sum(hit(e1[i], tol) for i in ids)
    return {"paired_items": len(ids), "interaction_sum": sum(s), "positive": pos, "negative": neg, "zero": len(s) - pos - neg,
            "D_minus_E_t2": abs_t2, "D_minus_E_t1": abs_t1}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("tree")
    ap.add_argument("--tol", type=int, default=120)
    ap.add_argument("--items-n", type=int, help="registered items in the set (default: the most items any cell has)")
    args = ap.parse_args()
    recs = load(args.tree)
    n = args.items_n or max((len(v) for v in recs.values()), default=0)
    print(table(recs, n, args.tol))
    for k in (600, 1800, 3600):
        if ("D", k, "t2") in recs and ("E", k, "t2") in recs:
            print(f"\nP1 at K={k}, tol={args.tol}:", json.dumps(p1(recs, args.tol, k)))
    print("\nExploratory (not registered): loose grounding for metric 2")
    print(loose(recs))
    # by subset, main metric only
    by = collections.defaultdict(lambda: collections.Counter())
    for key, rs in recs.items():
        for r in rs.values():
            by[key][(r["subset"], "first" if r.get("first_episode") else "later")] += hit(r, args.tol)
    print("\nhits@%d by subset (arm, K, ask -> subset/first-later: hits):" % args.tol)
    for key in sorted(by):
        print(" ", key, dict(by[key]))


if __name__ == "__main__":
    main()
