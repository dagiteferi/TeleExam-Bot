import html
from typing import Any, List

from aiogram.types import Message

# Telegram allows 4096 characters per message; keep headroom for tags and the watermark.
MAX_MESSAGE_LENGTH = 4000


def esc(value: Any) -> str:
    """Escape any dynamic value before putting it inside an HTML-formatted message."""
    if value is None:
        return ""
    return html.escape(str(value), quote=False)


def _hard_split_point(text: str, limit: int) -> int:
    """Index to cut an over-long line at, without splitting an HTML entity like &amp;."""
    cut = limit
    amp = text.rfind("&", max(0, cut - 10), cut)
    if amp != -1 and ";" not in text[amp:cut]:
        cut = amp
    return cut


def split_message(text: str, limit: int = MAX_MESSAGE_LENGTH) -> List[str]:
    """Split text into chunks under the limit, preferring line breaks."""
    if len(text) <= limit:
        return [text]

    chunks: List[str] = []
    current = ""
    for line in text.split("\n"):
        while len(line) > limit:
            cut = _hard_split_point(line, limit)
            if current:
                chunks.append(current)
                current = ""
            chunks.append(line[:cut])
            line = line[cut:]
        candidate = f"{current}\n{line}" if current else line
        if len(candidate) > limit:
            chunks.append(current)
            current = line
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks


async def answer_long(message: Message, text: str, reply_markup: Any = None, **kwargs: Any) -> None:
    """message.answer() that splits long text; the keyboard goes on the last chunk."""
    chunks = split_message(text)
    for i, chunk in enumerate(chunks):
        is_last = i == len(chunks) - 1
        await message.answer(chunk, reply_markup=reply_markup if is_last else None, **kwargs)
