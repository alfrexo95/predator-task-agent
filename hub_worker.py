"""One-shot, safe Infrastructure Hub task consumer.

Only handles catalog discovery and GET health checks for catalogued public/free routes.
It never calls paid routes, authenticated routes, arbitrary URLs, or mutating HTTP methods.
"""
from __future__ import annotations

import json
import os
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen, HTTPRedirectHandler, build_opener
from urllib.parse import urlparse

AGENT_ID = "predator-task-agent"


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def safe_urlopen(req, timeout=10):
    """HTTP client that rejects redirects to avoid redirect-based SSRF."""
    return build_opener(_NoRedirect()).open(req, timeout=timeout)
HUB_DEFAULT = "https://x402-api-wigc.onrender.com"


class HubClient:
    def __init__(self, token: str, base_url: str | None = None):
        self.token = token.strip()
        self.base_url = (base_url or os.getenv("INFRA_HUB_URL", HUB_DEFAULT)).rstrip("/")
        self.headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def request(self, path: str, body: dict | None = None, method: str = "GET"):
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = Request(self.base_url + path, data=data, headers=self.headers, method=method)
        with urlopen(req, timeout=15) as response:
            raw = response.read()
        return json.loads(raw) if raw else {}

    def mcp_tool(self, name: str, arguments: dict):
        request_body = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        }
        response = self.request("/mcp", request_body, "POST")
        result = response.get("result", {})
        if response.get("error") or result.get("isError"):
            raise RuntimeError("MCP tool call failed")
        return result.get("structuredContent", {})

    def list_services(self):
        return self.mcp_tool("list_services", {})

    def list_routes(self):
        return self.mcp_tool("list_routes", {})

    def get_service_routes(self, service_id: str):
        return self.mcp_tool("get_service_routes", {"service_id": service_id})

    def claim(self, agent_id: str):
        return self.request(f"/infra/agents/{agent_id}/claim", {}, "POST").get("task")

    def complete(self, agent_id: str, task_id: str, result: dict):
        return self.request(f"/infra/tasks/{task_id}/complete", {"agent_id": agent_id, "result": result}, "POST")


def execute_task(task: dict, client: HubClient) -> dict:
    capability = task.get("capability")
    payload = task.get("payload") or {}
    if not isinstance(payload, dict):
        return {"ok": False, "reason": "invalid_task_payload"}

    if capability == "hub.catalog.discover":
        service_id = str(payload.get("service_id", "")).strip()
        if service_id:
            data = client.get_service_routes(service_id)
            return {
                "ok": True,
                "service_id": service_id,
                "service": data.get("service"),
                "route_count": len(data.get("routes", [])),
                "routes": [
                    {k: r.get(k) for k in ("path", "method", "auth", "payment", "deployment_status", "price_usd")}
                    for r in data.get("routes", [])
                ],
            }
        services = client.list_services().get("services", [])
        routes = client.list_routes().get("routes", [])
        return {
            "ok": True,
            "service_count": len(services),
            "route_count": len(routes),
            "service_ids": [s.get("service_id") for s in services],
        }

    if capability == "route.health":
        service_id = str(payload.get("service_id", "")).strip()
        path = str(payload.get("path", "")).strip()
        if not service_id or not path:
            return {"ok": False, "reason": "service_id_and_path_required"}
        data = client.get_service_routes(service_id)
        service = data.get("service") or {}
        route = next((r for r in data.get("routes", []) if r.get("path") == path and r.get("method") == "GET"), None)
        if route is None:
            return {"ok": False, "reason": "route_not_catalogued"}
        if (
            service.get("deployment_status") != "live"
            or route.get("deployment_status") != "live"
            or route.get("auth") != "public"
            or route.get("payment") != "none"
            or not path.startswith("/")
            or "{" in path or "}" in path or "*" in path
            or ".." in path or "?" in path or "#" in path
        ):
            return {"ok": False, "reason": "route_not_public_free_get"}
        base = str(service.get("base_url", "")).rstrip("/")
        parsed = urlparse(base)
        host = (parsed.hostname or "").lower()
        if parsed.scheme != "https" or not (host.endswith(".onrender.com") or host.endswith(".workers.dev")):
            return {"ok": False, "reason": "service_host_not_allowed"}
        url = base + path
        try:
            req = Request(url, headers={"Accept": "application/json"}, method="GET")
            with safe_urlopen(req, timeout=10) as response:
                body = response.read(2048)
                status = getattr(response, "status", None)
                if status is None:
                    status = response.getcode()
                content_type = response.headers.get("Content-Type", "")
            json_type = None
            if "json" in content_type.lower() and body:
                try:
                    json_type = type(json.loads(body)).__name__
                except (ValueError, TypeError):
                    json_type = "invalid-json"
            return {"ok": status == 200, "service_id": service_id, "path": path,
                    "status_code": status, "content_type": content_type, "json_type": json_type}
        except HTTPError as error:
            return {"ok": False, "service_id": service_id, "path": path, "status_code": error.code}
        except (URLError, TimeoutError, OSError) as error:
            return {"ok": False, "service_id": service_id, "path": path, "reason": type(error).__name__}

    return {"ok": False, "reason": "unsupported_capability", "capability": capability}


def run_once() -> bool:
    token = os.getenv("INFRA_HUB_TOKEN", "").strip()
    if not token:
        print("Hub task worker skipped: token not configured.")
        return False
    client = HubClient(token)
    try:
        task = client.claim(AGENT_ID)
        if not task:
            print("Hub task worker: no pending safe task.")
            return True
        task_id = task.get("task_id")
        result = execute_task(task, client)
        client.complete(AGENT_ID, task_id, result)
        print(f"Hub task {task_id} completed; ok={result.get('ok')}")
        return True
    except (HTTPError, URLError, TimeoutError, OSError, RuntimeError, ValueError) as error:
        print(f"Hub task worker skipped/failure: {type(error).__name__}")
        return False


if __name__ == "__main__":
    run_once()
