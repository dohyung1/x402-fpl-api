"""
Tests for the x402 payment middleware.

These tests use httpx TestClient and mock on-chain verification
so we don't need a live Base Sepolia connection.
"""

import pytest
import sqlite3
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient

from app.main import app
from app.x402 import _DB_PATH, _init_db

client = TestClient(app, raise_server_exceptions=False)

FAKE_TX = "0xdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeef"


@pytest.fixture(autouse=True)
def clear_used_hashes():
    """Reset replay-protection database between tests."""
    # Clear the used_tx_hashes table
    _init_db()
    conn = sqlite3.connect(str(_DB_PATH))
    try:
        conn.execute("DELETE FROM used_tx_hashes")
        conn.commit()
    finally:
        conn.close()
    yield
    # Clean up after test
    conn = sqlite3.connect(str(_DB_PATH))
    try:
        conn.execute("DELETE FROM used_tx_hashes")
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Health / root -- should never require payment
# ---------------------------------------------------------------------------

def test_health_no_payment():
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_root_no_payment():
    resp = client.get("/")
    assert resp.status_code == 200
    data = resp.json()
    assert "endpoints" in data
    assert data["protocol"] == "x402"


# ---------------------------------------------------------------------------
# 402 -- no payment header
# ---------------------------------------------------------------------------

def test_captain_pick_requires_payment():
    resp = client.get("/api/fpl/captain-pick")
    assert resp.status_code == 402
    body = resp.json()
    assert body["x402"] is True
    assert "payment" in body
    assert body["payment"]["asset"] == "USDC"


def test_differentials_requires_payment():
    resp = client.get("/api/fpl/differentials")
    assert resp.status_code == 402


def test_fixture_outlook_requires_payment():
    resp = client.get("/api/fpl/fixture-outlook")
    assert resp.status_code == 402


def test_price_predictions_requires_payment():
    resp = client.get("/api/fpl/price-predictions")
    assert resp.status_code == 402


def test_transfer_suggest_requires_payment():
    resp = client.get("/api/fpl/transfer-suggest?team_id=123")
    assert resp.status_code == 402


def test_live_points_requires_payment():
    resp = client.get("/api/fpl/live-points?team_id=123")
    assert resp.status_code == 402


# ---------------------------------------------------------------------------
# 402 payment details structure
# ---------------------------------------------------------------------------

def test_402_response_has_correct_price_captain():
    resp = client.get("/api/fpl/captain-pick")
    body = resp.json()
    assert body["payment"]["amount"] == 2_000  # $0.002


def test_402_response_has_correct_price_transfer():
    resp = client.get("/api/fpl/transfer-suggest?team_id=1")
    body = resp.json()
    assert body["payment"]["amount"] == 5_000  # $0.005


def test_402_response_has_correct_price_differentials():
    resp = client.get("/api/fpl/differentials")
    body = resp.json()
    assert body["payment"]["amount"] == 1_000  # $0.001


# ---------------------------------------------------------------------------
# Payment verification -- mocked on-chain calls
# ---------------------------------------------------------------------------

def _mock_receipt(to_wallet: str, amount: int, block: int = 100):
    """Build a minimal mock receipt with a USDC Transfer event."""
    receipt = MagicMock()
    receipt.__getitem__ = lambda self, key: block if key == "blockNumber" else None
    return receipt


def _make_mock_w3(wallet: str, amount: int, current_block: int = 101):
    """Return a mock Web3 instance that simulates a valid payment."""
    mock_w3 = MagicMock()
    mock_w3.is_connected.return_value = True
    mock_w3.eth.block_number = current_block

    mock_receipt = {"blockNumber": current_block - 1, "status": 1}
    mock_w3.eth.get_transaction_receipt.return_value = mock_receipt

    # Mock the Transfer event parsing
    mock_event = MagicMock()
    mock_event.__getitem__ = lambda self, key: {"args": {"to": wallet, "value": amount}}[key]
    mock_event["args"] = {"to": wallet, "value": amount}

    transfer_event = {"args": {"to": wallet, "value": amount}}
    mock_contract = MagicMock()
    mock_contract.events.Transfer.return_value.process_receipt.return_value = [transfer_event]
    mock_w3.eth.contract.return_value = mock_contract

    return mock_w3


def test_valid_payment_passes_middleware():
    """With a valid mocked payment, the request should reach the endpoint (200 or 500 from FPL API, not 402)."""
    from app.config import settings

    mock_w3 = _make_mock_w3(
        wallet=settings.payment_wallet_address.lower(),
        amount=2_000,  # captain-pick price
    )

    with patch("app.x402._get_web3", return_value=mock_w3), \
         patch("app.x402.Web3.to_checksum_address", return_value=settings.usdc_contract_address):
        resp = client.get(
            "/api/fpl/captain-pick",
            headers={"X-Payment": FAKE_TX},
        )
    # Should NOT be 402 -- either 200 (real FPL data) or 500 (FPL unreachable in test)
    assert resp.status_code != 402


def test_replay_attack_rejected():
    """The same tx hash cannot be used twice."""
    from app.config import settings

    mock_w3 = _make_mock_w3(
        wallet=settings.payment_wallet_address.lower(),
        amount=2_000,
    )

    with patch("app.x402._get_web3", return_value=mock_w3), \
         patch("app.x402.Web3.to_checksum_address", return_value=settings.usdc_contract_address):
        # First use succeeds (passes middleware)
        resp1 = client.get("/api/fpl/captain-pick", headers={"X-Payment": FAKE_TX})
        assert resp1.status_code != 402

        # Second use with same hash -> 402
        resp2 = client.get("/api/fpl/captain-pick", headers={"X-Payment": FAKE_TX})
        assert resp2.status_code == 402
        assert "already used" in resp2.json()["error"].lower()


def test_insufficient_payment_rejected():
    """A payment of the wrong amount is rejected."""
    from app.config import settings

    mock_w3 = _make_mock_w3(
        wallet=settings.payment_wallet_address.lower(),
        amount=1,  # way too low
    )

    with patch("app.x402._get_web3", return_value=mock_w3), \
         patch("app.x402.Web3.to_checksum_address", return_value=settings.usdc_contract_address), \
         patch("app.x402.settings") as mock_settings:
        mock_settings.test_mode = False
        mock_settings.payment_wallet_address = settings.payment_wallet_address
        mock_settings.usdc_contract_address = settings.usdc_contract_address
        mock_settings.required_confirmations = settings.required_confirmations
        mock_settings.service_name = settings.service_name
        mock_settings.service_description = settings.service_description
        resp = client.get("/api/fpl/captain-pick", headers={"X-Payment": FAKE_TX})
    assert resp.status_code == 402
    assert "insufficient" in resp.json()["error"].lower()


def test_unknown_tx_rejected():
    """A tx hash that doesn't exist on-chain is rejected."""
    from web3.exceptions import TransactionNotFound
    from app.config import settings

    mock_w3 = MagicMock()
    mock_w3.is_connected.return_value = True
    mock_w3.eth.block_number = 100
    # web3 v7: TransactionNotFound requires a message keyword argument
    mock_w3.eth.get_transaction_receipt.side_effect = TransactionNotFound(
        message="Transaction not found"
    )

    with patch("app.x402._get_web3", return_value=mock_w3), \
         patch("app.x402.settings") as mock_settings:
        mock_settings.test_mode = False
        mock_settings.payment_wallet_address = settings.payment_wallet_address
        mock_settings.usdc_contract_address = settings.usdc_contract_address
        mock_settings.required_confirmations = settings.required_confirmations
        mock_settings.service_name = settings.service_name
        mock_settings.service_description = settings.service_description
        resp = client.get("/api/fpl/captain-pick", headers={"X-Payment": FAKE_TX})
    assert resp.status_code == 402
    assert "not found" in resp.json()["error"].lower()
