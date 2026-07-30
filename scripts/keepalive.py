"""Ping autenticado para el Railway Cron diario."""

import os
import urllib.request


base_url = os.environ["APP_URL"].rstrip("/")
token = os.environ["KEEPALIVE_TOKEN"]
request = urllib.request.Request(
    f"{base_url}/api/keepalive",
    method="POST",
    headers={"Authorization": f"Bearer {token}"},
)
with urllib.request.urlopen(request, timeout=60) as response:
    if response.status != 200:
        raise SystemExit(f"Keepalive respondió HTTP {response.status}")
    print(response.read().decode("utf-8"))
