from __future__ import annotations

import urllib.parse
import urllib.request


def send_message(
    token: str,
    chat_id: str,
    text: str,
    *,
    parse_mode: str | None = None,
) -> bool:
    if not token or not chat_id or not text:
        return False
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "disable_web_page_preview": "true",
    }
    if parse_mode:
        payload["parse_mode"] = parse_mode
    body = urllib.parse.urlencode(payload).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=15):
            return True
    except Exception:
        return False
