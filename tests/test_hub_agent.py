import unittest
from unittest.mock import patch
import json
from hub_agent import register_and_heartbeat

class HubAgentTests(unittest.TestCase):
    def test_no_token_disables_optional_hub(self):
        with patch.dict("os.environ", {"INFRA_HUB_TOKEN": ""}, clear=False):
            self.assertFalse(register_and_heartbeat("predator-task-agent", "github-actions", ["research"]))

    @patch("hub_agent.urlopen")
    def test_register_and_heartbeat(self, mocked):
        class Response:
            status = 200
            def read(self): return b'{}'
            def __enter__(self): return self
            def __exit__(self, *a): return False
        mocked.side_effect = [Response(), Response()]
        with patch.dict("os.environ", {"INFRA_HUB_TOKEN": "test-token", "INFRA_HUB_URL": "https://hub.test"}, clear=False):
            self.assertTrue(register_and_heartbeat("predator-task-agent", "github-actions", ["research"]))
        first, second = mocked.call_args_list
        req1 = first.args[0]
        req2 = second.args[0]
        self.assertEqual(req1.headers["Authorization"], "Bearer test-token")
        self.assertEqual(json.loads(req1.data)["capabilities"], ["research"])
        self.assertEqual(req2.get_method(), "POST")
        self.assertIn("/heartbeat", req2.full_url)

if __name__ == "__main__":
    unittest.main()
