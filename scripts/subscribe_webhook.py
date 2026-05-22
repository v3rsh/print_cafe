"""Subscribe to Wazzup24 webhooks.

Usage::

    python -m scripts.subscribe_webhook
"""

from __future__ import annotations

import asyncio
import sys

from app.config import get_settings
from app.wazzup.client import WazzupClient, WazzupClientError


async def main() -> int:
    settings = get_settings()
    api_key = settings.wazzup_api_key.get_secret_value()
    webhook_url = settings.wazzup_public_webhook_url

    if not api_key:
        print("WAZZUP_API_KEY is empty", file=sys.stderr)
        return 1
    if not webhook_url:
        print("WAZZUP_PUBLIC_WEBHOOK_URL is empty", file=sys.stderr)
        return 1

    async with WazzupClient(api_key=api_key, base_url=settings.wazzup_api_base_url) as client:
        try:
            result = await client.set_webhook(
                webhook_url,
                messages_and_statuses=True,
                contacts_and_deals_creation=False,
            )
        except WazzupClientError as exc:
            print(f"Failed to subscribe: {exc}", file=sys.stderr)
            return 2

    print("Subscribed:", result)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
