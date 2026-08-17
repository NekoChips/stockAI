import io
import unittest
from contextlib import redirect_stderr
from unittest.mock import patch

from stock_ai_agent.app import main


class CliErrorTests(unittest.TestCase):
    def test_sync_history_error_is_user_friendly(self):
        stderr = io.StringIO()
        with patch("stock_ai_agent.app.sync_history", side_effect=RuntimeError("缺少 AKShare 依赖，请先安装：python3 -m pip install akshare")):
            with redirect_stderr(stderr):
                code = main(["sync-history"])

        self.assertEqual(code, 1)
        self.assertIn("同步历史 K 线失败", stderr.getvalue())
        self.assertIn("pip install akshare", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
