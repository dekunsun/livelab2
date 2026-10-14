"""Aggregate profile of the batch distillation dataset, for the design doc.

Runs listed in holdout/holdout_runs.txt are skipped entirely: their files are never opened.
Prints totals and distributions only, never a single run's times, labels or YAML values.

Reports: sampling interval, run length, channel counts (sensors, actuators), recording gaps,
and how many YAML anomaly entries name an affected sensor that exists in the sensor file.

Usage: python scripts/batch_profile.py <data/raw/batch dir>
"""
import collections
import csv
import glob
import io
import os
import re
import statistics
import sys
import zipfile

import yaml

HOLDOUT = "holdout/holdout_runs.txt"
RID = re.compile(r"(batch_dist_[^/]+)/operating_point_(\d{3})/(test_anormal|train_normal)_experiment_(\d{3})\.(csv|yaml)$")


def rid(path):
    m = RID.search(path)
    return m and f"{m.group(1)}|op{m.group(2)}|{m.group(3)}|{m.group(4)}"


def seconds(s):
    h, m, sec = (int(x) for x in s.strip().split(":"))
    return h * 3600 + m * 60 + sec


def sensor_ids(node, out):
    """Collect every madeBySensor.Sensor.id anywhere in one anomaly entry."""
    if isinstance(node, dict):
        s = node.get("madeBySensor")
        if isinstance(s, dict) and isinstance(s.get("Sensor"), dict) and s["Sensor"].get("id"):
            out.add(str(s["Sensor"]["id"]))
        for v in node.values():
            sensor_ids(v, out)
    elif isinstance(node, list):
        for v in node:
            sensor_ids(v, out)
    return out


def header(zip_path, run):
    system, op, kind, n = run.split("|")
    with zipfile.ZipFile(zip_path) as z:
        for name in z.namelist():
            if name.endswith(f"{system}/operating_point_{op[2:]}/{kind}_experiment_{n}.csv"):
                return next(csv.reader(io.TextIOWrapper(z.open(name), encoding="utf-8", errors="replace")))
    return None


def main(root):
    holdout = {line.strip() for line in open(HOLDOUT) if line.strip()}
    labels = [p for p in glob.glob(os.path.join(root, "labels", "**", "*_experiment_*.csv"), recursive=True) if rid(p)]
    kept = [p for p in labels if rid(p) not in holdout]
    print(f"label files: {len(labels)}; skipped as hold-out: {len(labels) - len(kept)}; profiled: {len(kept)}")

    step = collections.Counter()
    hours = collections.defaultdict(list)
    gaps = collections.Counter()
    for p in kept:
        kind = rid(p).split("|")[2]
        raw = [r["Time"] for r in csv.DictReader(open(p, newline="", encoding="utf-8", errors="replace"))]
        gaps["rows_without_time"] += sum(1 for x in raw if not x.strip())
        t = [seconds(x) for x in raw if x.strip()]
        span = 0
        for a, b in zip(t, t[1:]):
            d = (b - a) % 86400  # time of day only; wraps at midnight
            step[d if d <= 5 else ">5"] += 1
            span += d
            if d > 1:
                gaps["gaps_over_1s"] += 1
            if d >= 60:
                gaps["gaps_60s_plus"] += 1
        if any((b - a) % 86400 >= 60 for a, b in zip(t, t[1:])):
            gaps["runs_with_gap_60s_plus"] += 1
        hours[kind].append(span / 3600)
    print("sampling interval (s) between consecutive rows:", dict(sorted(step.items(), key=str)))
    for kind, h in sorted(hours.items()):
        q = statistics.quantiles(h, n=4)
        print(f"run length, {kind} (n={len(h)}): min {min(h):.1f} h, quartiles {q[0]:.1f}/{q[1]:.1f}/{q[2]:.1f} h, max {max(h):.1f} h, total {sum(h):.0f} h")
    print("recording gaps:", dict(gaps))

    sample = sorted(rid(p) for p in kept if "train_normal" in p)[0]
    sens = header(glob.glob(os.path.join(root, "01_*Sensors.zip"))[0], sample) or []
    act = header(glob.glob(os.path.join(root, "02_*Actuators.zip"))[0], sample) or []
    print(f"channels in one normal run: sensors {len([c for c in sens if c != 'Time'])}, actuators {len([c for c in act if c != 'Time'])}")

    c = collections.Counter()
    sens_set = set(sens)
    for p in glob.glob(os.path.join(root, "labels", "**", "test_anormal_experiment_*.yaml"), recursive=True):
        if rid(p) in holdout:
            continue
        for a in (yaml.safe_load(open(p, encoding="utf-8")) or {}).get("anomalies", []) or []:
            if not isinstance(a, dict) or a.get("class") in (None, "None"):
                continue
            c["anomaly_entries"] += 1
            ids = sensor_ids(a, set())
            if not ids:
                c["entries_without_sensor"] += 1
            elif ids <= sens_set:
                c["entries_sensors_all_in_sensor_file"] += 1
            else:
                c["entries_sensors_some_missing_from_sensor_file"] += 1
            c["multi_window_entries"] += isinstance(a.get("hasBeginning"), list)
    print("YAML anomaly entries (non-hold-out runs):", dict(c))


if __name__ == "__main__":
    main(sys.argv[1])
