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
    # Insert after the first character to make it harder to strip
    if len(text) > 1:
        return text[0] + watermark + text[1:]
    return watermark + text


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
