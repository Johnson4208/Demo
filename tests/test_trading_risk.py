import unittest
import numpy as np
import pandas as pd

from engine.trading_risk import (
    _atr,
    _first_touch_stats,
    _forward_mae_percent,
    _peak_to_trough_drawdowns,
    _position_size_for_method,
    _shrunk_win_probability,
)


class TradingRiskUnitTests(unittest.TestCase):
    def setUp(self):
        n=80
        close=np.linspace(100,120,n)
        high=close+2
        low=close-2
        self.frame=pd.DataFrame({"High":high,"Low":low,"Close":close})

    def test_atr14_is_positive(self):
        a=_atr(self.frame,14).iloc[-1]
        self.assertTrue(float(a)>0)

    def test_peak_to_trough_tracks_drawdown_episode(self):
        close=pd.Series([100,110,120,100,90,95,125],dtype=float)
        dd=_peak_to_trough_drawdowns(close)
        self.assertTrue(any(abs(x-0.25)<1e-9 for x in dd))

    def test_forward_mae_is_nonnegative(self):
        mae=_forward_mae_percent(self.frame,20,'long')
        self.assertTrue(len(mae)>0)
        self.assertTrue(np.all(mae>=0))

    def test_first_touch_probabilities_resolve(self):
        close=np.array([100]*30+[105]*30,dtype=float)
        high=close+1
        low=close-1
        f=pd.DataFrame({"High":high,"Low":low,"Close":close})
        stats=_first_touch_stats(f,0.02,0.04,horizon=20,side='long')
        self.assertIsNotNone(stats['win_probability'])
        self.assertAlmostEqual(stats['win_probability']+stats['loss_probability'],1.0,places=6)

    def test_three_single_company_sizing_modes_produce_distinct_exposure(self):
        common = dict(
            account_equity=100_000,
            entry_price=100,
            stop_price=90,
            requested_risk_pct=1.0,
            target_r_multiple=2.0,
            win_probability=0.55,
        )
        results = {
            method: _position_size_for_method(method, **common)
            for method in ('fixed-fractional', 'kelly', 'half-kelly')
        }
        allocations = {method: round(result['allocation_pct'], 6) for method, result in results.items()}
        self.assertEqual(allocations['fixed-fractional'], 10.0)
        self.assertEqual(allocations['kelly'], 25.0)
        self.assertEqual(allocations['half-kelly'], 12.5)
        self.assertEqual(len(set(allocations.values())), 3)

    def test_modes_remain_comparable_without_account_equity(self):
        common = dict(
            account_equity=None,
            entry_price=100,
            stop_price=90,
            requested_risk_pct=1.0,
            target_r_multiple=2.0,
            win_probability=0.55,
        )
        results = {
            method: _position_size_for_method(method, **common)
            for method in ('fixed-fractional', 'kelly', 'half-kelly')
        }
        allocations = [round(results[method]['allocation_pct'], 6) for method in results]
        self.assertEqual(allocations, [10.0, 25.0, 12.5])
        self.assertEqual(len(set(allocations)), 3)
        for result in results.values():
            self.assertEqual(result['status'], 'normalized_only')
            self.assertTrue(result['normalized_only'])
            self.assertIsNone(result['position_units'])
            self.assertIsNone(result['position_value'])
            self.assertIsNotNone(result['planned_loss_pct_equity'])

    def test_kelly_withholds_position_when_adjusted_edge_is_not_positive(self):
        result = _position_size_for_method(
            'kelly', account_equity=100_000, entry_price=100, stop_price=90,
            requested_risk_pct=1.0, target_r_multiple=2.0,
            win_probability=0.30,
        )
        self.assertEqual(result['status'], 'no_positive_edge')
        self.assertEqual(result['position_units'], 0.0)

    def test_sizing_never_introduces_automatic_leverage(self):
        result = _position_size_for_method(
            'fixed-fractional', account_equity=100_000, entry_price=100, stop_price=99,
            requested_risk_pct=1.0, target_r_multiple=2.0,
            win_probability=0.60,
        )
        self.assertEqual(result['position_value'], 100_000)
        self.assertLessEqual(result['position_value'], 100_000)

    def test_portfolio_overlays_do_not_silently_become_single_company_modes(self):
        result = _position_size_for_method(
            'volatility-targeting', account_equity=100_000, entry_price=100, stop_price=90,
            requested_risk_pct=1.0, target_r_multiple=2.0,
            win_probability=0.60,
        )
        self.assertEqual(result['key'], 'fixed-fractional')
        self.assertEqual(result['allocation_pct'], 10.0)

    def test_probability_blends_and_shrinks_resolved_paths(self):
        result = _shrunk_win_probability(
            {'win_probability': 0.80, 'sample_size': 100, 'resolved_rate': 0.50},
            {'win_probability': 0.40, 'sample_size': 50, 'resolved_rate': 0.50},
        )
        self.assertEqual(result['resolved_paths'], 75)
        self.assertGreater(result['probability'], 0.50)
        self.assertLess(result['probability'], 0.80)

if __name__=='__main__':
    unittest.main()

class TradingRiskRouteTests(unittest.TestCase):
    @unittest.skipUnless(__import__("importlib").util.find_spec("flask") is not None, "Flask not installed in test environment")
    def test_api_route_accepts_trade_parameters(self):
        import app as app_module
        original = app_module.analyze_trading_risk
        original_session_validation = app_module.auth.validate_session
        seen = {}
        def fake(company, **kwargs):
            seen["company"] = company
            seen.update(kwargs)
            return {"status": "ok", "ticker": "FPT.VN"}
        app_module.analyze_trading_risk = fake
        app_module.auth.validate_session = lambda _user_id, _token: ({
            "id": 1, "email": "test@example.com", "display_name": "Test User",
            "role": "admin", "is_active": True, "must_reset_password": False,
            "created_at": "2026-01-01T00:00:00+00:00", "last_login_at": None,
            "login_count": 0, "failed_login_count": 0, "locked_until": None,
        }, {"id": 7})
        try:
            client = app_module.app.test_client()
            with client.session_transaction() as session:
                session["user_id"] = 1
                session["auth_token"] = "test-session"
            r = client.get('/api/risk/trading/FPT?entry=120&equity=100000000&risk_pct=1.5&target_r=2.5&horizon=30&side=long&sizing_method=half-kelly')
            self.assertEqual(r.status_code, 200)
            self.assertEqual(r.get_json()["ticker"], "FPT.VN")
            self.assertEqual(seen["company"], "FPT")
            self.assertEqual(seen["entry_price"], 120.0)
            self.assertEqual(seen["account_equity"], 100000000.0)
            self.assertEqual(seen["risk_pct"], 1.5)
            self.assertEqual(seen["target_r_multiple"], 2.5)
            self.assertEqual(seen["horizon"], 30)
            self.assertEqual(seen["side"], "long")
            self.assertEqual(seen["sizing_method"], "half-kelly")
        finally:
            app_module.analyze_trading_risk = original
            app_module.auth.validate_session = original_session_validation
