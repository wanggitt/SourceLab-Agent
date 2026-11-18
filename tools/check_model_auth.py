"""Read-only auth check: GET /models; never print, store, or send an LLM prompt."""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app


def main():
    endpoint = app.os.environ.get("LLM_CHAT_ENDPOINT", "").strip()
    key = app.os.environ.get("LLM_API_KEY", "").strip()
    model = app.os.environ.get("LLM_MODEL", "").strip()
    parsed = urllib.parse.urlparse(endpoint)
    if parsed.scheme != "https" or parsed.netloc != "api.deepseek.com":
        print("CONFIG_ERROR: only the official DeepSeek HTTPS endpoint is checked")
        return
    if parsed.path.rstrip("/") not in ("/chat/completions", "/v1/chat/completions"):
        print("CONFIG_ERROR: LLM_CHAT_ENDPOINT must be the full "
              "DeepSeek /chat/completions URL, not the base URL")
        return
    if not key or not model:
        print("CONFIG_ERROR: missing model or API key")
        return
    req = urllib.request.Request(
        "https://api.deepseek.com/models",
        headers={"Authorization": "Bearer " + key,
                 "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=8) as response:
            payload = json.load(response)
            models = {item.get("id") for item in payload.get("data", [])
                      if isinstance(item, dict)}
            print("AUTH_OK; configured_model_available=" + str(model in models))
    except urllib.error.HTTPError as exc:
        print("AUTH_HTTP_" + str(exc.code))
    except (urllib.error.URLError, TimeoutError, OSError):
        print("NETWORK_UNAVAILABLE")


if __name__ == "__main__":
    main()
