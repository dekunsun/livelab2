"""The task statement and the tool schemas (docs/question_rules.md §5–§6).

One system instruction for every arm that uses a model; the arm changes only which raw data the user
message carries and whether get_window is available. The instruction states the rules the judge
applies (1.0's lesson: a task must state the rules it is scored by), including the calibrated answers
that count when the raw evidence does not cover the onset.
"""
import hashlib
import re

from .archive import MAX_CALLS

SYSTEM = """You are the historical-analysis assistant of a monitoring system for a laboratory batch distillation plant. The plant records 18 sensor channels once per second. You are called at one moment, "now", just after the system flagged that a channel is deviating from its normal range. Your one task: find WHEN the current anomaly first became observable in the flagged channel's recorded readings.

Definitions
- The archive is the recorded data from second 0 (the start of this record) up to now. Nothing after now exists for you. Second 0 is either the start of the plant's operation phase or the moment after which the plant had returned to normal; treat it as the beginning of the record.
- The onset is the first second at which the flagged channel's recorded readings show the anomaly, as a process expert reading the data would judge it. It is not the moment the physical cause began, which can be earlier and invisible.
- A batch distillation run drifts by itself (temperatures climb as the light component leaves), so a slow trend is not an anomaly; look for a departure from the run's own prior behaviour.

How your answer is scored (fixed in advance)
- A point answer (one second) is correct if it lies within ±120 s of the expert's onset second (also reported at ±60 s and ±180 s).
- An interval [start, end] is correct if it contains the onset and is at most 240 s wide.
- If the raw readings you have do not cover the onset, do not invent a precise second. Answer with an interval whose ends are seconds you actually have data for (raw readings, or edges of the 600-second map) and that you believe contains the onset, or with earlier_than T, meaning "before the earliest raw second I received". These are calibrated answers and are scored as such; a precise second without covering data is scored as fabricated precision.
- If you believe the record contains no anomaly onset (a false alarm), answer none.
- Raw readings are costed: at most K readings per channel in total for this item. The current view and the 600-second map are free.

Answer by calling the report tool exactly once, briefly. The evidence list should name the seconds and channel you relied on."""

ARM_TEXT = {
    "A": "You have only the current view below. No raw readings are available in this condition.",
    "E": "Raw readings provided (the most recent {n} seconds of the flagged channel{plural}; this is all the raw data available in this condition, K = {k} per channel):",
    "B": "Raw readings provided (one window of {n} seconds of the flagged channel{plural}, selected for you; this is all the raw data available in this condition, K = {k} per channel):",
    "D": "You may fetch raw readings with get_window(start, end): integers, seconds since the start of the record, end at most now; each call returns the flagged channel{plural} at one reading per second. At most {calls} calls and at most K = {k} new readings per channel in total; a call that would exceed the remaining budget is refused and tells you what is left. The response of each call reports the window actually served and the remaining budget. Fetch what you need, then call report.",
}

TOOLS = [
    {"name": "report", "description": "Submit your answer. Call it exactly once.",
     "input_schema": {"type": "object", "required": ["onset", "evidence", "state"], "properties": {
         "onset": {"type": "object", "required": ["kind"], "properties": {
             "kind": {"type": "string", "enum": ["point", "interval", "earlier_than", "none"]},
             "second": {"type": "integer", "description": "for point: the onset second; for earlier_than: the onset is before this second"},
             "start": {"type": "integer", "description": "for interval"},
             "end": {"type": "integer", "description": "for interval"}}},
         "evidence": {"type": "array", "items": {"type": "object", "properties": {
             "channel": {"type": "string"}, "start": {"type": "integer"}, "end": {"type": "integer"},
             "observation": {"type": "string"}}}},
         "cause": {"type": "string", "description": "your best reading of the cause, or unknown"},
         "state": {"type": "string", "enum": ["anomalous", "normal", "cannot_tell"]}}}},
    {"name": "get_window", "description": "Fetch raw 1-second readings of the flagged channel(s) for [start, end], seconds since the start of the record.",
     "input_schema": {"type": "object", "required": ["start", "end"], "properties": {
         "start": {"type": "integer"}, "end": {"type": "integer"}}}},
]

# Strings that would reveal the answer or the identity of the run (automatic check 2)
FORBIDDEN = re.compile(r"batch_dist|test_anormal|train_normal|experiment_|operating_point|hasBeginning|"
                       r"\b(LS70[12]|T7(0[1-9]|1[0-2])|FT70[34]|FYI702|PDI70[12]|PY23)\b|\d{1,2}:\d{2}:\d{2}", re.I)


def user_message(archive, arm, raw_text=None):
    view = archive.current_view()
    flagged = ", ".join(archive.anon[c] for c in archive.flagged)
    plural = "s" if len(archive.flagged) > 1 else ""
    n = min(archive.k, archive.length())
    now = archive.rel(archive.t)
    parts = [
        f"Now = second {now} since the start of the record. The record starts at second 0.",
        f"Flagged by the system: channel {flagged} is deviating from its normal range now. The system does not say since when.",
        "Instruments (channel: type, position (unit)):\n" + archive.instrument_list(),
        "Current readings at now:\n" + view["now"],
        "Recent means of the flagged channel(s), 300-second bins ending now:\n" + view["recent"],
        "600-second map of the flagged channel(s) over the whole record (free):\n" + view["coarse"],
        ARM_TEXT[arm].format(n=n, k=archive.k, plural=plural, calls=MAX_CALLS),
    ]
    if raw_text:
        parts.append(raw_text)
    text = "\n\n".join(parts)
    return text


def leak_scan(*texts):
    """Automatic check 2: returns the forbidden fragments found (an empty list means clean)."""
    found = []
    for t in texts:
        found += [m.group(0) for m in FORBIDDEN.finditer(t)]
    return found


def sha(text):
    return hashlib.sha256(text.encode()).hexdigest()
