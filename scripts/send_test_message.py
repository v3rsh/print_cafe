"""Send a test message via Wazzup24."""

from __future__ import annotations

import argparse
import asyncio
import sys

from app.config import get_settings
from app.wazzup.client import WazzupClient, WazzupClientError


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Send a test Wazzup message")
    parser.add_argument("--channel", required=True)
    parser.add_argument("--chat-id", required=True)
    parser.add_argument(
        "--chat-type",
        required=True,
        help="whatsapp | telegram | instagram | viber | tgapi | avito | vk",
    )
    parser.add_argument("--text", required=True)
    return parser.parse_args()


async def main() -> int:
    args = _parse_args()
    settings = get_settings()
    api_key = settings.wazzup_api_key.get_secret_value()
    if not api_key:
        print("WAZZUP_API_KEY is empty", file=sys.stderr)
        return 1

    async with WazzupClient(api_key=api_key, base_url=settings.wazzup_api_base_url) as client:
        try:
            result = await client.send_message(
                channel_id=args.channel,
                chat_id=args.chat_id,
                chat_type=args.chat_type,
                text=args.text,
            )
        except WazzupClientError as exc:
            print(f"Failed to send: {exc}", file=sys.stderr)
            return 2

    print("Sent:", result)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
