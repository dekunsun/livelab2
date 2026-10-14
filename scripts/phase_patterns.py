"""Count anomaly episodes by their sequence of label phases, aggregated per scenario.

An episode is a maximal run of non-zero labels; its pattern is the sequence of distinct values
(for example 1-2-3). Prints counts only, never a single run's times.

First run ad hoc on 2026-10-14 (see docs/timeline.md), then saved here unchanged in logic.

Usage:
  python scripts/phase_patterns.py continuous <extracted ContinuousDistillationData dir>
  python scripts/phase_patterns.py batch <batch labels dir>
"""
import collections
import csv
import glob
import sys

ZERO = ("0", "0.0", "")


def episodes(lab):
    i = 0
    while i < len(lab):
        if lab[i] in ZERO:
            i += 1
            continue
        j, seq = i, []
        while j < len(lab) and lab[j] not in ZERO:
            if not seq or seq[-1] != lab[j]:
                seq.append(lab[j])
            j += 1
        yield seq, sum(1 for x in lab[i:j] if x == "2")
        i = j


def run(kind, root):
    if kind == "continuous":
        files, col, steps_per_min = glob.glob(root + "/*/operating_point_*/test_anormal_*.csv"), "Label (advanced/hard fault)", 2
        group = lambda p: p.split("/")[-3].split("_")[0]
    else:
        files, col, steps_per_min = glob.glob(root + "/**/test_anormal_*.csv", recursive=True), "Label (anomaly)", 60
        group = lambda p: "batch"
    pat = collections.defaultdict(collections.Counter)
    vis = collections.Counter()
    vis10 = collections.Counter()
    for p in files:
        if "_Column" in p:
            continue
        rows = list(csv.DictReader(open(p, newline="", encoding="utf-8", errors="replace")))
        if not rows or col not in rows[0]:
            continue
        g = group(p)
        for seq, n2 in episodes([r[col].strip() for r in rows]):
            pat[g]["-".join(seq)] += 1
            if n2:
                vis[g] += 1
                vis10[g] += n2 / steps_per_min >= 10
    for g in sorted(pat):
        print(g, dict(pat[g]), "| episodes with a visible stage:", vis[g], "| visible >= 10 min:", vis10[g])


if __name__ == "__main__":
    run(sys.argv[1], sys.argv[2])
