import unittest
from unittest.mock import patch

from hub_worker import execute_task, run_once


class FakeHubClient:
    def __init__(self, token="test"):
        self.token = token
        self.claimed = None
        self.completed = None
        self.service_data = {
            "service": {"service_id": "scan-malware-security", "base_url": "https://scan-malware-security.onrender.com", "deployment_status": "live"},
            "routes": [
                {"path": "/health", "method": "GET", "auth": "public", "payment": "none", "deployment_status": "live"},
                {"path": "/v1/scan", "method": "POST", "auth": "api-key", "payment": "x402", "deployment_status": "live"},
            ],
        }

    def list_services(self):
        return {"services": [self.service_data["service"]]}

    def list_routes(self):
        return {"routes": self.service_data["routes"]}

    def get_service_routes(self, service_id):
        if service_id != "scan-malware-security":
            raise ValueError("unknown service")
        return self.service_data

    def claim(self, agent_id):
        return self.claimed

    def complete(self, agent_id, task_id, result):
        self.completed = (agent_id, task_id, result)


class HubWorkerTests(unittest.TestCase):
    def test_catalog_discovery_returns_service_and_route_counts(self):
        client = FakeHubClient()
        result = execute_task({"capability": "hub.catalog.discover", "payload": {"service_id": "scan-malware-security"}}, client)
        self.assertTrue(result["ok"])
        self.assertEqual(result["service_id"], "scan-malware-security")
        self.assertEqual(result["route_count"], 2)

    def test_health_task_calls_only_catalogued_public_free_get_route(self):
        client = FakeHubClient()
        class Response:
            status = 200
            headers = {"Content-Type": "application/json"}
            def read(self, n=-1): return b'{"status":"ok"}'
            def __enter__(self): return self
            def __exit__(self, *args): return False
        with patch("hub_worker.urlopen", return_value=Response()) as mocked:
            result = execute_task({"capability": "route.health", "payload": {"service_id": "scan-malware-security", "path": "/health"}}, client)
        self.assertTrue(result["ok"])
        self.assertEqual(result["status_code"], 200)
        self.assertEqual(mocked.call_args.args[0].full_url, "https://scan-malware-security.onrender.com/health")

    def test_paid_or_authenticated_route_is_rejected_without_call(self):
        client = FakeHubClient()
        with patch("hub_worker.urlopen") as mocked:
            result = execute_task({"capability": "route.health", "payload": {"service_id": "scan-malware-security", "path": "/v1/scan"}}, client)
        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], "route_not_public_free_get")
        mocked.assert_not_called()

    def test_non_trusted_catalog_host_is_rejected_without_call(self):
        client = FakeHubClient()
        client.service_data["service"]["base_url"] = "https://evil.example"
        with patch("hub_worker.urlopen") as mocked:
            result = execute_task({"capability": "route.health", "payload": {"service_id": "scan-malware-security", "path": "/health"}}, client)
        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], "service_host_not_allowed")
        mocked.assert_not_called()

    def test_unknown_route_is_rejected_without_call(self):
        client = FakeHubClient()
        with patch("hub_worker.urlopen") as mocked:
            result = execute_task({"capability": "route.health", "payload": {"service_id": "scan-malware-security", "path": "/internal"}}, client)
        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], "route_not_catalogued")
        mocked.assert_not_called()

    def test_run_once_skips_without_token(self):
        with patch.dict("os.environ", {"INFRA_HUB_TOKEN": ""}, clear=False):
            self.assertFalse(run_once())

    def test_run_once_claims_and_completes_safe_task(self):
        client = FakeHubClient()
        client.claimed = {"task_id": "task-1", "capability": "hub.catalog.discover", "payload": {"service_id": "scan-malware-security"}}
        with patch("hub_worker.HubClient", return_value=client), patch.dict("os.environ", {"INFRA_HUB_TOKEN": "test-token"}, clear=False):
            self.assertTrue(run_once())
        self.assertIsNotNone(client.completed)
        self.assertEqual(client.completed[0], "predator-task-agent")
        self.assertEqual(client.completed[1], "task-1")
        self.assertTrue(client.completed[2]["ok"])


if __name__ == "__main__":
    unittest.main()
