"""Native MarbleRun requires device authorization before any dispatch."""
import asyncio
import unittest
from unittest.mock import patch

from fastapi import HTTPException
from gui.api import unified_api


class MarbleRunUnavailableTest(unittest.TestCase):
    def test_run_without_request_authentication_returns_401_before_database_access(self):
        with patch.object(unified_api, "_get_conn", side_effect=AssertionError("DB accessed")):
            with self.assertRaises(HTTPException) as result:
                asyncio.run(unified_api.execute_marblerun_chain(1, {"input": "fixture"}))
        self.assertEqual(result.exception.status_code, 401)


if __name__ == "__main__":
    unittest.main()
