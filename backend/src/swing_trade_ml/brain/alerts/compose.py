"""One grouped Telegram message per run, in plain words.

Telegram is sent in HTML mode, so every piece of text that came from data
(stock names, reasons, headlines) is escaped; only our own tags are markup.
"""

from __future__ import annotations

from html import escape
from zoneinfo import ZoneInfo

from swing_trade_ml.brain.alerts.detectors import AlertItem, RunView

IST = ZoneInfo("Asia/Kolkata")
SECTIONS = (("banner", None), ("holding", "Holdings needing attention"), ("trade", "New ideas"))


def compose(items: list[AlertItem], run: RunView) -> str | None:
    if not items:
        return None
    when = run.started_at.astimezone(IST).strftime("%d %b, %H:%M")
    lines = [f"🧠 <b>TradeMind brain</b> · {escape(when)}"]
    shown: set[str] = set()
    for kind, title in SECTIONS:
        group = [i for i in items if i.kind == kind]
        if not group:
            continue
        lines.append("")
        if title:
            lines.append(f"<b>{escape(title)}</b>")
        lines += [f"• {escape(i.text)}" for i in group]
        shown.update(i.key for i in group)
    others = [i for i in items if i.key not in shown]
    if others:
        lines.append("")
        lines += [f"• {escape(i.text)}" for i in others]
    lines += ["", "<i>The brain only suggests; it places no orders.</i>"]
    return "\n".join(lines)
