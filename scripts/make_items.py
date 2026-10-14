"""Generate the LiveLab 2.0 items from the frozen rules (docs/question_rules.md §2–§5).

  ./.venv/bin/python scripts/make_items.py public     -> items/public.json (committed) + counts
  ./.venv/bin/python scripts/make_items.py holdout    -> holdout/items.json (never committed) + counts and sha256

Rules applied, in order, per anomaly run:
- an episode = a maximal non-zero label block; its segment = the first contiguous label-2 run inside it;
- main set: segment >= 600 s, archive before the segment >= 300 s (archive starts at Operation start, or
  at the end of the previous non-zero block), and the overlapping YAML entries name at least one sensor
  present in the sensor file (all such sensors are the fixed channels);
- short set: segment < 600 s (t1 only), same other conditions;
- t1 = t_on + delta, delta ~ U[60, 300] seeded by sha256("livelab2-t1|" + item id);
- t2 = t_on + floor(0.8 L); the oracle offset u ~ U[0.2, 0.8] seeded by sha256("livelab2-oracle|" + item id);
- injected false alerts (secondary): one per normal run, t seeded in [1800, n), one random sensor.
The run id is kept in the item file (public runs are public; the hold-out file never leaves this machine);
the prompt side never sees it (livelab2/arms.py anonymises everything).
"""
import glob
import hashlib
import json
import math
import os
import random
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from livelab2.data import LABELS, Run, holdout_runs, seed_int, used_runs  # noqa: E402

MIN_VISIBLE, MIN_HISTORY, INJECT_MIN_T = 600, 300, 1800
RID = re.compile(r"(batch_dist_[^/]+)/operating_point_(\d{3})/(test_anormal|train_normal)_experiment_(\d{3})\.csv$")


def all_runs():
    out = []
    for p in sorted(glob.glob(str(LABELS / "**" / "*_experiment_*.csv"), recursive=True)):
        m = RID.search(p)
        if m:
            out.append(f"{m.group(1)}|op{m.group(2)}|{m.group(3)}|{m.group(4)}")
    return out


def item_id(*parts):
    return "ep" + hashlib.sha256(("livelab2-item|" + "|".join(str(p) for p in parts)).encode()).hexdigest()[:8]


def build(split):
    hold, used = holdout_runs(), used_runs()
    runs = all_runs()
    if split == "holdout":
        anomaly = [r for r in runs if r in hold]
        normal = []
    else:
        anomaly = [r for r in runs if "test_anormal" in r and r not in hold]
        normal = [r for r in runs if "train_normal" in r]
    items, counts = [], {}

    def tick(k):
        counts[k] = counts.get(k, 0) + 1

    for rid in anomaly:
        try:
            run = Run(rid)
        except ValueError as exc:  # clock gap, wrap or misaligned files: excluded and counted, never patched
            tick("excluded_run_rejected_by_loader"); print("  loader rejected a run:", str(exc).split(":", 1)[1].strip()); continue
        entries = run.anomaly_entries()
        subset = "holdout" if split == "holdout" else ("used_in_1.0" if rid in used else "public_unused")
        for ep in run.episodes():
            if ep["seg"] is None:
                tick("episodes_without_label2"); continue
            s, e = ep["seg"]
            L, history = e - s, s - ep["prev_end"]
            sensors = set()
            for a in entries:
                if any(b < e and en > s for b, en in a["windows"]):
                    sensors.update(x for x in a["sensors"] if x in run.channels)
            if history < MIN_HISTORY:
                tick("excluded_history_under_300s"); continue
            if not sensors:
                tick("excluded_no_named_sensor"); continue
            iid = item_id(rid, s)
            rng_t1 = random.Random(seed_int("livelab2-t1", iid))
            rng_u = random.Random(seed_int("livelab2-oracle", iid))
            delta = rng_t1.randint(60, 300)
            it = {"item_id": iid, "set": "main" if L >= MIN_VISIBLE else "short", "subset": subset, "run": rid,
                  "episode_index": ep["index"], "first_episode": ep["index"] == 0,
                  "archive_start": ep["prev_end"], "t_on": s, "t_end": e, "L": L, "history": history,
                  "t_cause": ep["label1_start"], "channels": sorted(sensors), "n_rows": run.n,
                  "delta": delta, "t1": s + delta, "t2": (s + math.floor(0.8 * L)) if L >= MIN_VISIBLE else None,
                  "u": round(0.2 + 0.6 * rng_u.random(), 4)}
            if it["t1"] >= run.n:
                tick("excluded_t1_past_end"); continue
            items.append(it)
            tick(f"{it['set']}|{subset}|{'first' if it['first_episode'] else 'later'}")
    for rid in normal:
        run = Run(rid)
        if run.n <= INJECT_MIN_T + 60:
            tick("normal_too_short_for_injection"); continue
        iid = item_id(rid, "inject")
        rng = random.Random(seed_int("livelab2-inject", iid))
        t = rng.randint(INJECT_MIN_T, run.n - 1)
        items.append({"item_id": iid, "set": "injected", "subset": "used_in_1.0" if rid in used else "public_unused",
                      "run": rid, "archive_start": 0, "t_on": None, "t1": t, "t2": None,
                      "channels": [rng.choice(run.channels)], "n_rows": run.n})
        tick("injected")
    return items, counts


def main(split):
    items, counts = build(split)
    out = ROOT / ("holdout/items.json" if split == "holdout" else "items/public.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(items, indent=1, ensure_ascii=False)
    with open(out, "x" if split == "holdout" else "w", encoding="utf-8") as f:  # never overwrite a hold-out draw
        f.write(text + "\n")
    print(f"{split}: {len(items)} items -> {out.relative_to(ROOT)}")
    for k in sorted(counts):
        print(f"  {k}: {counts[k]}")
    print("sha256:", hashlib.sha256(text.encode()).hexdigest())


if __name__ == "__main__":
    main(sys.argv[1])
