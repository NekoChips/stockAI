import unittest
from datetime import datetime, timezone
from decimal import Decimal

from stock_ai_agent.data.alphafeed import AlphaFeedAdapter, AlphaFeedError


class FakeFrame:
    def __init__(self, rows):
        self.rows = rows

    def to_dict(self, orient="records"):
        self.orient = orient
        return list(self.rows)


class FakeQuotes:
    def __init__(self, frame):
        self.frame = frame
        self.calls = []

    def get(self, **kwargs):
        self.calls.append(kwargs)
        return self.frame


class FakeKlines:
    def __init__(self, frames):
        self.frames = frames
        self.calls = []

    def get(self, symbol, **kwargs):
        self.calls.append((symbol, kwargs))
        return self.frames[symbol]

    def batch(self, symbols, **kwargs):
        self.calls.append((list(symbols), kwargs))
        return {symbol: self.frames[symbol] for symbol in symbols}


class FakeAlphaFeedClient:
    def __init__(self, quote_frame=None, kline_frames=None):
        self.quotes = FakeQuotes(quote_frame or FakeFrame([]))
        self.klines = FakeKlines(kline_frames or {})


class AlphaFeedAdapterTests(unittest.TestCase):
    def test_batch_quotes_are_normalized_to_project_quote(self):
        client = FakeAlphaFeedClient(
            quote_frame=FakeFrame(
                [
                    {
                        "symbol": "588170.SH",
                        "ext.name": "科创100ETF基金",
                        "last_price": 1.065,
                        "prev_close": 1.021,
                        "open": 1.018,
                        "high": 1.071,
                        "low": 1.015,
                        "volume": 45942103,
                        "amount": 4810354175,
                        "ext.change_pct": 0.0431,
                        "trade_time": "2026-08-21 10:00:00",
                    }
                ]
            )
        )
        adapter = AlphaFeedAdapter(
            client=client,
            freshness_seconds=90,
            min_request_interval_seconds=0,
            now_fn=lambda: datetime(2026, 8, 21, 2, 0, tzinfo=timezone.utc),
        )

        quote = adapter.get_quote("588170.SH")

        self.assertEqual(quote.source, "alphafeed")
        self.assertEqual(quote.name, "科创100ETF基金")
        self.assertEqual(quote.latest_price, Decimal("1.065"))
        self.assertEqual(quote.previous_close, Decimal("1.021"))
        self.assertEqual(quote.change_percent, Decimal("4.31"))
        self.assertEqual(client.quotes.calls[0]["symbols"], ["588170.SH"])
        self.assertTrue(quote.is_fresh)

    def test_kline_requests_are_single_symbol_and_use_alpha_feed_period(self):
        client = FakeAlphaFeedClient(
            kline_frames={
                "588170.SH": FakeFrame(
                    [
                        {
                            "symbol": "588170.SH",
                            "trade_date": "2026-08-20",
                            "open": 1.02,
                            "high": 1.06,
                            "low": 1.01,
                            "close": 1.05,
                            "volume": 12000,
                            "amount": 12480,
                        }
                    ]
                ),
                "588200.SH": FakeFrame(
                    [
                        {
                            "symbol": "588200.SH",
                            "trade_date": "2026-08-20",
                            "open": 1.02,
                            "high": 1.06,
                            "low": 1.01,
                            "close": 1.05,
                            "volume": 12000,
                            "amount": 12480,
                        }
                    ]
                ),
            }
        )
        adapter = AlphaFeedAdapter(
            client=client,
            history_count=2000,
            min_request_interval_seconds=0,
            kline_max_requests_per_minute=60,
            monotonic_fn=lambda: 10,
            sleep_fn=lambda _seconds: None,
        )

        bars = adapter.get_bars_batch(["588170.SH", "588200.SH"], start="20240101", end="20260821", adjust="qfq")

        self.assertEqual(bars["588170.SH"][0].close_price, Decimal("1.05"))
        self.assertEqual([symbol for symbol, _ in client.klines.calls], ["588170.SH", "588200.SH"])
        _, kwargs = client.klines.calls[0]
        self.assertEqual(kwargs["period"], "1d")
        self.assertEqual(kwargs["adjust"], "forward")
        self.assertEqual(kwargs["count"], 2000)
        self.assertTrue(kwargs["to_dataframe"])

    def test_external_daily_bars_accept_non_a_share_symbol_and_use_raw_prices(self):
        client = FakeAlphaFeedClient(
            kline_frames={
                "XLK.US": FakeFrame(
                    [
                        {"trade_date": "2026-08-20", "close": 100},
                        {"trade_date": "2026-08-21", "close": 103},
                    ]
                )
            }
        )
        adapter = AlphaFeedAdapter(
            client=client,
            api_key="external-daily-bars",
            kline_max_requests_per_minute=10,
            min_request_interval_seconds=0,
            monotonic_fn=lambda: 10,
            sleep_fn=lambda _seconds: None,
        )

        bars = adapter.get_external_daily_bars("XLK.US", "20260819", "20260821", count=5)

        self.assertEqual([bar.close_price for bar in bars], [Decimal("100"), Decimal("103")])
        symbol, kwargs = client.klines.calls[0]
        self.assertEqual(symbol, "XLK.US")
        self.assertEqual(kwargs["period"], "1d")
        self.assertEqual(kwargs["adjust"], "none")
        self.assertEqual(kwargs["count"], 5)

    def test_external_daily_kline_quota_allows_ten_but_clamps_above_plan_limit(self):
        adapter = AlphaFeedAdapter(
            client=FakeAlphaFeedClient(),
            kline_max_requests_per_minute=99,
        )

        self.assertEqual(adapter.kline_max_requests_per_minute, 10)

    def test_missing_api_key_is_explained_when_client_is_not_injected(self):
        adapter = AlphaFeedAdapter(api_key="", sdk_importer=lambda: (_ for _ in ()).throw(ImportError("missing")))

        with self.assertRaises(AlphaFeedError) as ctx:
            adapter.get_quote("588170.SH")

        self.assertIn("ALPHAFEED_API_KEY", str(ctx.exception))

    def test_safe_request_interval_is_applied_between_alpha_feed_calls(self):
        client = FakeAlphaFeedClient(quote_frame=FakeFrame([{"symbol": "588170.SH", "last_price": 1.0, "prev_close": 1.0, "open": 1.0, "high": 1.0, "low": 1.0}]))
        waits = []
        adapter = AlphaFeedAdapter(
            client=client,
            api_key="test-key-interval",
            min_request_interval_seconds=1,
            quote_max_requests_per_minute=60,
            quote_cache_seconds=0,
            monotonic_fn=lambda: 10,
            sleep_fn=waits.append,
        )

        adapter.get_quote("588170.SH")
        adapter.get_quote("588170.SH")

        self.assertEqual(waits, [7.5])

    def test_quote_cache_avoids_duplicate_sdk_calls(self):
        client = FakeAlphaFeedClient(quote_frame=FakeFrame([{"symbol": "588170.SH", "last_price": 1.0, "prev_close": 1.0, "open": 1.0, "high": 1.0, "low": 1.0}]))
        adapter = AlphaFeedAdapter(client=client, min_request_interval_seconds=0, quote_cache_seconds=3, monotonic_fn=lambda: 10)

        adapter.get_quote("588170.SH")
        adapter.get_quote("588170.SH")

        self.assertEqual(len(client.quotes.calls), 1)

    def test_safe_request_interval_is_shared_by_adapters_using_same_api_key(self):
        clients = [
            FakeAlphaFeedClient(quote_frame=FakeFrame([{"symbol": "588170.SH", "last_price": 1.0, "prev_close": 1.0, "open": 1.0, "high": 1.0, "low": 1.0}]))
            for _ in range(2)
        ]
        waits = []
        adapters = [
            AlphaFeedAdapter(
                client=client,
                api_key="test-key-shared-interval",
                min_request_interval_seconds=1,
                quote_max_requests_per_minute=60,
                quote_cache_seconds=0,
                monotonic_fn=lambda: 10,
                sleep_fn=waits.append,
            )
            for client in clients
        ]

        adapters[0].get_quote("588170.SH")
        adapters[1].get_quote("588170.SH")

        self.assertEqual(waits, [7.5])

    def test_quote_requests_are_split_into_five_symbol_batches(self):
        symbols = [f"60000{index}.SH" for index in range(1, 7)]
        client = FakeAlphaFeedClient(
            quote_frame=FakeFrame(
                [
                    {
                        "symbol": symbol,
                        "last_price": 1.0,
                        "prev_close": 1.0,
                        "open": 1.0,
                        "high": 1.0,
                        "low": 1.0,
                    }
                    for symbol in symbols
                ]
            )
        )
        adapter = AlphaFeedAdapter(
            client=client,
            quote_max_symbols_per_request=5,
            quote_max_requests_per_minute=60,
            min_request_interval_seconds=0,
            monotonic_fn=lambda: 10,
            sleep_fn=lambda _seconds: None,
        )

        quotes = adapter.get_quotes(symbols)

        self.assertEqual(set(quotes), set(symbols))
        self.assertEqual([call["symbols"] for call in client.quotes.calls], [symbols[:5], symbols[5:]])

    def test_default_rate_limit_reserves_headroom_below_ten_requests_per_minute(self):
        client = FakeAlphaFeedClient(
            quote_frame=FakeFrame(
                [
                    {
                        "symbol": "588170.SH",
                        "last_price": 1.0,
                        "prev_close": 1.0,
                        "open": 1.0,
                        "high": 1.0,
                        "low": 1.0,
                    }
                ]
            )
        )
        waits = []
        adapter = AlphaFeedAdapter(
            client=client,
            api_key="test-key-eight-per-minute",
            quote_cache_seconds=0,
            monotonic_fn=lambda: 10,
            sleep_fn=waits.append,
        )

        adapter.get_quote("588170.SH")
        adapter.get_quote("588170.SH")

        self.assertEqual(waits, [7.5])

    def test_unsafe_alpha_feed_quota_configuration_is_clamped_to_safe_limits(self):
        adapter = AlphaFeedAdapter(
            client=FakeAlphaFeedClient(),
            quote_max_symbols_per_request=99,
            quote_max_requests_per_minute=99,
            kline_max_symbols_per_request=99,
            kline_max_requests_per_minute=99,
        )

        self.assertEqual(adapter.quote_max_symbols_per_request, 5)
        self.assertEqual(adapter.quote_max_requests_per_minute, 8)
        self.assertEqual(adapter.kline_max_symbols_per_request, 1)
        self.assertEqual(adapter.kline_max_requests_per_minute, 10)

    def test_missing_required_quote_field_raises_for_fallback(self):
        client = FakeAlphaFeedClient(quote_frame=FakeFrame([{"symbol": "588170.SH", "last_price": 1.0, "prev_close": 1.0}]))
        adapter = AlphaFeedAdapter(client=client, min_request_interval_seconds=0)

        with self.assertRaises(AlphaFeedError):
            adapter.get_quote("588170.SH")


if __name__ == "__main__":
    unittest.main()
