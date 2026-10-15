"""The automatic checks every run must pass (docs/question_rules.md §9), over a results tree.

  ./.venv/bin/python scripts/checks.py results/mock-oracle/main_public

1. every served second <= now;  2. no forbidden string in any request text;  3. replay: the prompts
re-render to the recorded sha256;  4. the audit's latest served second <= now;  5. unique seconds per
channel <= K, and E/B windows are exactly min(K, archive);  6. the loader's clock assertions held (a
record exists only if they did);  7. no response stopped at the output cap.
Prints one line per check with the number of records failing it; exits 1 if any fail.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INCLUDE_REPS = __import__('os').environ.get('INCLUDE_REPS') == '1'   # checks: set to 1 to include repetitions
sys.path.insert(0, str(ROOT))
from livelab2.archive import Archive  # noqa: E402
from livelab2.prompts import SYSTEM, leak_scan, sha, user_message  # noqa: E402


def main(tree):
    items = {it["item_id"]: it for it in json.load(open(ROOT / "items/public.json"))}
    if (ROOT / "holdout/items.json").exists():
        items.update({it["item_id"]: it for it in json.load(open(ROOT / "holdout/items.json"))})
    fails = {k: [] for k in ("1_served_le_now", "2_leak", "3_replay", "4_audit_le_now", "5_budget", "7_output_cap")}
    n = 0
    for p in sorted(x for x in Path(tree).glob("*/*.json") if ".rep" not in x.parent.name or INCLUDE_REPS):
        r = json.load(open(p)); n += 1
        now = r["now_rel"]
        served = r["coverage"]
        if any(s > now for v in served.values() for s in v):
            fails["1_served_le_now"].append(r["item_id"])
        if leak_scan(r["system_text"], r["user_text"]):
            fails["2_leak"].append(r["item_id"])
        if any((a.get("max_rel_second") or 0) > now for a in r["audit"]):
            fails["4_audit_le_now"].append(r["item_id"])
        used = max((len(v) for v in served.values()), default=0)
        if used > r["k"]:
            fails["5_budget"].append(r["item_id"])
        if r["arm"] in ("E", "B") and used != min(r["k"], r["archive_len"]):
            fails["5_budget"].append(r["item_id"] + "(window length)")
        if "max_tokens" in (r.get("stop_reasons") or []):
            fails["7_output_cap"].append(r["item_id"])
        # 3. replay the prompt construction
        it = items[r["item_id"]]
        arch = Archive(it, it[r["when"]], r["k"])
        raw = arch.fixed_window() if r["arm"] == "E" else arch.oracle_window() if r["arm"] == "B" else None
        if sha(user_message(arch, r["arm"], raw)) != r["user_sha256"] or sha(SYSTEM) != r["system_sha256"]:
            fails["3_replay"].append(r["item_id"])
    bad = 0
    for k, v in fails.items():
        print(f"{k}: {len(v)} failing" + (f" -> {v[:6]}" if v else ""))
        bad += len(v)
    print(f"records checked: {n}; check 6 (clock) is enforced by the loader at generation and replay time")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main(sys.argv[1])
