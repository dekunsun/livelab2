"""Load one run of the batch distillation dataset (docs/question_rules.md §1).

Time: the dataset writes HH:MM:SS only. A run is loaded as integer seconds since the first row of its
Operation phase; the loader asserts the clock is monotone, has no midnight wrap, and advances 1 s per
row, so a row index is a relative second. Rows with an empty Time are dropped and counted.

The sensor file and the label file of a run must have the same rows (same count, same first and
last clock) or the run is refused: no silent alignment.
"""
import csv
import hashlib
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data/raw/batch"
LABELS = RAW / "labels/00_Batch_Distillation_Plant_M-202210_Timeseries_Label_Anomaly_Metadata/Operation"
SENSORS = RAW / "sensors/01_Batch_Distillation_Plant_M-202210_Timeseries_Sensors/Operation"
TAGS = ROOT / "docs/data/tags.csv"
HOLDOUT = ROOT / "holdout/holdout_runs.txt"
USED_IN_1 = ROOT / "docs/data/used_in_livelab1.txt"
ZERO = ("0", "0.0", "")


def seconds(s):
    h, m, x = (int(v) for v in s.strip().split(":"))
    return h * 3600 + m * 60 + x


def run_paths(run_id):
    system, op, kind, n = run_id.split("|")
    rel = f"{system}/operating_point_{op[2:]}/{kind}_experiment_{n}"
    return LABELS / f"{rel}.csv", LABELS / f"{rel}.yaml", SENSORS / f"{rel}.csv"


def read_rows(path):
    with open(path, newline="", encoding="utf-8", errors="replace") as f:
        rows = list(csv.DictReader(f))
    kept = [r for r in rows if r["Time"].strip()]
    return kept, len(rows) - len(kept)


def seed_int(*parts):
    """Deterministic seed from strings: the first 16 hex digits of sha256 (docs/question_rules.md §3, §5)."""
    return int(hashlib.sha256("|".join(parts).encode()).hexdigest()[:16], 16)


def load_tags():
    with open(TAGS, newline="", encoding="utf-8") as f:
        return {r["tag"]: r for r in csv.DictReader(f)}


def holdout_runs():
    return {l.strip() for l in open(HOLDOUT) if l.strip()} if HOLDOUT.exists() else set()


def used_runs():
    return {l.strip() for l in open(USED_IN_1) if l.strip()}


class Run:
    """One run's Operation phase: labels, sensor values per channel, and the YAML anomaly entries."""

    def __init__(self, run_id):
        self.run_id = run_id
        lab_path, yaml_path, sen_path = run_paths(run_id)
        lab, self.dropped_label_rows = read_rows(lab_path)
        sen, self.dropped_sensor_rows = read_rows(sen_path)
        if len(lab) != len(sen) or lab[0]["Time"] != sen[0]["Time"] or lab[-1]["Time"] != sen[-1]["Time"]:
            raise ValueError(f"{run_id}: label and sensor rows do not align ({len(lab)} vs {len(sen)})")
        t = [seconds(r["Time"]) for r in sen]
        self.t0 = t[0]
        for i, (a, b) in enumerate(zip(t, t[1:])):
            if b - a != 1:
                raise ValueError(f"{run_id}: clock step {b - a} s at row {i} (wrap or gap)")
        self.n = len(sen)
        self.labels = [r["Label (anomaly)"].strip() for r in lab]
        self.channels = [c for c in sen[0].keys() if c != "Time"]
        self.values = {}
        for c in self.channels:
            col = []
            for r in sen:
                v = r[c].strip()
                col.append(None if v in ("", "nan", "NaN") else float(v))
            self.values[c] = col
        self._yaml_path = yaml_path

    def rel(self, clock):
        """A YAML clock (HH:MM:SS) as a relative second; may fall outside [0, n)."""
        return seconds(str(clock)) - self.t0

    def anomaly_entries(self):
        """YAML entries with a class: [(begin_rel, end_rel), ...] windows and the sensors named anywhere inside."""
        out = []
        doc = yaml.safe_load(open(self._yaml_path, encoding="utf-8")) or {}
        for a in doc.get("anomalies", []) or []:
            if not isinstance(a, dict) or a.get("class") in (None, "None"):
                continue
            begins = a.get("hasBeginning"); ends = a.get("hasEnd")
            begins = begins if isinstance(begins, list) else [begins]
            ends = ends if isinstance(ends, list) else [ends]
            windows = []
            for b, e in zip(begins, ends):
                try:
                    windows.append((self.rel(b), self.rel(e)))
                except (ValueError, AttributeError):
                    pass
            out.append({"windows": windows, "sensors": sorted(_sensor_ids(a, set())),
                        "category": a.get("hasCategory"), "class": a.get("class")})
        return out

    def episodes(self):
        """Maximal non-zero label blocks, with the first contiguous label-2 segment inside each.

        Yields dicts: block (i, j), seg (s, e) or None, label1_start (the block start if it opens
        with label 1 before the segment), prev_end (end of the previous non-zero block, 0 if none).
        """
        lab = self.labels
        i, prev_end, k = 0, 0, 0
        while i < len(lab):
            if lab[i] in ZERO:
                i += 1
                continue
            j = i
            while j < len(lab) and lab[j] not in ZERO:
                j += 1
            seg = None
            if "2" in lab[i:j]:
                s = i + lab[i:j].index("2")
                e = s
                while e < j and lab[e] == "2":
                    e += 1
                seg = (s, e)
            yield {"index": k, "block": (i, j), "seg": seg, "prev_end": prev_end,
                   "label1_start": i if (seg and lab[i] == "1" and i < seg[0]) else None}
            prev_end, i, k = j, j, k + 1


def _sensor_ids(node, out):
    if isinstance(node, dict):
        s = node.get("madeBySensor")
        if isinstance(s, dict) and isinstance(s.get("Sensor"), dict) and s["Sensor"].get("id"):
            out.add(str(s["Sensor"]["id"]))
        for v in node.values():
            _sensor_ids(v, out)
    elif isinstance(node, list):
        for v in node:
            _sensor_ids(v, out)
    return out
