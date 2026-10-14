"""The formal run: every registered cell, items interleaved, one spend cap for the whole run.

  ./.venv/bin/python scripts/run_formal.py --agent opus-5.5 --cap 40 [--split public]

Cells (docs/registration.md): A t1/t2 @1800; E and D t1 @1800 and t2 @600/1800/3600; B t1/t2 @1800.
Items are visited in a seeded random order and every cell of an item is run before the next item, so a
transient API problem spreads across cells instead of hitting one cell wholesale (1.0's lesson: run order
is time order). The cap is for the whole run; at the halfway point the spend so far is printed against
the registered estimate. Existing records are skipped, so the run is resumable.
"""
import argparse
import json
import os
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
from livelab2.model import load_dotenv  # noqa: E402
from run import load_items, out_dir, run_item, spent_in  # noqa: E402

CELLS = [("A", 1800, "t1"), ("A", 1800, "t2"), ("E", 1800, "t1"), ("E", 600, "t2"), ("E", 1800, "t2"), ("E", 3600, "t2"),
         ("D", 1800, "t1"), ("D", 600, "t2"), ("D", 1800, "t2"), ("D", 3600, "t2"), ("B", 1800, "t1"), ("B", 1800, "t2")]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--agent", default="opus-5.5")
    ap.add_argument("--cap", type=float, required=True, help="US$ for the whole run")
    ap.add_argument("--split", default="public", choices=["public", "holdout"])
    ap.add_argument("--cells", nargs="*", help="restrict to cells written as ARM:K:WHEN")
    ap.add_argument("--estimate", type=float, help="registered estimate (US$) for this split; stop at halfway if the projection exceeds 1.5x")
    args = ap.parse_args()
    load_dotenv()
    cells = CELLS if not args.cells else [tuple([c.split(":")[0], int(c.split(":")[1]), c.split(":")[2]]) for c in args.cells]
    if args.split == "holdout":
        cells = [c for c in cells if c[1] == 1800]      # the hold-out runs only at K = 1,800
    items = [it for it in load_items(args.split) if it["set"] == "main"]
    random.Random(20261014).shuffle(items)
    dirs = {c: out_dir(args.agent, args.split, "main", *c) for c in cells}
    for d in dirs.values():
        d.mkdir(parents=True, exist_ok=True)
    spend = sum(spent_in(d) for d in dirs.values())
    total = sum(1 for it in items for c in cells if it.get(c[2]) is not None)
    done = sum(len(list(d.glob("*.json"))) for d in dirs.values())
    half_reported = done >= total / 2
    print(f"{len(items)} items x {len(cells)} cells = {total} records; {done} exist; spend so far US${spend:.2f}; cap US${args.cap}")
    for it in items:
        for c in cells:
            if it.get(c[2]) is None:
                continue
            path = dirs[c] / f"{it['item_id']}.json"
            if path.exists():
                continue
            if spend >= args.cap:
                print(f"CAP REACHED at US${spend:.2f}; stopping. {done} of {total} records written.")
                return
            rec = run_item(it, args.agent, *c)
            tmp = path.with_suffix(".json.part"); tmp.write_text(json.dumps(rec, ensure_ascii=False)); os.replace(tmp, path)
            spend += rec["spend_usd"]; done += 1
            m = rec["metrics"]
            print(f"[{done}/{total}] {c[0]} K{c[1]} {c[2]} {it['item_id']} {rec['outcome']} hit@120={m.get('exact', {}).get('120')} "
                  f"cal={m.get('calibration', {}).get('class')} raw={rec['raw_used']} US${rec['spend_usd']:.3f} (total {spend:.2f})")
            if not half_reported and done >= total / 2:
                half_reported = True
                projected = spend * total / done
                print(f"=== HALFWAY: US${spend:.2f} spent for {done} records; projected total US${projected:.2f}")
                if args.estimate and projected > 1.5 * args.estimate:
                    print(f"STOP: projected US${projected:.2f} exceeds 1.5 x the registered estimate US${args.estimate:.2f}; report before continuing.")
                    return
    print(f"finished: {done} of {total} records, spend US${spend:.2f}")


if __name__ == "__main__":
    main()
