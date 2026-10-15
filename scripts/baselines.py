"""The classical baselines F1, F2 and the zero-cost reference G (docs/question_rules.md §5).

  ./.venv/bin/python scripts/baselines.py calibrate          # on the public normal runs only -> docs/data/f_params.json
  ./.venv/bin/python scripts/baselines.py run --when t2        # F1, F2, G on the main public items -> results/baselines/

Residual: r[s] = x[s] - median(x[s-300 .. s-1]) (a trailing median, causal). Per channel, sigma is the
MAD of r over every public normal run. F2, the main classical control: the last second s before now
that ends a stretch of >= 120 s with |r| <= m*sigma; onset = s + 1 (earliest over the flagged channels;
no such stretch -> an interval over the whole record). F1: PELT (ruptures, l2 cost) on r, the last change
point before now (earliest over the flagged channels). m and the PELT penalty are chosen on the normal
runs as the smallest values giving at most one false departure / change point per hour, and are written
to docs/data/f_params.json before any anomaly item is scored. G reports onset = now.
"""
import argparse
import datetime as dt
import glob
import json
import os
import re
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from livelab2 import judge  # noqa: E402
from livelab2.data import LABELS, Run  # noqa: E402

W, MIN_NORMAL, MIN_DEPART = 300, 120, 60
PARAMS = ROOT / "docs/data/f_params.json"
RID = re.compile(r"(batch_dist_[^/]+)/operating_point_(\d{3})/(train_normal)_experiment_(\d{3})\.csv$")


def residual(x):
    """Causal trailing-median residual; None where the value or the window is missing (numpy, same rule)."""
    import numpy as np
    a = np.array([np.nan if v is None else v for v in x], dtype=float)
    out = [None] * len(a)
    if len(a) <= W:
        return out
    win = np.lib.stride_tricks.sliding_window_view(a[:-1], W)        # win[i] = a[i : i+W], predicts a[i+W]
    ok = np.sum(~np.isnan(win), axis=1) >= W // 2
    with np.errstate(all="ignore"):
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            med = np.nanmedian(win, axis=1)
    r = a[W:] - med
    for i, v in enumerate(r):
        if ok[i] and not np.isnan(v):
            out[i + W] = float(v)
    return out


def normal_runs():
    for p in sorted(glob.glob(str(LABELS / "**" / "train_normal_experiment_*.csv"), recursive=True)):
        m = RID.search(p)
        if m:
            yield f"{m.group(1)}|op{m.group(2)}|{m.group(3)}|{m.group(4)}"


def departures(r, thr):
    """Maximal stretches of >= MIN_DEPART consecutive seconds with |r| > thr."""
    n, run = 0, 0
    for v in r:
        if v is not None and abs(v) > thr:
            run += 1
            if run == MIN_DEPART:
                n += 1
        else:
            run = 0
    return n


def flagged_channels():
    """The channels any public item flags (a set of tags, no item values): the only ones the baselines need."""
    out = set()
    for it in json.load(open(ROOT / "items/public.json")):
        out.update(it["channels"])
    return sorted(out)


def calibrate():
    runs = [Run(rid) for rid in normal_runs()]
    hours = sum(r.n for r in runs) / 3600
    chans = flagged_channels()
    params = {"W": W, "min_normal_s": MIN_NORMAL, "min_departure_s": MIN_DEPART, "normal_runs": len(runs),
              "normal_hours": round(hours, 2), "calibrated_channels": chans, "channels": {}}
    res = {c: [residual(r.values[c]) for r in runs] for c in chans}
    for c, series in res.items():
        allr = [abs(v) for s in series for v in s if v is not None]
        sigma = 1.4826 * statistics.median(allr) if allr else 0.0
        chosen = None
        for m in (3, 4, 5, 6, 8, 10, 12, 16, 24, 32):
            n = sum(departures(s, m * sigma) for s in series) if sigma > 0 else 0
            if n / hours <= 1.0:
                chosen = {"m": m, "false_departures": n, "per_hour": round(n / hours, 3)}
                break
        params["channels"][c] = {"sigma": sigma, **(chosen or {"m": None, "note": "no multiplier reached 1/hour"})}
    pelt = calibrate_pelt(res, hours)
    params["pelt"] = pelt
    PARAMS.write_text(json.dumps(params, indent=1))
    print(json.dumps({c: (v["m"], round(v["sigma"], 4)) for c, v in params["channels"].items()}))
    print("pelt:", pelt)


def pelt_points(r, pen):
    import numpy as np
    import ruptures
    arr = np.array([0.0 if v is None else v for v in r], dtype=float)
    if len(arr) < 2 * MIN_DEPART:
        return []
    algo = ruptures.Pelt(model="l2", min_size=MIN_DEPART, jump=10).fit(arr)
    bk = algo.predict(pen=pen)
    return [b for b in bk if b < len(arr)]


def calibrate_pelt(res, hours):
    try:
        import ruptures  # noqa: F401
    except ImportError:
        return {"available": False, "note": "ruptures not installed; F1 skipped"}
    scaled = {}
    for c, series in res.items():
        sig = max(1e-9, 1.4826 * statistics.median([abs(v) for s in series for v in s if v is not None]))
        scaled[c] = [[None if v is None else v / sig for v in s] for s in series]

    def count(pen):
        return sum(len(pelt_points(s, pen)) for ss in scaled.values() for s in ss)

    pens = (1, 3, 10, 30, 100, 300, 1000, 3000)
    lo, hi, best = 0, len(pens) - 1, None          # change points fall as the penalty rises: binary search
    while lo <= hi:
        mid = (lo + hi) // 2
        n = count(pens[mid])
        if n / hours <= 1.0:
            best, hi = (pens[mid], n), mid - 1
        else:
            lo = mid + 1
    if best is None:
        return {"available": True, "pen": None, "note": "no penalty reached 1/hour"}
    return {"available": True, "pen": best[0], "change_points_on_normal": best[1], "per_hour": round(best[1] / hours, 3),
            "scaled_by_sigma": True, "jump_s": 10}


def f2_onset(run, c, start, now, p):
    thr = p["channels"][c]["m"] * p["channels"][c]["sigma"]
    r = residual(run.values[c][: now + 1])
    last_end, ok = None, 0
    for s in range(start, now + 1):
        v = r[s]
        if v is not None and abs(v) <= thr:
            ok += 1
            if ok >= MIN_NORMAL:
                last_end = s
        else:
            ok = 0
    if last_end is None or last_end >= now:
        return None
    return last_end + 1


def f1_onset(run, c, start, now, p):
    if not p["pelt"].get("available") or p["pelt"].get("pen") is None:
        return None
    sig = max(1e-9, p["channels"][c]["sigma"])
    r = residual(run.values[c][: now + 1])
    pts = pelt_points([None if v is None else v / sig for v in r[start:]], p["pelt"]["pen"])
    return (start + pts[-1]) if pts else None


def run_baselines(when, set_="main"):
    p = json.load(open(PARAMS))
    items = [it for it in json.load(open(ROOT / "items/public.json")) if it["set"] == set_ and it.get(when) is not None]
    for name in ("F1", "F2", "G"):
        d = ROOT / "results/baselines" / f"{set_}_public" / f"{name}_{when}"
        d.mkdir(parents=True, exist_ok=True)
        hits = 0
        for it in items:
            path = d / f"{it['item_id']}.json"
            if path.exists():
                continue
            run = Run(it["run"]); now, start = it[when], it["archive_start"]
            if name == "G":
                onset_abs = now
            else:
                cands = [(f1_onset if name == "F1" else f2_onset)(run, c, start, now, p) for c in it["channels"]]
                cands = [x for x in cands if x is not None]
                onset_abs = min(cands) if cands else None
            rel = lambda s: s - start  # noqa: E731
            if onset_abs is None:
                onset = {"kind": "interval", "start": 0, "end": rel(now)}
            else:
                onset = {"kind": "point", "second": rel(onset_abs)}
            parsed = judge.parse_onset({"onset": onset})
            coverage = {c: list(range(0, rel(now) + 1)) for c in it["channels"]} if name != "G" else {c: [] for c in it["channels"]}
            edges = list(range(0, rel(now) + 1, 600)) + [rel(now) + 1]
            metrics = {"onset": parsed,
                       "exact": {str(tol): judge.exact(parsed, rel(it["t_on"]), tol) for tol in judge.TOLERANCES},
                       "calibration": judge.calibration(parsed, rel(it["t_on"]), coverage, edges, rel(now)),
                       "signed_error_s": (parsed[1] - rel(it["t_on"])) if parsed and parsed[0] == "point" else None}
            rec = {"item_id": it["item_id"], "set": it["set"], "subset": it["subset"], "first_episode": it.get("first_episode"),
                   "arm": name, "k": 0, "when": when, "agent": "baseline", "model": None, "now_rel": rel(now),
                   "t_on_rel": rel(it["t_on"]), "archive_len": rel(now) + 1, "L": it["L"], "channels_n": len(it["channels"]),
                   "raw_used": rel(now) + 1 if name != "G" else 0, "metrics": metrics, "outcome": "submitted",
                   "report": {"onset": onset}, "reminders": 0, "stop_reasons": [], "usage": {}, "spend_usd": 0.0,
                   "audit": [], "coverage": coverage, "error": None, "exchanges": [], "params": p if name != "G" else None,
                   "written_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")}
            tmp = path.with_suffix(".json.part"); tmp.write_text(json.dumps(rec)); os.replace(tmp, path)
            hits += metrics["exact"]["120"] == "hit"
        print(f"{name} {when}: {len(items)} items, hit@120 = {hits}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["calibrate", "run"])
    ap.add_argument("--when", default="t2", choices=["t1", "t2"])
    ap.add_argument("--set", default="main")
    a = ap.parse_args()
    calibrate() if a.cmd == "calibrate" else run_baselines(a.when, a.set)
