import unittest

from stock_ai_agent.config import load_config
from stock_ai_agent.universe import Universe, UniverseError, normalize_symbol, validate_hs_symbol


class UniverseTests(unittest.TestCase):
    def test_accepts_sh_sz_stock_and_etf_symbols(self):
        self.assertEqual(validate_hs_symbol("588170.SH", "etf"), "588170.SH")
        self.assertEqual(validate_hs_symbol("588200.SH", "etf"), "588200.SH")
        self.assertEqual(validate_hs_symbol("600519.SH", "stock"), "600519.SH")
        self.assertEqual(validate_hs_symbol("000001.SZ", "stock"), "000001.SZ")
        self.assertEqual(normalize_symbol("588170"), "588170.SH")

    def test_rejects_out_of_scope_symbols(self):
        for symbol in ["00700.HK", "AAPL.US", "588170", "900901.SH", "200002.SZ"]:
            if symbol == "588170":
                continue
            with self.assertRaises(UniverseError):
                validate_hs_symbol(symbol)

    def test_fixed_universe_rejects_unconfigured_symbols(self):
        universe = Universe.from_config(load_config().universe)

        self.assertTrue(universe.contains("588170.SH"))
        self.assertTrue(universe.contains("588200"))
        with self.assertRaises(UniverseError):
            universe.require("600519.SH")


if __name__ == "__main__":
    unittest.main()
