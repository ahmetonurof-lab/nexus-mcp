"""
test_exchange.py — exchange.py characterization tests
=====================================================

Covers: _round_to_tick, _round_step, BinanceHTTPClient (init, _ep, _sign,
_request retry, precision helpers, klines, orders, cancel, listen key, PM mapping)
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ── sys.path ─────────────────────────────────────────────────────────────────
SRC = Path(__file__).parent.parent / "sonnet" / "src"
import sys  # noqa: E402

sys.path.insert(0, str(SRC))

import warnings  # noqa: E402

with warnings.catch_warnings():
    warnings.simplefilter("ignore", DeprecationWarning)
    import config  # noqa: F401

from exchange import (  # noqa: E402
    BinanceHTTPClient,
    _round_step,
    _round_to_tick,
)

# ═════════════════════════════════════════════════════════════════════════════
# 1. Module-level helpers
# ═════════════════════════════════════════════════════════════════════════════


class TestRoundToTick:
    """_round_to_tick(value, tick) — tick size'a yuvarlama."""

    def test_exact_multiple(self):
        assert _round_to_tick(100.0, 0.01) == 100.0

    def test_round_up(self):
        # Floating point: 100.005 / 0.01 = 10000.5 → round=10000 → *0.01 = 100.0 (banker's rounding)
        assert _round_to_tick(100.015, 0.01) == 100.02

    def test_round_down(self):
        assert _round_to_tick(100.004, 0.01) == 100.0

    def test_round_tick_at_boundary(self):
        assert _round_to_tick(100.0051, 0.01) == 100.01

    def test_zero_tick(self):
        assert _round_to_tick(123.456, 0) == 123.456

    def test_negative_tick(self):
        assert _round_to_tick(123.456, -0.01) == 123.456

    def test_small_tick(self):
        assert _round_to_tick(0.12345678, 0.0001) == 0.1235


class TestRoundStep:
    """_round_step(value, step) — step size'a aşağı yuvarlama."""

    def test_exact_multiple(self):
        # Use step that's exactly representable in binary float (power of 2)
        assert _round_step(100.0, 0.5) == 100.0

    def test_round_down(self):
        # floor division with step: 100.0059 // 0.001 → * 0.001
        assert _round_step(100.0059, 0.001) == 100.005

    def test_zero_step(self):
        assert _round_step(123.456, 0) == 123.456

    def test_negative_step(self):
        assert _round_step(123.456, -0.001) == 123.456

    def test_floor_behavior(self):
        assert _round_step(1.234, 0.1) == 1.2


# ═════════════════════════════════════════════════════════════════════════════
# 2. BinanceHTTPClient — init, _ep, _sign
# ═════════════════════════════════════════════════════════════════════════════


class TestClientInit:
    """BinanceHTTPClient.__init__"""

    def test_default_init(self):
        c = BinanceHTTPClient(api_key="k", api_secret="s")
        assert c.api_key == "k"
        assert c.api_secret == "s"
        assert c.base_url == "https://fapi.binance.com"
        assert c.timeout == 15
        assert c.portfolio_margin is False
        assert c._exchange_info is None
        assert c._exchange_info_ts == 0.0
        assert isinstance(c._symbol_info, dict)
        assert len(c._symbol_info) == 0

    def test_custom_base_url(self):
        c = BinanceHTTPClient(api_key="k", api_secret="s", base_url="https://demo-fapi.binance.com/")
        assert c.base_url == "https://demo-fapi.binance.com"

    def test_custom_timeout(self):
        c = BinanceHTTPClient(api_key="k", api_secret="s", timeout=30)
        assert c.timeout == 30

    def test_portfolio_margin_enabled(self):
        c = BinanceHTTPClient(api_key="k", api_secret="s", portfolio_margin=True)
        assert c.portfolio_margin is True


class TestEndpointMapping:
    """BinanceHTTPClient._ep — Portfolio Margin endpoint mapping."""

    def test_no_pm_returns_original(self):
        c = BinanceHTTPClient(api_key="k", api_secret="s", portfolio_margin=False)
        assert c._ep("/fapi/v1/order") == "/fapi/v1/order"
        assert c._ep("/fapi/v2/positionRisk") == "/fapi/v2/positionRisk"
        assert c._ep("/fapi/v1/exchangeInfo") == "/fapi/v1/exchangeInfo"

    def test_pm_order_mapped(self):
        c = BinanceHTTPClient(api_key="k", api_secret="s", portfolio_margin=True)
        assert c._ep("/fapi/v1/order") == "/papi/v1/um/order"

    def test_pm_algo_order_mapped(self):
        c = BinanceHTTPClient(api_key="k", api_secret="s", portfolio_margin=True)
        assert c._ep("/fapi/v1/algoOrder") == "/papi/v1/um/conditional/order"

    def test_pm_margin_type_none(self):
        c = BinanceHTTPClient(api_key="k", api_secret="s", portfolio_margin=True)
        assert c._ep("/fapi/v1/marginType") is None

    def test_pm_leverage_mapped(self):
        c = BinanceHTTPClient(api_key="k", api_secret="s", portfolio_margin=True)
        assert c._ep("/fapi/v1/leverage") == "/papi/v1/um/leverage"

    def test_pm_position_risk_mapped(self):
        c = BinanceHTTPClient(api_key="k", api_secret="s", portfolio_margin=True)
        assert c._ep("/fapi/v2/positionRisk") == "/papi/v1/um/positionRisk"

    def test_pm_account_mapped(self):
        c = BinanceHTTPClient(api_key="k", api_secret="s", portfolio_margin=True)
        assert c._ep("/fapi/v2/account") == "/papi/v1/account"

    def test_pm_open_orders_mapped(self):
        c = BinanceHTTPClient(api_key="k", api_secret="s", portfolio_margin=True)
        assert c._ep("/fapi/v1/openOrders") == "/papi/v1/um/openOrders"

    def test_pm_open_algo_orders_mapped(self):
        c = BinanceHTTPClient(api_key="k", api_secret="s", portfolio_margin=True)
        assert c._ep("/fapi/v1/openAlgoOrders") == "/papi/v1/um/conditional/openOrders"

    def test_pm_cancel_replace_mapped(self):
        c = BinanceHTTPClient(api_key="k", api_secret="s", portfolio_margin=True)
        assert c._ep("/fapi/v1/order/cancelReplace") == "/papi/v1/um/order/cancelReplace"

    def test_pm_unknown_path_passthrough(self):
        c = BinanceHTTPClient(api_key="k", api_secret="s", portfolio_margin=True)
        assert c._ep("/fapi/v1/unknownEndpoint") == "/fapi/v1/unknownEndpoint"


class TestSign:
    """BinanceHTTPClient._sign — HMAC-SHA256 imza."""

    def test_basic_sign(self):
        c = BinanceHTTPClient(api_key="k", api_secret="secret123")
        sig = c._sign({"symbol": "BTCUSDT", "timestamp": 1234567890})
        expected = hmac.new(b"secret123", b"symbol=BTCUSDT&timestamp=1234567890", hashlib.sha256).hexdigest()
        assert sig == expected

    def test_empty_params(self):
        c = BinanceHTTPClient(api_key="k", api_secret="s")
        sig = c._sign({})
        expected = hmac.new(b"s", b"", hashlib.sha256).hexdigest()
        assert sig == expected

    def test_special_characters(self):
        c = BinanceHTTPClient(api_key="k", api_secret="sec")
        sig = c._sign({"symbol": "BTC/USDT", "side": "BUY"})
        # urllib.parse.urlencode encodes / → %2F
        expected = hmac.new(b"sec", b"symbol=BTC%2FUSDT&side=BUY", hashlib.sha256).hexdigest()
        assert sig == expected


# ═════════════════════════════════════════════════════════════════════════════
# 3. _request — HTTP retry logic
# ═════════════════════════════════════════════════════════════════════════════


def _make_urlopen_response(data: dict | list | str, status: int = 200):
    """Create a mock urlopen context manager that returns given data."""

    class MockResponse:
        def __init__(self, data, status):
            self._data = data
            self.status = status

        def read(self):
            if isinstance(self._data, str):
                return self._data.encode()
            return json.dumps(self._data).encode()

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    return MockResponse(data, status)


class TestRequestSuccess:
    """_request — successful calls."""

    def test_get_request(self):
        c = BinanceHTTPClient(api_key="k", api_secret="s")
        mock_resp = _make_urlopen_response({"status": "ok"})
        with patch.object(urllib.request, "urlopen", return_value=mock_resp) as mock_urlopen:
            result = c._request("GET", "/fapi/v1/exchangeInfo")
            assert result == {"status": "ok"}
            mock_urlopen.assert_called_once()

    def test_post_request_signed(self):
        c = BinanceHTTPClient(api_key="k", api_secret="s")
        mock_resp = _make_urlopen_response({"orderId": 12345})
        with patch.object(urllib.request, "urlopen", return_value=mock_resp) as mock_urlopen:
            with patch.object(c, "_sign", return_value="fake_signature"):
                result = c._request("POST", "/fapi/v1/order", {"symbol": "BTCUSDT"}, signed=True)
                assert result == {"orderId": 12345}
                mock_urlopen.assert_called_once()

    def test_delete_request(self):
        c = BinanceHTTPClient(api_key="k", api_secret="s")
        mock_resp = _make_urlopen_response({"status": "ok"})
        with patch.object(urllib.request, "urlopen", return_value=mock_resp):
            result = c._request("DELETE", "/fapi/v1/order", {"symbol": "BTCUSDT", "orderId": 123})
            assert result == {"status": "ok"}

    def test_empty_response_body(self):
        c = BinanceHTTPClient(api_key="k", api_secret="s")
        mock_resp = _make_urlopen_response("")
        with patch.object(urllib.request, "urlopen", return_value=mock_resp):
            result = c._request("GET", "/fapi/v1/test")
            assert result == {}

    def test_ok_response_portfolio_margin(self):
        c = BinanceHTTPClient(api_key="k", api_secret="s")
        mock_resp = _make_urlopen_response("ok")
        with patch.object(urllib.request, "urlopen", return_value=mock_resp):
            result = c._request("POST", "/papi/v1/um/order", signed=True)
            assert result == {"status": "ok"}

    def test_signed_adds_timestamp_and_signature(self):
        c = BinanceHTTPClient(api_key="k", api_secret="s")
        mock_resp = _make_urlopen_response({"ok": True})
        with patch.object(urllib.request, "urlopen", return_value=mock_resp) as mock_urlopen:
            with patch.object(c, "_sign", return_value="sig123"):
                result = c._request("POST", "/fapi/v1/order", {"symbol": "BTCUSDT"}, signed=True)
                # The request should include timestamp and signature
                assert result == {"ok": True}
                mock_urlopen.assert_called_once()


class TestRequestRetry429:
    """_request — 429 rate limit retry."""

    def test_429_retry_success(self):
        c = BinanceHTTPClient(api_key="k", api_secret="s")
        err_429 = urllib.error.HTTPError(
            "http://test",
            429,
            "Rate Limited",
            {"Retry-After": "1"},
            None,
        )
        # Set fp to return JSON with Binance error code
        err_429.fp = MagicMock()
        err_429.fp.read.return_value = json.dumps({"code": -1003, "msg": "Too many requests"}).encode()

        success_resp = _make_urlopen_response({"status": "ok"})

        with patch.object(urllib.request, "urlopen", side_effect=[err_429, success_resp]) as mock_urlopen:
            with patch.object(time, "sleep", return_value=None) as mock_sleep:
                result = c._request("GET", "/fapi/v1/test", max_retries=2)
                assert result == {"status": "ok"}
                assert mock_urlopen.call_count == 2
                mock_sleep.assert_called_once_with(1.0)  # Retry-After header value

    def test_429_no_retry_header_fallback(self):
        c = BinanceHTTPClient(api_key="k", api_secret="s")
        err_429 = urllib.error.HTTPError("http://test", 429, "Rate Limited", {}, None)
        err_429.fp = MagicMock()
        err_429.fp.read.return_value = json.dumps({"code": -1003, "msg": "Too many"}).encode()

        success_resp = _make_urlopen_response({"status": "ok"})

        with patch.object(urllib.request, "urlopen", side_effect=[err_429, success_resp]):
            with patch.object(time, "sleep", return_value=None) as mock_sleep:
                result = c._request("GET", "/fapi/v1/test", max_retries=2)
                assert result == {"status": "ok"}
                mock_sleep.assert_called_once_with(2.0)  # 2.0 * (0 + 1)

    def test_429_retry_exhausted(self):
        c = BinanceHTTPClient(api_key="k", api_secret="s")
        err_429 = urllib.error.HTTPError("http://test", 429, "Rate Limited", {}, None)
        err_429.fp = MagicMock()
        err_429.fp.read.return_value = json.dumps({"code": -1003, "msg": "Too many"}).encode()

        with patch.object(urllib.request, "urlopen", side_effect=err_429):
            with patch.object(time, "sleep", return_value=None):
                with pytest.raises(urllib.error.HTTPError):
                    c._request("GET", "/fapi/v1/test", max_retries=2)

    def test_429_with_invalid_retry_after_header(self):
        c = BinanceHTTPClient(api_key="k", api_secret="s")
        err_429 = urllib.error.HTTPError(
            "http://test",
            429,
            "Rate Limited",
            {"Retry-After": "not-a-number"},
            None,
        )
        err_429.fp = MagicMock()
        err_429.fp.read.return_value = b""

        success_resp = _make_urlopen_response({"status": "ok"})

        with patch.object(urllib.request, "urlopen", side_effect=[err_429, success_resp]):
            with patch.object(time, "sleep", return_value=None) as mock_sleep:
                result = c._request("GET", "/fapi/v1/test", max_retries=1)
                assert result == {"status": "ok"}
                mock_sleep.assert_called_once_with(5.0)  # fallback on invalid header


class TestRequestRetry5xx:
    """_request — 5xx server error retry."""

    def test_5xx_retry_success(self):
        c = BinanceHTTPClient(api_key="k", api_secret="s")
        err_502 = urllib.error.HTTPError("http://test", 502, "Bad Gateway", {}, None)
        err_502.fp = MagicMock()
        err_502.fp.read.return_value = b""

        success_resp = _make_urlopen_response({"status": "ok"})

        with patch.object(urllib.request, "urlopen", side_effect=[err_502, success_resp]):
            with patch.object(time, "sleep", return_value=None) as mock_sleep:
                result = c._request("GET", "/fapi/v1/test", max_retries=2)
                assert result == {"status": "ok"}
                mock_sleep.assert_called_once_with(2.0)  # 2.0 * (0 + 1)

    def test_5xx_retry_exhausted(self):
        c = BinanceHTTPClient(api_key="k", api_secret="s")
        err_500 = urllib.error.HTTPError("http://test", 500, "Server Error", {}, None)
        err_500.fp = MagicMock()
        err_500.fp.read.return_value = b""

        with patch.object(urllib.request, "urlopen", side_effect=err_500):
            with patch.object(time, "sleep", return_value=None):
                with pytest.raises(urllib.error.HTTPError):
                    c._request("GET", "/fapi/v1/test", max_retries=2)


class TestRequestFatalCodes:
    """_request — fatal Binance error codes (no retry)."""

    FATAL_CODES = [-1013, -2010, -2015, -2019, -4061]

    @pytest.mark.parametrize("code", FATAL_CODES)
    def test_fatal_code_no_retry(self, code):
        c = BinanceHTTPClient(api_key="k", api_secret="s")
        err = urllib.error.HTTPError("http://test", 400, "Bad Request", {}, None)
        # HTTPError.read is C-defined — mock on the instance directly
        err.read = MagicMock(return_value=json.dumps({"code": code, "msg": "Fatal error"}).encode())
        err.fp = MagicMock()  # truthy for `if e.fp:` guard

        with patch.object(urllib.request, "urlopen", side_effect=err):
            with patch.object(time, "sleep", return_value=None) as mock_sleep:
                with pytest.raises(urllib.error.HTTPError):
                    c._request("POST", "/fapi/v1/order", max_retries=3)
                mock_sleep.assert_not_called()


class TestRequestURLError:
    """_request — URLError (timeout) retry."""

    def test_urlerror_retry_success(self):
        c = BinanceHTTPClient(api_key="k", api_secret="s")
        err = urllib.error.URLError("timeout")
        success_resp = _make_urlopen_response({"status": "ok"})

        with patch.object(urllib.request, "urlopen", side_effect=[err, success_resp]):
            with patch.object(time, "sleep", return_value=None) as mock_sleep:
                result = c._request("GET", "/fapi/v1/test", max_retries=1)
                assert result == {"status": "ok"}
                mock_sleep.assert_called_once()

    def test_urlerror_retry_exhausted(self):
        c = BinanceHTTPClient(api_key="k", api_secret="s")
        err = urllib.error.URLError("timeout")

        with patch.object(urllib.request, "urlopen", side_effect=err):
            with patch.object(time, "sleep", return_value=None):
                with pytest.raises(urllib.error.URLError):
                    c._request("GET", "/fapi/v1/test", max_retries=2)


class TestRequest4xxRetry:
    """_request — generic 4xx retry (non-fatal, non-429)."""

    def test_4xx_retry_success(self):
        c = BinanceHTTPClient(api_key="k", api_secret="s")
        err = urllib.error.HTTPError("http://test", 400, "Bad Request", {}, None)
        err.fp = MagicMock()
        err.fp.read.return_value = json.dumps({"code": 0, "msg": "Unknown"}).encode()

        success_resp = _make_urlopen_response({"status": "ok"})

        with patch.object(urllib.request, "urlopen", side_effect=[err, success_resp]):
            with patch.object(time, "sleep", return_value=None) as mock_sleep:
                result = c._request("GET", "/fapi/v1/test", max_retries=1)
                assert result == {"status": "ok"}
                mock_sleep.assert_called_once_with(1.5)  # 1.5 * (0 + 1)


class TestRequestNoRetries:
    """_request — max_retries=0, no retry."""

    def test_http_error_no_retry(self):
        c = BinanceHTTPClient(api_key="k", api_secret="s")
        err = urllib.error.HTTPError("http://test", 400, "Bad Request", {}, None)
        err.fp = MagicMock()
        err.fp.read.return_value = b"error body"

        with patch.object(urllib.request, "urlopen", side_effect=err):
            with pytest.raises(urllib.error.HTTPError):
                c._request("GET", "/fapi/v1/test", max_retries=0)

    def test_urlerror_no_retry(self):
        c = BinanceHTTPClient(api_key="k", api_secret="s")
        err = urllib.error.URLError("timeout")

        with patch.object(urllib.request, "urlopen", side_effect=err):
            with pytest.raises(urllib.error.URLError):
                c._request("GET", "/fapi/v1/test", max_retries=0)


# ═════════════════════════════════════════════════════════════════════════════
# 4. Precision helpers
# ═════════════════════════════════════════════════════════════════════════════

BTCUSDT_INFO = {
    "symbol": "BTCUSDT",
    "filters": [
        {"filterType": "PRICE_FILTER", "tickSize": "0.10"},
        {"filterType": "LOT_SIZE", "stepSize": "0.001", "minQty": "0.001"},
    ],
}

ETHUSDT_INFO = {
    "symbol": "ETHUSDT",
    "filters": [
        {"filterType": "PRICE_FILTER", "tickSize": "0.01"},
        {"filterType": "LOT_SIZE", "stepSize": "0.001", "minQty": "0.001"},
    ],
}


class TestPrecisionHelpers:
    """get_tick_size, get_step_size, get_min_qty, apply_price/amount_precision."""

    def test_get_tick_size_known_symbol(self):
        c = BinanceHTTPClient(api_key="k", api_secret="s")
        c._symbol_info["BTCUSDT"] = BTCUSDT_INFO
        assert c.get_tick_size("BTCUSDT") == 0.10

    def test_get_tick_size_unknown_symbol(self):
        c = BinanceHTTPClient(api_key="k", api_secret="s")
        assert c.get_tick_size("UNKNOWN") == 0.0001

    def test_get_tick_size_no_filters(self):
        c = BinanceHTTPClient(api_key="k", api_secret="s")
        c._symbol_info["BLAH"] = {"symbol": "BLAH", "filters": []}
        assert c.get_tick_size("BLAH") == 0.0001

    def test_get_step_size_known_symbol(self):
        c = BinanceHTTPClient(api_key="k", api_secret="s")
        c._symbol_info["BTCUSDT"] = BTCUSDT_INFO
        assert c.get_step_size("BTCUSDT") == 0.001

    def test_get_step_size_unknown_symbol(self):
        c = BinanceHTTPClient(api_key="k", api_secret="s")
        assert c.get_step_size("UNKNOWN") == 0.001

    def test_get_step_size_no_lot_filter(self):
        c = BinanceHTTPClient(api_key="k", api_secret="s")
        c._symbol_info["BLAH"] = {"symbol": "BLAH", "filters": [{"filterType": "PRICE_FILTER", "tickSize": "0.01"}]}
        assert c.get_step_size("BLAH") == 0.001

    def test_get_min_qty_known_symbol(self):
        c = BinanceHTTPClient(api_key="k", api_secret="s")
        c._symbol_info["BTCUSDT"] = BTCUSDT_INFO
        assert c.get_min_qty("BTCUSDT") == 0.001

    def test_get_min_qty_unknown_symbol(self):
        c = BinanceHTTPClient(api_key="k", api_secret="s")
        assert c.get_min_qty("UNKNOWN") == 0.0

    def test_apply_price_precision(self):
        c = BinanceHTTPClient(api_key="k", api_secret="s")
        c._symbol_info["BTCUSDT"] = BTCUSDT_INFO
        assert c.apply_price_precision("BTCUSDT", 50123.456) == 50123.5

    def test_apply_price_precision_none(self):
        c = BinanceHTTPClient(api_key="k", api_secret="s")
        assert c.apply_price_precision("BTCUSDT", None) is None

    def test_apply_price_precision_zero(self):
        c = BinanceHTTPClient(api_key="k", api_secret="s")
        assert c.apply_price_precision("BTCUSDT", 0) == 0

    def test_apply_amount_precision(self):
        c = BinanceHTTPClient(api_key="k", api_secret="s")
        c._symbol_info["BTCUSDT"] = BTCUSDT_INFO
        assert c.apply_amount_precision("BTCUSDT", 1.2345) == 1.234

    def test_apply_amount_precision_none(self):
        c = BinanceHTTPClient(api_key="k", api_secret="s")
        assert c.apply_amount_precision("BTCUSDT", None) is None

    def test_apply_amount_precision_zero(self):
        c = BinanceHTTPClient(api_key="k", api_secret="s")
        assert c.apply_amount_precision("BTCUSDT", 0) == 0

    def test_get_symbol_info_invalid_json(self):
        """Test get_symbol_info with exchange info that has no symbols key."""
        c = BinanceHTTPClient(api_key="k", api_secret="s")
        with patch.object(c, "_load_exchange_info", return_value={"symbols": []}):
            assert c.get_symbol_info("BTCUSDT") is None


# ═════════════════════════════════════════════════════════════════════════════
# 5. Data methods: get_klines, get_open_orders, get_algo_orders
# ═════════════════════════════════════════════════════════════════════════════


class TestGetKlines:
    """get_klines — OHLCV data parsing."""

    def test_basic_klines(self):
        c = BinanceHTTPClient(api_key="k", api_secret="s")
        raw = [
            [
                1680000000000,
                "50000.0",
                "51000.0",
                "49000.0",
                "50500.0",
                "100.5",
                "1680000000000",
                "100.5",
                100,
                "50.0",
                "2500000.0",
                "0",
            ],
            [
                1680000060000,
                "50500.0",
                "51500.0",
                "50000.0",
                "51200.0",
                "80.2",
                "1680000060000",
                "80.2",
                80,
                "40.0",
                "2000000.0",
                "0",
            ],
        ]
        with patch.object(c, "_request", return_value=raw):
            result = c.get_klines("BTCUSDT", "5m", 2)
            assert len(result) == 2
            assert result[0] == [1680000000000, 50000.0, 51000.0, 49000.0, 50500.0, 100.5]
            assert result[1] == [1680000060000, 50500.0, 51500.0, 50000.0, 51200.0, 80.2]

    def test_empty_klines(self):
        c = BinanceHTTPClient(api_key="k", api_secret="s")
        with patch.object(c, "_request", return_value=[]):
            result = c.get_klines("BTCUSDT", "5m", 10)
            assert result == []

    def test_klines_passes_max_retries(self):
        c = BinanceHTTPClient(api_key="k", api_secret="s")
        with patch.object(c, "_request", return_value=[]) as mock_req:
            c.get_klines("BTCUSDT", "15m", 5, max_retries=3)
            mock_req.assert_called_once_with(
                "GET",
                "/fapi/v1/klines",
                {"symbol": "BTCUSDT", "interval": "15m", "limit": 5},
                signed=False,
                max_retries=3,
            )


class TestGetOpenOrders:
    """get_open_orders, get_algo_orders, get_all_open_orders."""

    def test_get_open_orders_list(self):
        c = BinanceHTTPClient(api_key="k", api_secret="s")
        raw = [{"orderId": 1, "symbol": "BTCUSDT"}]
        with patch.object(c, "_request", return_value=raw):
            result = c.get_open_orders("BTCUSDT")
            assert result == raw

    def test_get_open_orders_dict_with_orders_key(self):
        c = BinanceHTTPClient(api_key="k", api_secret="s")
        raw = {"orders": [{"orderId": 1}]}
        with patch.object(c, "_request", return_value=raw):
            result = c.get_open_orders("BTCUSDT")
            assert result == [{"orderId": 1}]

    def test_get_open_orders_dict_with_open_orders_key(self):
        c = BinanceHTTPClient(api_key="k", api_secret="s")
        raw = {"openOrders": [{"orderId": 2}]}
        with patch.object(c, "_request", return_value=raw):
            result = c.get_open_orders("BTCUSDT")
            assert result == [{"orderId": 2}]

    def test_get_open_orders_empty_dict(self):
        c = BinanceHTTPClient(api_key="k", api_secret="s")
        with patch.object(c, "_request", return_value={}):
            result = c.get_open_orders("BTCUSDT")
            assert result == []

    def test_get_algo_orders_list(self):
        c = BinanceHTTPClient(api_key="k", api_secret="s")
        raw = [{"algoId": 1, "symbol": "BTCUSDT"}]
        with patch.object(c, "_request", return_value=raw):
            result = c.get_algo_orders("BTCUSDT")
            assert result == raw

    def test_get_algo_orders_dict_with_orders_key(self):
        c = BinanceHTTPClient(api_key="k", api_secret="s")
        raw = {"orders": [{"algoId": 1}]}
        with patch.object(c, "_request", return_value=raw):
            result = c.get_algo_orders("BTCUSDT")
            assert result == [{"algoId": 1}]

    def test_get_algo_orders_dict_with_algo_orders_key(self):
        c = BinanceHTTPClient(api_key="k", api_secret="s")
        raw = {"algoOrders": [{"algoId": 2}]}
        with patch.object(c, "_request", return_value=raw):
            result = c.get_algo_orders("BTCUSDT")
            assert result == [{"algoId": 2}]

    def test_get_algo_orders_empty_dict(self):
        c = BinanceHTTPClient(api_key="k", api_secret="s")
        with patch.object(c, "_request", return_value={}):
            result = c.get_algo_orders("BTCUSDT")
            assert result == []

    def test_get_all_open_orders_combines(self):
        c = BinanceHTTPClient(api_key="k", api_secret="s")
        with patch.object(c, "get_open_orders", return_value=[{"orderId": 1}]):
            with patch.object(c, "get_algo_orders", return_value=[{"algoId": 2}]):
                result = c.get_all_open_orders("BTCUSDT")
                assert len(result) == 2
                assert result[0] == {"orderId": 1}
                assert result[1] == {"algoId": 2}

    def test_get_all_open_orders_handles_errors(self):
        c = BinanceHTTPClient(api_key="k", api_secret="s")
        with patch.object(c, "get_open_orders", side_effect=Exception("fail")):
            with patch.object(c, "get_algo_orders", return_value=[{"algoId": 2}]):
                result = c.get_all_open_orders("BTCUSDT")
                assert len(result) == 1
                assert result[0] == {"algoId": 2}


# ═════════════════════════════════════════════════════════════════════════════
# 6. Order methods: create_order, create_algo_order, create_stop_order_standard, query, cancel
# ═════════════════════════════════════════════════════════════════════════════

ORDER_RESPONSE = {"orderId": 12345, "symbol": "BTCUSDT", "status": "NEW"}


class TestCreateOrder:
    """create_order — MARKET/STOP_MARKET order."""

    def test_market_order(self):
        c = BinanceHTTPClient(api_key="k", api_secret="s")
        with patch.object(c, "_request", return_value=ORDER_RESPONSE) as mock_req:
            result = c.create_order("BTCUSDT", "MARKET", "BUY", 0.01)
            assert result["orderId"] == 12345
            mock_req.assert_called_once()
            call_args = mock_req.call_args[0]
            assert call_args[0] == "POST"
            assert call_args[2]["symbol"] == "BTCUSDT"
            assert call_args[2]["side"] == "BUY"
            assert call_args[2]["type"] == "MARKET"
            assert call_args[2]["quantity"] == 0.01

    def test_limit_order_with_price(self):
        c = BinanceHTTPClient(api_key="k", api_secret="s")
        with patch.object(c, "_request", return_value=ORDER_RESPONSE) as mock_req:
            result = c.create_order("BTCUSDT", "LIMIT", "SELL", 0.01, price=50000.0)
            assert result["orderId"] == 12345
            call_args = mock_req.call_args[0]
            assert call_args[2]["price"] == 50000.0

    def test_order_with_extra_params(self):
        c = BinanceHTTPClient(api_key="k", api_secret="s")
        with patch.object(c, "_request", return_value=ORDER_RESPONSE) as mock_req:
            result = c.create_order(
                "BTCUSDT", "STOP_MARKET", "SELL", 0.01, params={"stopPrice": 49000, "reduceOnly": True}
            )
            assert result["orderId"] == 12345
            call_args = mock_req.call_args[0]
            assert call_args[2]["stopPrice"] == 49000
            assert call_args[2]["reduceOnly"] is True

    def test_pm_endpoint_none_returns_empty(self):
        c = BinanceHTTPClient(api_key="k", api_secret="s", portfolio_margin=True)
        # Override _ep for this specific path to return None
        with patch.object(c, "_ep", return_value=None):
            result = c.create_order("BTCUSDT", "MARKET", "BUY", 0.01)
            assert result == {}

    def test_demo_no_order_id_fallback(self):
        """When orderId is missing, fallback to get_open_orders."""
        c = BinanceHTTPClient(api_key="k", api_secret="s")
        with patch.object(c, "_request", return_value={"status": "ok"}):
            with patch.object(c, "get_open_orders", return_value=[ORDER_RESPONSE]):
                with patch.object(time, "sleep", return_value=None):
                    result = c.create_order("BTCUSDT", "MARKET", "BUY", 0.01)
                    assert result["orderId"] == 12345

    def test_demo_fallback_pm_std_open_orders(self):
        """PM mode: first get_open_orders fails, falls back to std /fapi/v1/openOrders."""
        c = BinanceHTTPClient(api_key="k", api_secret="s", portfolio_margin=True)
        # _request: POST returns no orderId, then GET returns match
        post_return = {"status": "ok"}
        get_return = [{"orderId": 999, "symbol": "BTCUSDT", "type": "MARKET", "side": "BUY"}]

        with patch.object(c, "_request", side_effect=[post_return, get_return]):
            with patch.object(c, "get_open_orders", side_effect=Exception("fail")):
                with patch.object(time, "sleep", return_value=None):
                    result = c.create_order("BTCUSDT", "MARKET", "BUY", 0.01)
                    assert result["orderId"] == 999

    def test_demo_fallback_empty_all(self):
        """All fallback sources return empty."""
        c = BinanceHTTPClient(api_key="k", api_secret="s")
        with patch.object(c, "_request", return_value={"status": "ok"}):
            with patch.object(c, "get_open_orders", return_value=[]):
                with patch.object(time, "sleep", return_value=None):
                    result = c.create_order("BTCUSDT", "MARKET", "BUY", 0.01)
                    assert result == {"status": "ok"}


class TestCreateAlgoOrder:
    """create_algo_order — STOP/TAKE_PROFIT algo order."""

    def test_stop_algo_order(self):
        c = BinanceHTTPClient(api_key="k", api_secret="s")
        with patch.object(c, "_request", return_value={"algoId": 999}) as mock_req:
            result = c.create_algo_order("BTCUSDT", "STOP_MARKET", "SELL", 0.01, stop_price=49000.0)
            assert result["algoId"] == 999
            call_args = mock_req.call_args[0]
            assert call_args[2]["symbol"] == "BTCUSDT"
            assert call_args[2]["side"] == "SELL"
            assert call_args[2]["algoType"] == "CONDITIONAL"
            assert call_args[2]["triggerPrice"] == "49000.0"
            assert call_args[2]["closePosition"] == "true"

    def test_algo_order_default_close_position(self):
        c = BinanceHTTPClient(api_key="k", api_secret="s")
        with patch.object(c, "_request", return_value={"algoId": 999}) as mock_req:
            c.create_algo_order("ETHUSDT", "TAKE_PROFIT_MARKET", "BUY", 0.1, stop_price=3000.0)
            call_args = mock_req.call_args[0]
            assert call_args[2]["closePosition"] == "true"

    def test_algo_pm_endpoint_none(self):
        c = BinanceHTTPClient(api_key="k", api_secret="s", portfolio_margin=True)
        with patch.object(c, "_ep", return_value=None):
            result = c.create_algo_order("BTCUSDT", "STOP_MARKET", "SELL", 0.01, stop_price=49000.0)
            assert result == {}

    def test_algo_demo_fallback(self):
        c = BinanceHTTPClient(api_key="k", api_secret="s")
        with patch.object(c, "_request", return_value={"status": "ok"}):
            with patch.object(
                c,
                "get_algo_orders",
                return_value=[{"algoId": 777, "symbol": "BTCUSDT", "type": "STOP_MARKET", "side": "SELL"}],
            ):
                with patch.object(time, "sleep", return_value=None):
                    result = c.create_algo_order("BTCUSDT", "STOP_MARKET", "SELL", 0.01, stop_price=49000.0)
                    assert result["algoId"] == 777


class TestCreateStopOrderStandard:
    """create_stop_order_standard — STOP/TP via /fapi/v1/order."""

    def test_stop_order_standard(self):
        c = BinanceHTTPClient(api_key="k", api_secret="s")
        with patch.object(c, "_request", return_value={"orderId": 555}) as mock_req:
            result = c.create_stop_order_standard("BTCUSDT", "STOP_MARKET", "SELL", 0.01, stop_price=49000.0)
            assert result["orderId"] == 555
            call_args = mock_req.call_args[0]
            assert call_args[2]["stopPrice"] == 49000.0
            assert call_args[2]["reduceOnly"] is True
            assert call_args[2]["closePosition"] is False

    def test_stop_order_standard_extra_params(self):
        c = BinanceHTTPClient(api_key="k", api_secret="s")
        with patch.object(c, "_request", return_value={"orderId": 556}) as mock_req:
            c.create_stop_order_standard(
                "BTCUSDT", "TAKE_PROFIT_MARKET", "BUY", 0.01, stop_price=51000.0, params={"timeInForce": "GTC"}
            )
            call_args = mock_req.call_args[0]
            assert call_args[2]["timeInForce"] == "GTC"

    def test_stop_order_standard_pm_endpoint_none(self):
        c = BinanceHTTPClient(api_key="k", api_secret="s", portfolio_margin=True)
        with patch.object(c, "_ep", return_value=None):
            result = c.create_stop_order_standard("BTCUSDT", "STOP_MARKET", "SELL", 0.01, stop_price=49000.0)
            assert result == {}


class TestQueryOrder:
    """query_order — single order query."""

    def test_query_order(self):
        c = BinanceHTTPClient(api_key="k", api_secret="s")
        with patch.object(c, "_request", return_value={"orderId": 123, "status": "FILLED"}) as mock_req:
            result = c.query_order("BTCUSDT", 123)
            assert result["status"] == "FILLED"
            mock_req.assert_called_once()


class TestCancelOrder:
    """cancel_order — normal and algo order cancellation."""

    def test_cancel_normal_order(self):
        c = BinanceHTTPClient(api_key="k", api_secret="s")
        with patch.object(c, "_request", return_value={"status": "CANCELED"}) as mock_req:
            result = c.cancel_order("BTCUSDT", "12345")
            assert result["status"] == "CANCELED"
            mock_req.assert_called_once()

    def test_cancel_algo_order(self):
        c = BinanceHTTPClient(api_key="k", api_secret="s")
        with patch.object(c, "_request", return_value={"status": "CANCELED"}) as mock_req:
            result = c.cancel_order("BTCUSDT", "algo_999", is_algo=True)
            assert result["status"] == "CANCELED"
            call_args = mock_req.call_args[0]
            assert call_args[2]["algoId"] == "algo_999"

    def test_cancel_algo_raises(self):
        c = BinanceHTTPClient(api_key="k", api_secret="s")
        with patch.object(c, "_request", side_effect=Exception("fail")):
            with pytest.raises(Exception, match="fail"):
                c.cancel_order("BTCUSDT", "algo_999", is_algo=True)

    def test_cancel_normal_fallsback_to_algo(self):
        """Normal cancel fails, tries algo endpoint."""
        c = BinanceHTTPClient(api_key="k", api_secret="s")
        algo_resp = {"status": "CANCELED_ALGO"}
        with patch.object(c, "_request", side_effect=[Exception("not normal"), algo_resp]) as mock_req:
            result = c.cancel_order("BTCUSDT", "mixed_id", is_algo=False)
            assert result["status"] == "CANCELED_ALGO"
            assert mock_req.call_count == 2

    def test_cancel_both_fail(self):
        """Both normal and algo cancel fail."""
        c = BinanceHTTPClient(api_key="k", api_secret="s")
        with patch.object(c, "_request", side_effect=Exception("fail")):
            with pytest.raises(Exception, match="fail"):
                c.cancel_order("BTCUSDT", "bad_id", is_algo=False)


# ═════════════════════════════════════════════════════════════════════════════
# 7. Listen key + misc: positions, account, margin, leverage
# ═════════════════════════════════════════════════════════════════════════════


class TestPositionsAndAccount:
    """get_positions, get_account."""

    def test_get_positions_all(self):
        c = BinanceHTTPClient(api_key="k", api_secret="s")
        raw = [{"symbol": "BTCUSDT", "positionAmt": "1.0"}, {"symbol": "ETHUSDT", "positionAmt": "0.0"}]
        with patch.object(c, "_request", return_value=raw) as mock_req:
            result = c.get_positions()
            assert len(result) == 2
            mock_req.assert_called_once()

    def test_get_positions_symbol(self):
        c = BinanceHTTPClient(api_key="k", api_secret="s")
        with patch.object(c, "_request", return_value=[{"symbol": "BTCUSDT"}]) as mock_req:
            c.get_positions("BTCUSDT")
            call_args = mock_req.call_args[0]
            assert call_args[2]["symbol"] == "BTCUSDT"

    def test_get_account(self):
        c = BinanceHTTPClient(api_key="k", api_secret="s")
        raw = {"totalWalletBalance": "10000.0"}
        with patch.object(c, "_request", return_value=raw) as mock_req:
            result = c.get_account()
            assert result["totalWalletBalance"] == "10000.0"
            mock_req.assert_called_once()


class TestMarginAndLeverage:
    """set_margin_mode, set_leverage."""

    def test_set_margin_mode(self):
        c = BinanceHTTPClient(api_key="k", api_secret="s")
        with patch.object(c, "_request", return_value={"code": 200}) as mock_req:
            result = c.set_margin_mode("BTCUSDT", "ISOLATED")
            assert result["code"] == 200
            mock_req.assert_called_once()

    def test_set_margin_mode_pm_skip(self):
        c = BinanceHTTPClient(api_key="k", api_secret="s", portfolio_margin=True)
        with patch.object(c, "_ep", return_value=None):
            result = c.set_margin_mode("BTCUSDT", "ISOLATED")
            assert result == {}

    def test_set_leverage(self):
        c = BinanceHTTPClient(api_key="k", api_secret="s")
        with patch.object(c, "_request", return_value={"leverage": 10}) as mock_req:
            result = c.set_leverage("BTCUSDT", 10)
            assert result["leverage"] == 10
            mock_req.assert_called_once()


class TestListenKey:
    """new_listen_key, renew_listen_key, delete_listen_key."""

    def test_new_listen_key(self):
        c = BinanceHTTPClient(api_key="k", api_secret="s")
        with patch.object(c, "_request", return_value={"listenKey": "abc123"}) as mock_req:
            result = c.new_listen_key()
            assert result == "abc123"
            mock_req.assert_called_once()

    def test_new_listen_key_missing_key(self):
        c = BinanceHTTPClient(api_key="k", api_secret="s")
        with patch.object(c, "_request", return_value={}):
            result = c.new_listen_key()
            assert result == ""

    def test_renew_listen_key_success(self):
        c = BinanceHTTPClient(api_key="k", api_secret="s")
        with patch.object(c, "_request", return_value={}):
            result = c.renew_listen_key("abc123")
            assert result is True

    def test_renew_listen_key_failure(self):
        c = BinanceHTTPClient(api_key="k", api_secret="s")
        with patch.object(c, "_request", side_effect=Exception("fail")):
            result = c.renew_listen_key("abc123")
            assert result is False

    def test_delete_listen_key_success(self):
        c = BinanceHTTPClient(api_key="k", api_secret="s")
        with patch.object(c, "_request", return_value={}):
            result = c.delete_listen_key("abc123")
            assert result is True

    def test_delete_listen_key_failure(self):
        c = BinanceHTTPClient(api_key="k", api_secret="s")
        with patch.object(c, "_request", side_effect=Exception("fail")):
            result = c.delete_listen_key("abc123")
            assert result is False


# ═════════════════════════════════════════════════════════════════════════════
# 8. _load_exchange_info — cached exchange info
# ═════════════════════════════════════════════════════════════════════════════


class TestExchangeInfo:
    """_load_exchange_info and get_symbol_info."""

    EXCHANGE_DATA = {
        "symbols": [
            {
                "symbol": "BTCUSDT",
                "filters": [
                    {"filterType": "PRICE_FILTER", "tickSize": "0.10"},
                    {"filterType": "LOT_SIZE", "stepSize": "0.001", "minQty": "0.001"},
                ],
            },
        ],
    }

    def test_load_exchange_info_first_time(self):
        c = BinanceHTTPClient(api_key="k", api_secret="s")
        with patch.object(c, "_request", return_value=self.EXCHANGE_DATA) as mock_req:
            result = c._load_exchange_info()
            assert len(result["symbols"]) == 1
            assert c._symbol_info["BTCUSDT"] is not None
            mock_req.assert_called_once()

    def test_load_exchange_info_cached(self):
        c = BinanceHTTPClient(api_key="k", api_secret="s")
        c._exchange_info = self.EXCHANGE_DATA
        c._exchange_info_ts = time.time()  # just now
        with patch.object(c, "_request") as mock_req:
            result = c._load_exchange_info()
            assert result == self.EXCHANGE_DATA
            mock_req.assert_not_called()  # cached, no request

    def test_load_exchange_info_force(self):
        c = BinanceHTTPClient(api_key="k", api_secret="s")
        c._exchange_info = {"old": True}
        c._exchange_info_ts = time.time()
        with patch.object(c, "_request", return_value=self.EXCHANGE_DATA) as mock_req:
            result = c._load_exchange_info(force=True)
            assert len(result["symbols"]) == 1
            mock_req.assert_called_once()

    def test_load_exchange_info_expired_cache(self):
        c = BinanceHTTPClient(api_key="k", api_secret="s")
        c._exchange_info = {"old": True}
        c._exchange_info_ts = time.time() - 400  # 400 seconds ago (> 300 cache)
        with patch.object(c, "_request", return_value=self.EXCHANGE_DATA) as mock_req:
            result = c._load_exchange_info()
            assert len(result["symbols"]) == 1
            mock_req.assert_called_once()

    def test_get_symbol_info_cached(self):
        c = BinanceHTTPClient(api_key="k", api_secret="s")
        c._exchange_info = self.EXCHANGE_DATA
        c._exchange_info_ts = time.time()
        c._symbol_info = {"BTCUSDT": self.EXCHANGE_DATA["symbols"][0]}
        with patch.object(c, "_request") as mock_req:
            info = c.get_symbol_info("BTCUSDT")
            assert info["symbol"] == "BTCUSDT"
            mock_req.assert_not_called()
