import tempfile
import unittest
from http.client import HTTPConnection
from pathlib import Path
from threading import Thread

from stock_ai_agent.config import load_config
from stock_ai_agent.storage.mock import MockMarketDataStore as SQLiteMarketDataStore
from stock_ai_agent import web_assets
from stock_ai_agent.web_http import create_dashboard_server


class SpaAssetTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.spa_dir = Path(self._tmpdir.name)
        (self.spa_dir / "index.html").write_text(
            "<!doctype html><title>StockAI SPA</title><div id='root'></div>",
            encoding="utf-8",
        )
        assets = self.spa_dir / "assets"
        assets.mkdir()
        (assets / "app.js").write_text("console.log('ok')", encoding="utf-8")
        self._old = web_assets.spa_root
        web_assets.spa_root = lambda: self.spa_dir  # type: ignore[method-assign]

    def tearDown(self):
        web_assets.spa_root = self._old  # type: ignore[method-assign]
        self._tmpdir.cleanup()

    def test_render_spa_index_reads_file(self):
        html = web_assets.render_spa_index()
        self.assertIn("StockAI SPA", html)
        self.assertIn("id='root'", html)

    def test_resolve_spa_file_allows_assets(self):
        path = web_assets.resolve_spa_file("/app/assets/app.js")
        self.assertIsNotNone(path)
        assert path is not None
        self.assertEqual(path.read_text(encoding="utf-8"), "console.log('ok')")

    def test_resolve_spa_file_blocks_traversal(self):
        self.assertIsNone(web_assets.resolve_spa_file("/app/../web_http.py"))
        self.assertIsNone(web_assets.resolve_spa_file("/app/assets/../../web_http.py"))

    def test_http_app_index_asset_fallback_and_legacy_root(self):
        config = load_config()
        store = SQLiteMarketDataStore()
        server = create_dashboard_server(config, store, host="127.0.0.1", port=0)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            host, port = server.server_address
            conn = HTTPConnection(host, port, timeout=5)

            conn.request("GET", "/app")
            res = conn.getresponse()
            body = res.read().decode("utf-8")
            self.assertEqual(res.status, 200)
            self.assertIn("StockAI SPA", body)

            conn.request("GET", "/app/unknown-client-route")
            res = conn.getresponse()
            body = res.read().decode("utf-8")
            self.assertEqual(res.status, 200)
            self.assertIn("id='root'", body)

            conn.request("GET", "/app/assets/app.js")
            res = conn.getresponse()
            body = res.read().decode("utf-8")
            self.assertEqual(res.status, 200)
            self.assertEqual(body, "console.log('ok')")

            conn.request("GET", "/")
            res = conn.getresponse()
            body = res.read().decode("utf-8")
            self.assertEqual(res.status, 302)
            self.assertEqual(res.getheader("Location"), "/app/")
            self.assertEqual(body, "")
        finally:
            server.shutdown()
            server.server_close()

    def test_root_returns_503_when_spa_is_missing(self):
        config = load_config()
        store = SQLiteMarketDataStore()
        missing = self.spa_dir / "missing-spa"
        old_root = web_assets.spa_root
        web_assets.spa_root = lambda: missing  # type: ignore[method-assign]
        server = create_dashboard_server(config, store, host="127.0.0.1", port=0)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            host, port = server.server_address
            conn = HTTPConnection(host, port, timeout=5)
            conn.request("GET", "/")
            res = conn.getresponse()
            body = res.read().decode("utf-8")
            self.assertEqual(res.status, 503)
            self.assertIn("SPA 尚未构建", body)
        finally:
            server.shutdown()
            server.server_close()
            web_assets.spa_root = old_root  # type: ignore[method-assign]
