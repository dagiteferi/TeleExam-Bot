"""
Formatting for admin announcements.

The admin panel writes announcements with a small markup (the same as Telegram's own
shortcuts) and this turns it into Telegram HTML:

    **bold**   __italic__   ++underline++   ~~strikethrough~~
    ||spoiler||   `code`   [link text](https://example.com)

Everything else is escaped, and a marker without a matching closing marker stays as
plain text, so the result is always valid HTML Telegram accepts.
Keep in sync with src/lib/announcementFormat.tsx in the admin panel.
"""
import re

from bot.utils.text import esc

# marker -> HTML tag. Order matters: checked in this order at each position.
_PAIRED = (
    ("**", "b"),
    ("__", "i"),
    ("++", "u"),
    ("~~", "s"),
    ("||", "tg-spoiler"),
)

_LINK = re.compile(r"\[([^\]\n]+)\]\((https?://[^\s)]+)\)")


def _render(text: str, allow_links: bool = True) -> str:
    out = []
    i = 0
    n = len(text)
    while i < n:
        # `code`: shown as-is, no formatting inside
        if text[i] == "`":
            end = text.find("`", i + 1)
            if end > i + 1:
                out.append(f"<code>{esc(text[i + 1:end])}</code>")
                i = end + 1
                continue

        if allow_links and text[i] == "[":
            m = _LINK.match(text, i)
            if m:
                url = esc(m.group(2)).replace('"', "&quot;")
                out.append(f'<a href="{url}">{_render(m.group(1), allow_links=False)}</a>')
                i = m.end()
                continue

        for marker, tag in _PAIRED:
            if text.startswith(marker, i):
                start = i + len(marker)
                end = text.find(marker, start)
                if end > start:
                    out.append(f"<{tag}>{_render(text[start:end], allow_links)}</{tag}>")
                    i = end + len(marker)
                    break
        else:
            out.append(esc(text[i]))
            i += 1
    return "".join(out)


def format_announcement(text: str) -> str:
    """Admin announcement markup -> Telegram HTML (always well-formed)."""
    return _render(text or "")
