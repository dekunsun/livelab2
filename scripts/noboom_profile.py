"""Aggregate profile of the NoBOOM continuous mini-plant sets (data/raw/noboom), before any 2.1 rule is frozen.

Prints counts and length quantiles only: no single anomaly's values, times, causes or texts.
  python scripts/noboom_profile.py
"""
import csv, glob, re, statistics, sys
from datetime import datetime
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parent.parent / "data/raw/noboom"
ADV = ["Label (advanced/hard fault)", "Label (advanced/soft fault)", "Label (advanced/controller fault)"]
ALL = "Label (common/all)"


def parse_t(s):
    for f in ("%Y-%m-%d %H:%M:%S", "%m/%d/%Y %H:%M:%S", "%m/%d/%Y %H:%M", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(s.strip(), f)
        except ValueError:
            pass
    return None


def runs(col):
    """Maximal runs of equal value: list of (value, start_idx, end_idx_exclusive)."""
    out, i = [], 0
    while i < len(col):
        j = i
        while j < len(col) and col[j] == col[i]:
            j += 1
        out.append((col[i], i, j)); i = j
    return out


def q(xs):
    if not xs:
        return "-"
    xs = sorted(xs)
    if len(xs) < 4:
        return "/".join(f"{x/60:.1f}" for x in xs) + " min"
    a, b, c = statistics.quantiles(xs, n=4)
    return f"{a/60:.1f} / {b/60:.1f} / {c/60:.1f} min (max {xs[-1]/60:.1f})"


for ds in sorted(p.name for p in ROOT.iterdir() if p.is_dir()):
    files = sorted(glob.glob(str(ROOT / ds / "**/*.csv"), recursive=True))
    files = [f for f in files if "Features" not in f]
    tests = [f for f in files if "test_anormal" in Path(f).name]
    cols = set()
    for f in files:
        with open(f, newline="", encoding="utf-8", errors="replace") as h:
            cols |= set(next(csv.reader(h)))
    sensors = {c.strip() for c in cols if c and not c.startswith("Label") and c.strip() != "Time"}
    steps, nontime, durs = {}, 0, []
    seg2, hist2, seg_all, hist_all, first2 = [], [], [], [], 0
    sensor_named, entries = 0, 0
    for f in files:
        with open(f, newline="", encoding="utf-8", errors="replace") as h:
            rows = list(csv.DictReader(h))
        ts = [parse_t(r.get("Time", "")) for r in rows]
        nontime += sum(t is None for t in ts)
        ts = [t for t in ts if t]
        for a, b in zip(ts, ts[1:]):
            d = int((b - a).total_seconds()); steps[d] = steps.get(d, 0) + 1
        if ts:
            durs.append((ts[-1] - ts[0]).total_seconds())
        if f not in tests:
            continue
        dt = 30
        for c in ADV + [ALL]:
            if c not in rows[0]:
                continue
            col = [(r[c] or "0").strip().split(".")[0] for r in rows]
            prev_end = 0
            for k, (v, s, e) in enumerate(runs(col)):
                if c == ALL and v == "1":
                    seg_all.append((e - s) * dt); hist_all.append((s - prev_end) * dt)
                if c != ALL and v == "2":
                    seg2.append((e - s) * dt); hist2.append((s - prev_end) * dt)
                    first2 += prev_end == 0
                if v == "0" and k > 0:
                    prev_end = s
        y = Path(f[:-4] + "_metadata.yaml")
        if y.exists():
            d = yaml.safe_load(open(y)) or {}
            for a in d.get("AnomalyReasons") or []:
                entries += 1
                text = " ".join(str(a.get(k, "")) for k in ("cause", "description", "effect"))
                toks = set(re.findall(r"[A-Z]{1,5}\d{2,3}", text))
                sensor_named += bool(toks & sensors)
    print(f"== {ds}: {len(files)} runs ({len(tests)} anomalous), {len(sensors)} sensor columns")
    print(f"   time step counts (s: n): {dict(sorted(steps.items(), key=lambda kv: -kv[1])[:5])}; unparsed times {nontime}")
    print(f"   run durations: {q(durs)}")
    print(f"   advanced label-2 segments: {len(seg2)}; lengths {q(seg2)}; >=10 min: {sum(x >= 600 for x in seg2)}; "
          f"history before >=5 min: {sum(h >= 300 for h in hist2)}; both: {sum(x >= 600 and h >= 300 for x, h in zip(seg2, hist2))}")
    print(f"   common/all segments: {len(seg_all)}; lengths {q(seg_all)}; >=10 min with >=5 min history: "
          f"{sum(x >= 600 and h >= 300 for x, h in zip(seg_all, hist_all))}")
    print(f"   yaml anomaly entries: {entries}; entries whose cause/description/effect names a sensor column: {sensor_named}")
