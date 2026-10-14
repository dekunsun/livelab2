"""Draw the private hold-out for LiveLab 2.0 from the batch distillation dataset.

Rule, fixed before the draw (docs/one_shot_actions.md, step 1):
- Unit: an anomaly run (`test_anormal_experiment_*`), so episodes of one run never sit on both sides.
- Runs that LiveLab 1.0 referenced anywhere (docs/data/used_in_livelab1.txt) are never eligible:
  their data has already been sent to models and some items are public.
- Within each mixture system, one third of the eligible runs (rounded half up) go to the hold-out.
- Seed: the first 16 hex digits of sha256("livelab2-holdout-v1|" + sha256 of the label archive).
  The archive hash is a property of the published data, so the seed cannot be chosen.

Writes holdout/holdout_runs.txt (outside the repository) and prints, for the repository, the run
lists of the public side, the sha256 of the hold-out list, and aggregate counts only.

Usage: python scripts/split_holdout.py <label archive .zip> <extracted labels dir>
"""
import collections
import csv
import glob
import hashlib
import math
import os
import random
import re
import sys

USED = "docs/data/used_in_livelab1.txt"
HOLDOUT = "holdout/holdout_runs.txt"


def run_id(path):
    m = re.search(r"(batch_dist_[^/]+)/operating_point_(\d{3})/test_anormal_experiment_(\d{3})\.csv$", path)
    return f"{m.group(1)}|op{m.group(2)}|test_anormal|{m.group(3)}"


def visible_episodes(path):
    """Count episodes with a visible (label 2) stage, and those >= 10 min (600 steps at 1 Hz)."""
    rows = list(csv.DictReader(open(path, newline="", encoding="utf-8", errors="replace")))
    lab = [r["Label (anomaly)"].strip() for r in rows]
    n_vis = n_vis10 = 0
    i = 0
    while i < len(lab):
        if lab[i] in ("0", ""):
            i += 1
            continue
        j = i
        while j < len(lab) and lab[j] not in ("0", ""):
            j += 1
        n2 = lab[i:j].count("2")
        n_vis += n2 > 0
        n_vis10 += n2 >= 600
        i = j
    return n_vis, n_vis10


def main(archive, labels_dir):
    archive_sha = hashlib.sha256(open(archive, "rb").read()).hexdigest()
    seed = int(hashlib.sha256(f"livelab2-holdout-v1|{archive_sha}".encode()).hexdigest()[:16], 16)
    used = {line.strip() for line in open(USED) if line.strip()}
    paths = {run_id(p): p for p in glob.glob(os.path.join(labels_dir, "**", "test_anormal_experiment_*.csv"), recursive=True)}
    by_system = collections.defaultdict(list)
    for rid in sorted(paths):
        if rid not in used:
            by_system[rid.split("|")[0]].append(rid)
    rng = random.Random(seed)
    holdout, public = [], []
    for system in sorted(by_system):
        ids = sorted(by_system[system])
        rng.shuffle(ids)
        k = math.floor(len(ids) / 3 + 0.5)
        holdout += ids[:k]
        public += ids[k:]
    os.makedirs("holdout", exist_ok=True)
    text = "\n".join(sorted(holdout)) + "\n"
    with open(HOLDOUT, "x") as f:  # never overwrite an earlier draw
        f.write(text)
    counts = collections.defaultdict(collections.Counter)
    for side, ids in (("holdout", holdout), ("public_unused_in_1.0", public), ("used_in_1.0", sorted(set(paths) & used))):
        for rid in ids:
            v, v10 = visible_episodes(paths[rid])
            counts[side]["runs"] += 1
            counts[side]["visible_episodes"] += v
            counts[side]["visible_episodes_10min_plus"] += v10
    print(f"label archive sha256: {archive_sha}")
    print(f"seed: {seed}")
    print(f"holdout list sha256: {hashlib.sha256(text.encode()).hexdigest()}")
    for side in counts:
        print(side, dict(counts[side]))
    print("public runs (not used in 1.0):")
    print("\n".join(sorted(public)))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
