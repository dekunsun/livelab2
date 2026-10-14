"""The archive a session can reach, and the budget it pays (docs/question_rules.md §4–§5).

Every number a model receives comes through this module, which is why the automatic checks live here
too: the session time t is bound at construction, a request past t is cut and recorded, every reading
served is counted once per (channel, second), and the audit log keeps what was asked and what was given.
Channel names are anonymised: the model sees C1…C18 with a description, never a tag.
"""
import math

from .data import Run, load_tags

COARSE_S = 600          # the coarse map: 600-second means of the flagged channels over the whole archive
VIEW_MEANS_S = 300      # the current view's recent means
VIEW_SPAN_S = 1800
MAX_CALLS = 4
UNIT = {"heater temperature": "°C", "process temperature": "°C", "flow": "L/h", "pressure": "mbar",
        "pressure difference": "mbar", "level switch": "0/1"}


def fmt(v):
    if v is None:
        return "nan"
    s = f"{v:.3f}".rstrip("0").rstrip(".")
    return s if s not in ("", "-0") else "0"


class Archive:
    """One item's archive, bound to one session time t. All times are seconds since the archive start."""

    def __init__(self, item, t, k):
        self.item, self.t, self.k = item, t, k
        self.run = Run(item["run"])
        self.start = item["archive_start"]
        self.channels = list(self.run.channels)
        self.anon = {c: f"C{i + 1}" for i, c in enumerate(self.channels)}
        tags = load_tags()
        self.describe = {c: f"{tags[c]['role']}, {tags[c]['feature_of_interest'] or 'position not documented'}"
                         f" ({UNIT.get(tags[c]['role'], '')})".replace(" ()", "") for c in self.channels}
        self.flagged = list(item["channels"])
        self.served = {c: set() for c in self.flagged}   # unique seconds served per flagged channel
        self.calls = 0
        self.audit = []

    # --- what every arm gets -------------------------------------------------------------------
    def length(self):
        """Archive length in seconds: from the archive start to t inclusive."""
        return self.t - self.start + 1

    def rel(self, s):
        """Absolute row index -> archive-relative second (0 = archive start)."""
        return s - self.start

    def value(self, c, s):
        return self.run.values[c][s]

    def instrument_list(self):
        lines = [f"- {self.anon[c]}: {self.describe[c]}" for c in self.channels]
        return "\n".join(lines)

    def current_view(self):
        """Readings at t for all channels, the recent 300-s means of the flagged channels, and the coarse map."""
        now = "\n".join(f"- {self.anon[c]}: {fmt(self.value(c, self.t))}" for c in self.channels)
        recent = []
        for c in self.flagged:
            parts = []
            for b in range(VIEW_SPAN_S // VIEW_MEANS_S):
                end = self.t - b * VIEW_MEANS_S
                beg = max(self.start, end - VIEW_MEANS_S + 1)
                if beg > end:
                    break
                vals = [self.value(c, s) for s in range(beg, end + 1) if self.value(c, s) is not None]
                parts.append(f"[{self.rel(beg)}..{self.rel(end)}] {fmt(sum(vals) / len(vals)) if vals else 'nan'}")
            recent.append(f"- {self.anon[c]}: " + "; ".join(reversed(parts)))
        return {"now": now, "recent": "\n".join(recent), "coarse": self.coarse_map()}

    def coarse_map(self):
        """600-s means of each flagged channel from the archive start to t (the last bin may be partial)."""
        out = []
        for c in self.flagged:
            cells = []
            for beg in range(self.start, self.t + 1, COARSE_S):
                end = min(self.t, beg + COARSE_S - 1)
                vals = [self.value(c, s) for s in range(beg, end + 1) if self.value(c, s) is not None]
                cells.append(f"{self.rel(beg)}-{self.rel(end)}: {fmt(sum(vals) / len(vals)) if vals else 'nan'}")
            out.append(f"- {self.anon[c]} (mean per 600 s, seconds since archive start):\n  " + "\n  ".join(cells))
        return "\n".join(out)

    def coarse_edges(self):
        return [self.rel(b) for b in range(self.start, self.t + 1, COARSE_S)] + [self.rel(self.t) + 1]

    # --- raw data -------------------------------------------------------------------------------
    def render(self, c, beg, end):
        """Raw 1-s readings of channel c for archive-relative seconds [beg, end], 60 per line."""
        lines = [f"{self.anon[c]} ({self.describe[c]}), seconds {beg}..{end} since archive start, one reading per second:"]
        for row in range(beg, end + 1, 60):
            stop = min(end, row + 59)
            vals = " ".join(fmt(self.value(c, self.start + s)) for s in range(row, stop + 1))
            lines.append(f"{row}: {vals}")
        return "\n".join(lines)

    def fixed_window(self):
        """Arm E: the most recent min(K, archive) seconds of every flagged channel."""
        beg = max(0, self.rel(self.t) - self.k + 1)
        end = self.rel(self.t)
        for c in self.flagged:
            self.served[c].update(range(beg, end + 1))
        self.audit.append({"kind": "fixed_window", "beg": beg, "end": end})
        return "\n\n".join(self.render(c, beg, end) for c in self.flagged)

    def oracle_window(self):
        """Arm B: a window of min(K, archive) seconds containing t_on, placed with the item's seeded offset."""
        n = min(self.k, self.length())
        t_on, u = self.rel(self.item["t_on"]), self.item["u"]
        beg = int(round(t_on - u * n))
        beg = max(0, min(beg, self.rel(self.t) - n + 1))
        end = beg + n - 1
        for c in self.flagged:
            self.served[c].update(range(beg, end + 1))
        self.audit.append({"kind": "oracle_window", "beg": beg, "end": end})
        return "\n\n".join(self.render(c, beg, end) for c in self.flagged)

    def get_window(self, start, end):
        """Arm D's tool. Integer seconds since archive start; past t is cut; over budget is refused."""
        entry = {"kind": "get_window", "call": self.calls + 1, "requested": [start, end]}
        try:
            start, end = int(start), int(end)
        except (TypeError, ValueError):
            entry.update(served=None, error="start and end must be integers (seconds since archive start)")
            self.audit.append(entry)
            return {"error": entry["error"], "remaining_budget": self.remaining()}
        if self.calls >= MAX_CALLS:
            entry.update(served=None, error=f"no calls left ({MAX_CALLS} per item)")
            self.audit.append(entry)
            return {"error": entry["error"], "remaining_budget": self.remaining()}
        self.calls += 1
        cut = False
        if end > self.rel(self.t):
            end, cut = self.rel(self.t), True
        start = max(0, start)
        if start > end:
            entry.update(served=None, error="empty window (start after end, or entirely after now)", cut_at_t=cut)
            self.audit.append(entry)
            return {"error": entry["error"], "remaining_budget": self.remaining()}
        new = max(len(set(range(start, end + 1)) - self.served[c]) for c in self.flagged)
        if new > self.remaining():
            entry.update(served=None, error=f"window needs {new} new readings per channel, budget left {self.remaining()}", cut_at_t=cut)
            self.audit.append(entry)
            return {"error": entry["error"], "remaining_budget": self.remaining()}
        for c in self.flagged:
            self.served[c].update(range(start, end + 1))
        entry.update(served=[start, end], n=end - start + 1, cut_at_t=cut, max_rel_second=end,
                     remaining_after=self.remaining())
        self.audit.append(entry)
        text = "\n\n".join(self.render(c, start, end) for c in self.flagged)
        note = " (cut at the current time)" if cut else ""
        return {"served": [start, end], "n_per_channel": end - start + 1, "remaining_budget": self.remaining(),
                "calls_left": MAX_CALLS - self.calls, "data": text + note}

    def remaining(self):
        return self.k - max((len(s) for s in self.served.values()), default=0)

    # --- for the judge ---------------------------------------------------------------------------
    def coverage(self):
        """Seconds (archive-relative) served per flagged channel, as sorted lists."""
        return {c: sorted(s) for c, s in self.served.items()}
