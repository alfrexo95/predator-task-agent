"""Optional heartbeat integration with Predator Infrastructure Hub."""
import json
import os
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

def register_and_heartbeat(agent_id, platform, capabilities):
    token = os.getenv("INFRA_HUB_TOKEN", "").strip()
    if not token:
        return False
    base = os.getenv("INFRA_HUB_URL", "https://x402-api-wigc.onrender.com").rstrip("/")
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json", "Accept": "application/json"}
    data = json.dumps({"agent_id": agent_id, "platform": platform, "capabilities": capabilities}).encode()
    req = Request(base + "/infra/agents/register", data=data, headers=headers, method="POST")
    try:
        with urlopen(req, timeout=8) as response:
            response.read()
        heartbeat = Request(base + f"/infra/agents/{agent_id}/heartbeat", data=b"{}", headers=headers, method="POST")
        with urlopen(heartbeat, timeout=8) as response:
            response.read()
        print("Hub registration/heartbeat completed.")
        return True
    except (HTTPError, URLError, TimeoutError):
        print("Hub registration skipped: service unavailable or request rejected.")
        return False

if __name__ == "__main__":
    register_and_heartbeat("predator-task-agent", "github-actions", ["reasoning", "code", "research", "hub.catalog.discover", "route.health"])
