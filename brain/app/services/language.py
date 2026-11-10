import re
from typing import Optional


def detect_language(text: Optional[str]) -> str:
    """
    Lightweight script-based language detector.
    Identifies Sinhala, Tamil, or English/Singlish.
    """
    if not text:
        return "en"

    # Sinhala Unicode Block: U+0D80 - U+0DFF
    if re.search(r"[\u0D80-\u0DFF]", text):
        return "si"

    # Tamil Unicode Block: U+0B80 - U+0BFF
    if re.search(r"[\u0B80-\u0BFF]", text):
        return "ta"

    return "en"

