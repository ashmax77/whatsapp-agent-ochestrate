"""Shared text normalisation for keyword search (BM25) and the local embedding fallback."""
import re
from typing import List

# Words that carry no meaning for search. Without this list, "What is the capital
# of France?" would match every chunk that contains "what", "is" or "the".
STOPWORDS = frozenset("""
a an and are as at be been but by can could did do does for from had has have how i
if in into is it its me my of on or our please so tell than that the their them then
there these they this those to too us was we what when where which who whom why will
with would you your yours about any also just get got want need like s
""".split())


def stem(token: str) -> str:
    """Very light plural/verb stemmer: offers -> offer, closes -> close, hours -> hour."""
    if len(token) > 4 and token.endswith("ies"):
        return token[:-3] + "y"
    if len(token) > 3 and token.endswith("s") and not token.endswith("ss"):
        return token[:-1]
    return token


def tokenize(text: str) -> List[str]:
    """Lowercase, drop stopwords, stem: "Offers for STUDENT15" -> ["offer", "student15"]."""
    return [stem(t) for t in re.findall(r"\w+", text.lower()) if t not in STOPWORDS]

