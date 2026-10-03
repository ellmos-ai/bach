"""An unavailable MarbleRun dispatcher must not record completed runs."""
import asyncio
import unittest
from unittest.mock import patch

from fastapi import HTTPException
from gui.api import unified_api


class MarbleRunUnavailableTest(unittest.TestCase):
    def test_run_returns_501_before_database_access(self):
        with patch.object(unified_api, "_get_conn", side_effect=AssertionError("DB accessed")):
            with self.assertRaises(HTTPException) as result:
                asyncio.run(unified_api.execute_marblerun_chain(1, {"input": "fixture"}))
        self.assertEqual(result.exception.status_code, 501)


if __name__ == "__main__":
    unittest.main()
