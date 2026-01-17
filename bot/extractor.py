# bot/extractor.py
import logging
from telethon import TelegramClient
from telethon.sessions import StringSession

from bot.config import API_ID, API_HASH, EXTRACT_MESSAGES_LIMIT
from bot.utils import extract_telegram_links, normalize_tme_link

logger = logging.getLogger(__name__)


async def extract_links_from_channel(session_string: str, channel_link: str) -> list[str]:
    """
    Extract telegram links from channel messages.

    Modes:
    - if EXTRACT_MESSAGES_LIMIT == 0:
        Extract from first message to last message (reverse=True)
    - if EXTRACT_MESSAGES_LIMIT > 0:
        Extract last N messages only

    Output:
    - returns unique links normalized to:
      https://t.me/<path>

    Notes:
    - Uses Telethon StringSession.
    - Will ignore empty messages.
    """
    channel_link = normalize_tme_link(channel_link)

    client = TelegramClient(StringSession(session_string), API_ID, API_HASH)
    await client.connect()

    found = set()

    try:
        entity = await client.get_entity(channel_link)

        # ---------------- Fast mode: last N messages ----------------
        if EXTRACT_MESSAGES_LIMIT and EXTRACT_MESSAGES_LIMIT > 0:
            logger.info(
                f"[extractor] Extracting last {EXTRACT_MESSAGES_LIMIT} messages from {channel_link}"
            )

            async for msg in client.iter_messages(entity, limit=EXTRACT_MESSAGES_LIMIT):
                if not msg:
                    continue

                text = msg.message or ""
                if not text.strip():
                    continue

                for link in extract_telegram_links(text):
                    n = normalize_tme_link(link)
                    if n:
                        found.add(n)

        # ---------------- Full mode: all messages ----------------
        else:
            logger.info(f"[extractor] Extracting ALL messages from {channel_link}")

            # reverse=True: from first message to last message
            async for msg in client.iter_messages(entity, reverse=True):
                if not msg:
                    continue

                text = msg.message or ""
                if not text.strip():
                    continue

                for link in extract_telegram_links(text):
                    n = normalize_tme_link(link)
                    if n:
                        found.add(n)

        result = sorted(found)
        logger.info(f"[extractor] Done. Found {len(result)} unique links from {channel_link}")
        return result

    finally:
        await client.disconnect()
