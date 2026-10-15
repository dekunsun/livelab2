"""Run one arm × budget × ask-time over a set of items, with a mock agent or Opus 5.5.

  ./.venv/bin/python scripts/run.py --agent mock-oracle --arm D --k 1800 --when t1 --limit 3
  ./.venv/bin/python scripts/run.py --agent opus-5.5 --arm E --k 1800 --when t2 --cap 5

One JSON record per item, written atomically, never overwritten (rerun skips items with a record).
Public results go to results/; hold-out results go to holdout/results/ and never enter the repository.
The record keeps the literal system and user texts, every exchange, the audit of every window served,
the coverage the judge used, usage and spend. Spend stops at --cap (US$) for the directory.
"""
import argparse
import datetime as dt
import hashlib
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from livelab2.archive import Archive  # noqa: E402
from livelab2 import judge  # noqa: E402
from livelab2.mocks import run_mock  # noqa: E402
from livelab2.model import MODELS, load_dotenv, run_session  # noqa: E402
from livelab2.prompts import SYSTEM, TOOLS, leak_scan, sha, user_message  # noqa: E402


def load_items(split):
    path = ROOT / ("holdout/items.json" if split == "holdout" else "items/public.json")
    return json.load(open(path, encoding="utf-8"))


def out_dir(agent, split, set_, arm, k, when, rep=0):
    base = ROOT / ("holdout/results" if split == "holdout" else "results")
    return base / agent / f"{set_}_{split}" / (f"{arm}_K{k}_{when}" + (f".rep{rep}" if rep else ""))


def spent_in(d):
    total = 0.0
    for p in d.glob("*.json"):
        try:
            total += json.load(open(p)).get("spend_usd", 0.0)
        except Exception:
            pass
    return total


def run_item(item, agent, arm, k, when):
    t = item[when]
    archive = Archive(item, t, k)
    raw = None
    if arm == "E":
        raw = archive.fixed_window()
    elif arm == "B":
        raw = archive.oracle_window()
    user = user_message(archive, arm, raw)
    tools = TOOLS if arm == "D" else [TOOLS[0]]
    leaks = leak_scan(SYSTEM, user)
    if leaks:
        raise RuntimeError(f"leak check failed for {item['item_id']}: {leaks[:5]}")
    t_on_rel = archive.rel(item["t_on"]) if item.get("t_on") is not None else None
    if agent.startswith("mock-"):
        rec = run_mock(agent[5:], archive, arm, t_on_rel, seed=f"{item['item_id']}|{arm}|{k}|{when}")
    else:
        rec = run_session(MODELS[agent], SYSTEM, user, tools, archive, allow_fetch=(arm == "D"))
    onset = judge.parse_onset(rec.get("report"))
    metrics = {"onset": onset}
    if t_on_rel is not None:
        metrics["exact"] = {str(tol): judge.exact(onset, t_on_rel, tol) for tol in judge.TOLERANCES}
        metrics["calibration"] = judge.calibration(onset, t_on_rel, rec["coverage"], archive.coarse_edges(), archive.rel(t))
        metrics["early_evidence"] = judge.early_evidence(onset, t_on_rel, archive.rel(item["t_cause"]) if item.get("t_cause") is not None else None)
        metrics["signed_error_s"] = (onset[1] - t_on_rel) if onset and onset[0] == "point" else None
    else:
        metrics["false_alarm_handled"] = onset is not None and onset[0] == "none"
    used = max((len(v) for v in rec["coverage"].values()), default=0)
    record = {
        "item_id": item["item_id"], "set": item["set"], "subset": item["subset"], "first_episode": item.get("first_episode"),
        "arm": arm, "k": k, "when": when, "agent": agent, "model": MODELS.get(agent),
        "now_rel": archive.rel(t), "t_on_rel": t_on_rel, "archive_len": archive.length(), "L": item.get("L"),
        "channels_n": len(archive.flagged), "raw_used": used, "metrics": metrics,
        "system_sha256": sha(SYSTEM), "user_sha256": sha(user), "system_text": SYSTEM, "user_text": user,
        "written_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        **{key: rec[key] for key in ("outcome", "report", "reminders", "stop_reasons", "usage", "spend_usd", "audit", "coverage", "error", "exchanges")},
    }
    return record


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--agent", required=True, choices=["mock-now", "mock-random", "mock-oracle"] + sorted(MODELS))
    ap.add_argument("--arm", required=True, choices=["A", "E", "D", "B"])
    ap.add_argument("--k", type=int, default=1800, choices=[600, 1800, 3600])
    ap.add_argument("--when", required=True, choices=["t1", "t2"])
    ap.add_argument("--set", default="main", choices=["main", "short", "injected"])
    ap.add_argument("--split", default="public", choices=["public", "holdout"])
    ap.add_argument("--items", nargs="*", help="only these item ids")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--cap", type=float, default=5.0, help="stop once this directory's spend passes this many US$")
    args = ap.parse_args()
    load_dotenv()
    items = [it for it in load_items(args.split) if it["set"] == args.set and it.get(args.when) is not None]
    if args.items:
        items = [it for it in items if it["item_id"] in set(args.items)]
    if args.limit:
        items = items[: args.limit]
    d = out_dir(args.agent, args.split, args.set, args.arm, args.k, args.when)
    d.mkdir(parents=True, exist_ok=True)
    done, skipped, spend = 0, 0, spent_in(d)
    for it in items:
        path = d / f"{it['item_id']}.json"
        if path.exists():
            skipped += 1
            continue
        if spend >= args.cap:
            print(f"cap reached: US${spend:.2f} >= {args.cap}; stopping before {it['item_id']}")
            break
        rec = run_item(it, args.agent, args.arm, args.k, args.when)
        tmp = path.with_suffix(".json.part")
        tmp.write_text(json.dumps(rec, ensure_ascii=False))
        os.replace(tmp, path)
        spend += rec["spend_usd"]
        done += 1
        m = rec["metrics"]
        print(f"{it['item_id']} {rec['outcome']:>12} exact@120={m.get('exact', {}).get('120', '-'):>7} "
              f"cal={m.get('calibration', {}).get('class', '-')} raw={rec['raw_used']} spend=US${rec['spend_usd']:.3f}")
    print(f"done {done}, skipped {skipped}, directory spend US${spend:.2f} -> {d.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
