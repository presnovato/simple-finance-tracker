"""Генерирует подписанный initData для локального запуска TMA.

Пример:
  python tools/generate_tma_dev_init_data.py --base-url http://localhost:5173
"""

import argparse
import hashlib
import hmac
import json
import os
import time
from urllib.parse import quote, urlencode

from dotenv import load_dotenv


def generate(bot_token: str, user_id: int, auth_date: int | None = None) -> str:
    values = {
        "auth_date": str(int(time.time()) if auth_date is None else auth_date),
        "query_id": "finance-tracker-dev",
        "user": json.dumps(
            {"id": user_id, "first_name": "Sunset", "username": "dev"},
            ensure_ascii=False,
            separators=(",", ":"),
        ),
    }
    check_string = "\n".join(f"{key}={values[key]}" for key in sorted(values))
    secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    values["hash"] = hmac.new(secret, check_string.encode(), hashlib.sha256).hexdigest()
    return urlencode(values)


def main() -> None:
    load_dotenv()
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://localhost:5173")
    parser.add_argument("--user-id", type=int, default=int(os.getenv("ALLOWED_USER_ID", "0")))
    args = parser.parse_args()
    bot_token = os.getenv("BOT_TOKEN", "")
    if not bot_token or not args.user_id:
        raise SystemExit("Заполни BOT_TOKEN и ALLOWED_USER_ID в .env")
    init_data = generate(bot_token, args.user_id)
    separator = "&" if "?" in args.base_url else "?"
    print(f"{args.base_url}{separator}initData={quote(init_data, safe='')}")


if __name__ == "__main__":
    main()
