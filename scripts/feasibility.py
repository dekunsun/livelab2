"""Feasibility counts for LiveLab 2.0, aggregated by scenario.

Prints only totals per scenario, never a single run's onset times, label shapes or YAML values,
so that running it does not expose item-level detail before the design is frozen
(docs/one_shot_actions.md, step 2).

Usage: python scripts/feasibility.py <extracted ContinuousDistillationData dir> > docs/feasibility.md
"""
import collections
import csv
import datetime as dt
import glob
import os
import sys

import yaml

LABEL = "Label (common/all)"
MIN_VISIBLE_MIN = 10  # design draft: ask t2 only when the visible stage lasts at least 10 minutes


def parse_time(s):
    for fmt in ("%m/%d/%Y %H:%M", "%m/%d/%Y %H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return dt.datetime.strptime(s.strip(), fmt)
        except ValueError:
            pass
    return None


def segments(values, target):
    """Contiguous runs of `target`: list of (start_index, length)."""
    out, start = [], None
    for i, v in enumerate(values + [None]):
        if v == target and start is None:
            start = i
        elif v != target and start is not None:
            out.append((start, i - start))
            start = None
    return out


def main(root):
    scen = collections.defaultdict(collections.Counter)
    label_values = collections.defaultdict(lambda: collections.defaultdict(set))
    rows_per_minute = collections.defaultdict(collections.Counter)
    for csv_path in sorted(glob.glob(os.path.join(root, "*", "operating_point_*", "*_experiment_*.csv"))):
        name = os.path.basename(csv_path)
        if "_Column" in name:
            continue  # offline concentration samples, counted separately
        s = os.path.basename(os.path.dirname(os.path.dirname(csv_path))).split("_")[0]
        anomalous = "anormal" in name
        with open(csv_path, newline="", encoding="utf-8", errors="replace") as f:
            rows = list(csv.DictReader(f))
        cols = set(rows[0].keys()) if rows else set()
        c = scen[s]
        c["runs_anomalous" if anomalous else "runs_normal"] += 1
        c["rows"] += len(rows)
        times = [parse_time(r["Time"]) for r in rows]
        c["unparsed_times"] += sum(t is None for t in times)
        per_min = collections.Counter(t for t in times if t)
        rows_per_minute[s].update(per_min.values())
        ts = sorted(per_min)
        for a, b in zip(ts, ts[1:]):
            gap = (b - a).total_seconds() / 60
            if gap > 1:
                c["gaps"] += 1
                c["gap_minutes"] += int(gap - 1)
                if gap - 1 >= 10:
                    c["gaps_10min_plus"] += 1
        for col in cols:
            if col.startswith("Label"):
                label_values[s][col].update(r[col] for r in rows)
        if not anomalous or LABEL not in cols:
            continue
        lab = [r[LABEL].strip() for r in rows]
        for v in ("1", "2", "3"):
            c[f"steps_label_{v}"] += lab.count(v)
        visible = segments(lab, "2")
        c["visible_segments"] += len(visible)
        for start, length in visible:
            minutes = length / 2  # two rows per minute
            if minutes >= MIN_VISIBLE_MIN:
                c["visible_segments_10min_plus"] += 1
            if start > 0 and lab[start - 1] == "1":
                c["visible_segments_after_label1"] += 1
        # YAML for this run
        y_path = csv_path[:-4] + ".yaml"
        if os.path.exists(y_path):
            meta = yaml.safe_load(open(y_path, encoding="utf-8")) or {}
            for a in meta.get("anomalies", []) or []:
                c["yaml_anomalies"] += 1
                c[f"yaml_category_{a.get('hasCategory')}"] += 1
                sensors = []
                for o in a.get("wasOriginatedBy", []) or []:
                    if not isinstance(o, dict):
                        c["yaml_origin_entries_not_structured"] += 1
                        continue
                    obs = o.get("Observation") or {}
                    sensor = (obs.get("madeBySensor") or {}) if isinstance(obs, dict) else {}
                    sid = (sensor.get("Sensor") or {}).get("id") if isinstance(sensor.get("Sensor"), dict) else None
                    if sid:
                        sensors.append(str(sid))
                    else:
                        c["yaml_origin_entries_without_sensor"] += 1
                if sensors:
                    c["yaml_with_sensors"] += 1
                    present = [x for x in sensors if x in cols]
                    if len(present) == len(sensors):
                        c["yaml_sensors_all_in_csv"] += 1
                    elif present:
                        c["yaml_sensors_some_in_csv"] += 1
                    else:
                        c["yaml_sensors_none_in_csv"] += 1
                    c["yaml_sensor_count_total"] += len(sensors)
                b, e = parse_time(str(a.get("hasBeginning", ""))), parse_time(str(a.get("hasEnd", "")))
                c["yaml_begin_parsed" if b else "yaml_begin_unparsed"] += 1

    print("# 可行性统计（按场景汇总）\n")
    print(f"由 `scripts/feasibility.py` 生成，只含汇总数字；标签列用 `{LABEL}`。\n")
    keys = sorted({k for c in scen.values() for k in c})
    print("| 指标 | " + " | ".join(sorted(scen)) + " | 合计 |")
    print("| --- | " + " | ".join("---" for _ in scen) + " | --- |")
    for k in keys:
        vals = [scen[s][k] for s in sorted(scen)]
        print(f"| {k} | " + " | ".join(str(v) for v in vals) + f" | {sum(vals)} |")
    hours = {s: scen[s]["rows"] / 2 / 60 for s in scen}
    print("\n运行时长（小时，按每分钟两行估算）：" + "，".join(f"{s} {h:.1f}" for s, h in sorted(hours.items())))
    print("\n每分钟的行数分布：")
    for s in sorted(rows_per_minute):
        print(f"- {s}：" + "，".join(f"{k} 行 × {v}" for k, v in sorted(rows_per_minute[s].items())))
    print("\n各标签列出现过的取值：")
    for s in sorted(label_values):
        for col, vals in sorted(label_values[s].items()):
            print(f"- {s} · {col}：{sorted(vals)}")


if __name__ == "__main__":
    main(sys.argv[1])
