
# bot/utils.py
import re
from urllib.parse import urlparse

# Telegram link extractor:
# Supports:
# - username links:   https://t.me/SomeChannel   OR  t.me/SomeChannel
# - invite links:     https://t.me/+HASH         OR  t.me/+HASH
# - old invite links: https://t.me/joinchat/HASH OR  t.me/joinchat/HASH
# - folder invite:    https://t.me/addlist/SLUG  OR  t.me/addlist/SLUG
#
# Notes:
# - Some messages include links with trailing punctuation or brackets.
# - We keep it permissive but safe.
TG_LINK_RE = re.compile(
    r"((?:https?://)?(?:t\.me|telegram\.me)/(?:addlist/|joinchat/|\+)?[A-Za-z0-9_\-+]+)",
    re.IGNORECASE
)


def extract_telegram_links(text: str) -> list[str]:
    """
    Extract all Telegram links from any text.
    Returns raw link-like strings (may include missing scheme).
    """
    if not text:
        return []

    links = TG_LINK_RE.findall(text)

    cleaned: list[str] = []
    for l in links:
        l = (l or "").strip()

        # remove trailing punctuation / brackets (common in formatted messages)
        l = l.rstrip(").,;:!؟…]}>\"'`")

        # remove leading brackets too (rare)
        l = l.lstrip("(<[{\"'`")

        if l:
            cleaned.append(l)

    return cleaned


def normalize_tme_link(link: str) -> str:
    """
    Normalize Telegram links:
    - force https scheme
    - remove query parameters + fragments
    - normalize to: https://t.me/<path>
    - removes extra slashes in path
    """
    link = (link or "").strip()
    if not link:
        return ""

    # Add scheme if missing
    if link.startswith("t.me/") or link.startswith("telegram.me/"):
        link = "https://" + link

    try:
        u = urlparse(link)

        # Ensure telegram domains only
        if u.netloc.lower() in ("t.me", "telegram.me"):
            path = (u.path or "").strip("/")

            # collapse multiple slashes
            while "//" in path:
                path = path.replace("//", "/")

            # ignore query / fragment
            return f"https://t.me/{path}"

    except Exception:
        pass

    # If parsing failed, return original trimmed
    return link


def parse_link_type(link: str) -> tuple[str, str]:
    """
    Detect link type.

    Returns:
      ("folder", slug)    for https://t.me/addlist/<slug>
      ("invite", hash)    for https://t.me/+HASH or https://t.me/joinchat/HASH
      ("username", name)  for https://t.me/<username>
    """
    link = normalize_tme_link(link)

    if not link:
        return ("unknown", "")

    # folder: https://t.me/addlist/<slug>
    if "/addlist/" in link:
        slug = link.split("/addlist/", 1)[-1].strip("/")
        return ("folder", slug)

    # invite: https://t.me/+HASH
    if "t.me/+" in link:
        invite_hash = link.split("t.me/+", 1)[-1].strip("/")
        return ("invite", invite_hash)

    # old invite: https://t.me/joinchat/HASH
    if "/joinchat/" in link:
        invite_hash = link.split("/joinchat/", 1)[-1].strip("/")
        return ("invite", invite_hash)

    # username: https://t.me/<username or channel>
    username = link.split("t.me/", 1)[-1].strip("/")
    return ("username", username)
