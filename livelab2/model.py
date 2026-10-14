"""The Anthropic Messages API over plain HTTP, with the two tools, every exchange recorded.

Follows 1.0's runner v2 rules: the literal request body is kept, every server message is saved,
stop reasons are recorded, an answer that stops at the output cap is an infrastructure failure, and at
most one reminder ("Call report now.") is sent when a turn ends without the report. The session time
never comes from the model: get_window is served by the Archive bound to the item's t.
"""
import json
import os
import ssl
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
URL = "https://api.anthropic.com/v1/messages"
VERSION = "2023-06-01"
MODELS = {"opus-5.5": "claude-opus-5-5"}
PRICE = {"claude-opus-5-5": (4.0, 20.0)}          # US$ per million input / output tokens (1.0's table)
MAX_TOKENS = 8192
TIMEOUT_S = 180
MAX_TURNS = 8                                     # 4 fetches + refusals + the report, with margin
REMINDER = "Call report now with your answer."


def load_dotenv(path=ROOT / ".env"):
    if path.exists():
        for line in path.read_text().splitlines():
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def _ssl():
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


def post(body, key):
    req = urllib.request.Request(URL, data=json.dumps(body).encode(), method="POST", headers={
        "x-api-key": key, "anthropic-version": VERSION, "content-type": "application/json"})
    for attempt in range(5):
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT_S, context=_ssl()) as r:
                return json.loads(r.read().decode()), None
        except urllib.error.HTTPError as e:
            text = e.read().decode(errors="replace")
            if e.code in (429, 500, 502, 503, 529) and attempt < 4:
                time.sleep(5 * (attempt + 1))
                continue
            return None, f"HTTP {e.code}: {text[:400]}"
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            if attempt < 4:
                time.sleep(5 * (attempt + 1))
                continue
            return None, f"transport: {e}"
    return None, "unreachable"


def cost(model, usage):
    pin, pout = PRICE[model]
    i = usage.get("input_tokens", 0) + usage.get("cache_creation_input_tokens", 0) * 1.25 \
        + usage.get("cache_read_input_tokens", 0) * 0.1
    return (i * pin + usage.get("output_tokens", 0) * pout) / 1e6


def run_session(model, system, user_text, tools, archive, allow_fetch):
    """One item, one arm. Returns a record with every exchange, the audit, usage and the report args."""
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise RuntimeError("ANTHROPIC_API_KEY is not set (put it in .env, which is gitignored)")
    messages = [{"role": "user", "content": user_text}]
    exchanges, usage_total, spend = [], {}, 0.0
    report, reminders, stop_reasons = None, 0, []
    body_base = {"model": model, "max_tokens": MAX_TOKENS, "tools": tools, "tool_choice": {"type": "auto"},
                 "system": [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}]}
    for turn in range(MAX_TURNS):
        body = dict(body_base, messages=messages)
        resp, err = post(body, key)
        exchanges.append({"turn": turn, "request_messages": messages[-1], "response": resp, "error": err})
        if err:
            return _record("transport_error", exchanges, archive, usage_total, spend, report, reminders, stop_reasons, err)
        u = resp.get("usage", {})
        for k, v in u.items():
            if isinstance(v, (int, float)):
                usage_total[k] = usage_total.get(k, 0) + v
        spend += cost(model, u)
        stop_reasons.append(resp.get("stop_reason"))
        if resp.get("stop_reason") == "max_tokens":
            return _record("output_cap", exchanges, archive, usage_total, spend, report, reminders, stop_reasons)
        content = resp.get("content", [])
        messages.append({"role": "assistant", "content": content})
        tool_uses = [c for c in content if c.get("type") == "tool_use"]
        if not tool_uses:
            if reminders >= 1:
                return _record("no_report", exchanges, archive, usage_total, spend, report, reminders, stop_reasons)
            reminders += 1
            messages.append({"role": "user", "content": REMINDER})
            continue
        results = []
        for tu in tool_uses:
            if tu["name"] == "report":
                report = tu.get("input")
                results.append({"type": "tool_result", "tool_use_id": tu["id"], "content": "recorded"})
            elif tu["name"] == "get_window" and allow_fetch:
                out = archive.get_window(tu["input"].get("start"), tu["input"].get("end"))
                results.append({"type": "tool_result", "tool_use_id": tu["id"], "content": json.dumps(out)})
            else:
                results.append({"type": "tool_result", "tool_use_id": tu["id"], "is_error": True,
                                "content": "this tool is not available in this condition"})
        if report is not None:
            return _record("submitted", exchanges, archive, usage_total, spend, report, reminders, stop_reasons)
        messages.append({"role": "user", "content": results})
    return _record("turn_limit", exchanges, archive, usage_total, spend, report, reminders, stop_reasons)


def _record(outcome, exchanges, archive, usage, spend, report, reminders, stop_reasons, error=None):
    return {"outcome": outcome, "report": report, "reminders": reminders, "stop_reasons": stop_reasons,
            "usage": usage, "spend_usd": round(spend, 5), "audit": archive.audit, "coverage": archive.coverage(),
            "error": error, "exchanges": exchanges}
