"""
Digital Watermarking Utility for TeleExam Bot.

Embeds an invisible, traceable watermark into question text using
Unicode zero-width characters. This allows identifying which user
leaked or scraped question content.

Zero-width Space  (U+200B) = binary 0
Zero-width Non-joiner (U+200C) = binary 1
"""

ZWS = "\u200b"   # zero-width space  = bit 0
ZWNJ = "\u200c"  # zero-width non-joiner = bit 1
SEPARATOR = "\u200d"  # zero-width joiner = separator between bytes


def _int_to_bits(n: int, bit_length: int = 32) -> str:
    """Convert an integer to a zero-width character binary string."""
    bits = bin(n & ((1 << bit_length) - 1))[2:].zfill(bit_length)
    return "".join(ZWNJ if b == "1" else ZWS for b in bits)


def embed_watermark(text: str, telegram_id: int) -> str:
    """
    Embed an invisible watermark (encoded telegram_id) into the text.
    The watermark is inserted after the first character so it's imperceptible.
    """
    watermark = SEPARATOR + _int_to_bits(telegram_id) + SEPARATOR
    # Insert after the first visible character to make it harder to strip. Leading
    # HTML tags (e.g. "<b>") and entities (e.g. "&amp;") are skipped: putting the
    # watermark inside one breaks the HTML and Telegram rejects the whole message.
    i = 0
    while i < len(text) and text[i] == "<":
        close = text.find(">", i)
        if close == -1:
            break
        i = close + 1
    if i >= len(text):
        return watermark + text
    end = i + 1
    if text[i] == "&":
        semi = text.find(";", i, i + 10)
        if semi != -1:
            end = semi + 1
    return text[:end] + watermark + text[end:]


def extract_watermark(text: str) -> int | None:
    """
    Attempt to extract and decode the watermark from text.
    Returns the telegram_id if found, or None if no watermark is present.
    """
    try:
        # Find the separator markers
        start = text.find(SEPARATOR)
        if start == -1:
            return None
        end = text.find(SEPARATOR, start + 1)
        if end == -1:
            return None
        encoded_bits = text[start + 1:end]
        # Decode bits back to integer
        bits = "".join("1" if c == ZWNJ else "0" for c in encoded_bits if c in (ZWS, ZWNJ))
        return int(bits, 2) if bits else None
    except Exception:
        return None
