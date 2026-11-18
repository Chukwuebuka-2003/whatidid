"""Text utilities: tokenising, slugging, matching an entry against a plan item,
duration formatting and a small distraction lexicon.

Deliberately boring and dependency-free. The point is that grading works
without an API key, so the heuristics have to be honest about what they know:
an entry either carries an objective's hashtag (exact credit), or its words
overlap the objective (partial credit, reported as an estimate).
"""
from __future__ import annotations

import re
import unicodedata

STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "of", "to", "in", "on", "for", "with",
    "at", "by", "from", "up", "about", "into", "over", "after", "is", "are", "was",
    "were", "be", "been", "being", "it", "its", "this", "that", "these", "those",
    "i", "we", "you", "he", "she", "they", "me", "my", "our", "your", "their",
    "do", "did", "does", "done", "doing", "have", "has", "had", "will", "would",
    "can", "could", "should", "may", "might", "must", "not", "no", "so", "if",
    "then", "than", "as", "there", "here", "when", "while", "also", "just", "some",
    "more", "most", "very", "much", "get", "got", "make", "made", "go", "went",
    "new", "again", "still", "only", "all", "any", "each", "other",
}

# Words that mean "this was not the work". Kept small and obvious on purpose:
# a false accusation is worse than a missing one.
DISTRACTION_LEXICON: dict[str, tuple[str, ...]] = {
    "social feeds": ("twitter", "x.com", "bluesky", "mastodon", "reddit", "linkedin",
                     "facebook", "instagram", "tiktok", "scrolling", "scroll", "feed"),
    "video": ("youtube", "netflix", "twitch", "video", "videos", "watching", "episode"),
    "news and rabbit holes": ("news", "hacker news", "hn", "wikipedia", "wiki",
                              "rabbit hole", "browsing", "surfing"),
    "chat and inbox": ("slack", "discord", "whatsapp", "telegram", "inbox", "email",
                       "emails", "twitter dms", "messages"),
    "admin and yak-shaving": ("admin", "paperwork", "invoices", "receipts", "booking",
                              "faffing", "tidying", "organising", "organizing",
                              "reorganising", "reorganizing", "filing"),
}

# Things people say that mean real work, which keeps the "focus" signal sane.
WORK_SIGNALS = (
    "wrote", "drafted", "designed", "built", "debugged", "fixed", "reviewed",
    "read", "studied", "practised", "practiced", "shipped", "deployed", "tested",
    "compiled", "refactored", "analysed", "analyzed", "planned", "researched",
    "interviewed", "recorded", "drew", "modelled", "modeled", "presented",
)

TAG_RE = re.compile(r"(?:^|\s)#([a-z0-9][a-z0-9\-_]{0,40})", re.IGNORECASE)


def slugify(text: str, max_len: int = 40) -> str:
    """Stable, typeable hashtag for a plan item: 'Ship the beta!' -> 'ship-the-beta'.

    Every word is kept, stopwords included, so the tag is exactly what the plan
    item says with dashes for spaces. Anything cleverer makes the tag
    unguessable, and an unguessable tag never gets typed.
    """
    norm = unicodedata.normalize("NFKD", text or "")
    norm = norm.encode("ascii", "ignore").decode("ascii").lower()
    words = [w for w in re.split(r"[^a-z0-9]+", norm) if w]
    kept: list[str] = []
    length = 0
    for word in words:
        addition = len(word) + (1 if kept else 0)
        if kept and length + addition > max_len:
            break
        kept.append(word)
        length += addition
    slug = "-".join(kept)[:max_len].strip("-")
    return slug or "item"


def tokens(text: str) -> list[str]:
    """Content words, crudely stemmed so 'drafting' matches 'draft'.

    Hyphens are separators: a hashtag's words are also words in the entry.
    """
    norm = unicodedata.normalize("NFKD", text or "").lower()
    raw = re.findall(r"[a-z0-9][a-z0-9+']*", norm)
    out: list[str] = []
    for word in raw:
        word = word.strip("-'#")
        if len(word) < 2 or word in STOPWORDS or word.isdigit():
            continue
        for suffix in ("ing", "ed", "es", "s"):
            if len(word) > len(suffix) + 3 and word.endswith(suffix):
                word = word[: -len(suffix)]
                break
        if word not in out:
            out.append(word)
    return out


def tags_in(text: str) -> list[str]:
    return [m.group(1).lower() for m in TAG_RE.finditer(text or "")]


def strip_tags(text: str) -> str:
    return TAG_RE.sub(" ", text or "").strip()


def overlap(item_text: str, entry_text: str) -> float:
    """Share of the plan item's content words that appear in the entry (0..1)."""
    item = set(tokens(item_text))
    if not item:
        return 0.0
    entry = set(tokens(entry_text))
    return len(item & entry) / len(item)


def match_entry(item: dict, entry: dict) -> tuple[bool, bool, float]:
    """(exact, fuzzy, ratio) for one plan item against one log entry."""
    slug = item.get("slug") or slugify(item.get("text", ""))
    if slug and slug in set(entry.get("tags") or []):
        return True, True, 1.0
    ratio = overlap(item.get("text", ""), entry.get("text", ""))
    return False, ratio >= 0.5, ratio


def classify(text: str) -> str | None:
    """Name of the distraction category this entry falls into, if any."""
    lowered = (text or "").lower()
    if not lowered:
        return None
    best: tuple[int, str] | None = None
    for category, words in DISTRACTION_LEXICON.items():
        for word in words:
            if re.search(rf"(?<![a-z]){re.escape(word)}(?![a-z])", lowered):
                score = len(word)
                if best is None or score > best[0]:
                    best = (score, category)
    return best[1] if best else None


def format_duration(minutes: float) -> str:
    minutes = int(round(float(minutes or 0)))
    if minutes < 60:
        return f"{minutes}m"
    hours, mins = divmod(minutes, 60)
    if mins == 0:
        return f"{hours}h"
    return f"{hours}h {mins:02d}m"


def human_duration(minutes: float) -> str:
    """'1h 30m' -> '1 hour 30 minutes', for report prose."""
    minutes = int(round(float(minutes or 0)))
    if minutes == 0:
        return "nothing logged"
    hours, mins = divmod(minutes, 60)
    parts = []
    if hours:
        parts.append(f"{hours} hour" + ("s" if hours != 1 else ""))
    if mins:
        parts.append(f"{mins} minute" + ("s" if mins != 1 else ""))
    return " ".join(parts)


def plural(count: int, singular: str, plural_form: str | None = None) -> str:
    return singular if count == 1 else (plural_form or singular + "s")


def join_list(items: list[str], max_items: int = 3) -> str:
    items = [i for i in items if i]
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    shown = items[:max_items]
    rest = len(items) - len(shown)
    text = ", ".join(shown[:-1]) + " and " + shown[-1] if len(shown) > 1 else shown[0]
    if rest > 0:
        text += f", plus {rest} more"
    return text
