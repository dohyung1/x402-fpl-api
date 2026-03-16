"""
x402 Payment Protocol implementation.

Flow:
  1. Agent hits endpoint with no auth -> server returns 402 + payment details
  2. Agent pays USDC on Base -> gets tx hash
  3. Agent retries with X-Payment: <tx_hash> header
  4. We verify the tx on-chain -> serve the response

Replay protection: used tx hashes persisted in SQLite (data/payments.db).
"""

import asyncio
import logging
import re
import sqlite3
from pathlib import Path

from fastapi import Request
from fastapi.responses import JSONResponse
from web3 import Web3
from web3.exceptions import TransactionNotFound

from app.config import ENDPOINT_PRICES, settings

logger = logging.getLogger(__name__)

# ERC-20 Transfer event ABI (minimal, just what we need)
ERC20_TRANSFER_ABI = [
    {
        "anonymous": False,
        "inputs": [
            {"indexed": True, "name": "from", "type": "address"},
            {"indexed": True, "name": "to", "type": "address"},
            {"indexed": False, "name": "value", "type": "uint256"},
        ],
        "name": "Transfer",
        "type": "event",
    }
]

# SQLite database for persistent replay protection
_DB_PATH = Path(__file__).resolve().parent.parent / "data" / "payments.db"


def _init_db() -> None:
    """Create the payments database and used_tx_hashes table if they don't exist."""
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(_DB_PATH))
    try:
        conn.execute("PRAGMA journal_mode=WAL")  # better concurrency under async
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS used_tx_hashes (
                tx_hash TEXT PRIMARY KEY,
                path TEXT NOT NULL,
                used_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.commit()
    finally:
        conn.close()


def _check_and_insert_tx(tx_hash: str, path: str) -> bool:
    """
    Atomically check if a tx hash has been used and insert it if not.

    Returns True if the hash was successfully inserted (not previously used).
    Returns False if the hash was already used (replay attack).

    Uses INSERT OR IGNORE with a UNIQUE constraint (PRIMARY KEY) for
    thread-safe, race-condition-free operation via SQLite's built-in locking.
    """
    conn = sqlite3.connect(str(_DB_PATH))
    try:
        cursor = conn.execute(
            "INSERT OR IGNORE INTO used_tx_hashes (tx_hash, path) VALUES (?, ?)",
            (tx_hash, path),
        )
        conn.commit()
        return cursor.rowcount == 1  # 1 = inserted (new), 0 = already existed
    finally:
        conn.close()


# Initialize database on module load
_init_db()


def _get_web3() -> Web3:
    """
    Create a Web3 instance connected to Base RPC.

    No caching -- Web3 instances are lightweight, and caching a broken
    connection (e.g., RPC down at startup) would require a server restart.
    """
    w3 = Web3(Web3.HTTPProvider(settings.base_rpc_url))
    if not w3.is_connected():
        logger.warning("Could not connect to Base RPC at %s", settings.base_rpc_url)
    return w3


def payment_required_response(path: str) -> JSONResponse:
    """Return a 402 response with payment details for the given endpoint."""
    price_usdc = ENDPOINT_PRICES.get(path, 1_000)
    return JSONResponse(
        status_code=402,
        content={
            "x402": True,
            "service": settings.service_name,
            "description": settings.service_description,
            "payment": {
                "scheme": "exact",
                "network": "base-sepolia",
                "asset": "USDC",
                "contract": settings.usdc_contract_address,
                "payee": settings.payment_wallet_address,
                "amount": price_usdc,
                "amount_display": f"${price_usdc / 1_000_000:.4f}",
            },
            "instructions": (
                "Send the exact USDC amount to the payee address on Base Sepolia. "
                "Then retry this request with the header: X-Payment: <tx_hash>"
            ),
        },
    )


class PaymentVerificationError(Exception):
    pass


async def verify_payment(tx_hash: str, path: str) -> None:
    """
    Verify that tx_hash is a valid USDC payment to our wallet for the correct amount.

    Raises PaymentVerificationError with a human-readable message on failure.

    All blocking Web3 RPC calls are run in a thread executor to avoid
    blocking the async event loop.
    """
    # Validate tx hash format (0x + 64 hex chars)
    clean_hash = tx_hash.strip()
    if not re.fullmatch(r"0x[0-9a-fA-F]{64}", clean_hash if clean_hash.startswith("0x") else "0x" + clean_hash):
        raise PaymentVerificationError("Invalid transaction hash format.")
    tx_hash = clean_hash

    if settings.test_mode:
        logger.info("TEST_MODE: skipping on-chain verification for %s (tx: %s)", path, tx_hash)
        if not _check_and_insert_tx(tx_hash.lower(), path):
            raise PaymentVerificationError("Transaction already used for a previous request.")
        return

    required_amount = ENDPOINT_PRICES.get(path, 1_000)
    wallet = settings.payment_wallet_address.lower()
    usdc_address = Web3.to_checksum_address(settings.usdc_contract_address)

    # Normalise hash
    if not tx_hash.startswith("0x"):
        tx_hash = "0x" + tx_hash
    tx_hash_lower = tx_hash.lower()

    # Replay protection -- atomic check-and-insert via SQLite
    if not _check_and_insert_tx(tx_hash_lower, path):
        raise PaymentVerificationError("Transaction already used for a previous request.")

    def _verify_on_chain() -> None:
        """Synchronous Web3 verification, run in a thread."""
        w3 = _get_web3()

        # Fetch receipt
        try:
            receipt = w3.eth.get_transaction_receipt(tx_hash)  # type: ignore[arg-type]
        except TransactionNotFound:
            raise PaymentVerificationError("Transaction not found on Base Sepolia.")

        if receipt is None:
            raise PaymentVerificationError("Transaction not found on Base Sepolia.")

        # Verify transaction succeeded (status=1). A reverted tx (status=0) must be rejected.
        if receipt.get("status") != 1:
            raise PaymentVerificationError("Transaction reverted on-chain.")

        # Confirmation check
        current_block = w3.eth.block_number
        tx_block = receipt["blockNumber"]
        confirmations = current_block - tx_block
        if confirmations < settings.required_confirmations:
            raise PaymentVerificationError(
                f"Transaction has {confirmations} confirmation(s); "
                f"{settings.required_confirmations} required."
            )

        # Parse Transfer events from the USDC contract
        usdc = w3.eth.contract(address=usdc_address, abi=ERC20_TRANSFER_ABI)
        transfer_events = usdc.events.Transfer().process_receipt(receipt, errors="discard")

        paid_amount = 0
        for event in transfer_events:
            to_addr = event["args"]["to"].lower()
            if to_addr == wallet:
                paid_amount += event["args"]["value"]

        if paid_amount < required_amount:
            logger.warning(
                "Insufficient payment for %s: required %d, received %d (tx: %s)",
                path, required_amount, paid_amount, tx_hash,
            )
            raise PaymentVerificationError(
                "Insufficient payment. Check the required amount and retry."
            )

        logger.info("Payment accepted: %s (%.4f USDC) for %s", tx_hash, paid_amount / 1_000_000, path)

    # Run blocking Web3 calls in a thread to avoid blocking the event loop
    await asyncio.to_thread(_verify_on_chain)


async def x402_middleware(request: Request, call_next):
    """
    FastAPI middleware that enforces x402 payment on all /api/fpl/* routes.

    - No X-Payment header -> 402 with payment details
    - X-Payment header present -> verify on-chain -> proceed or 402 error
    """
    path = request.url.path

    if not path.startswith("/api/fpl/"):
        return await call_next(request)

    tx_hash = request.headers.get("X-Payment")

    if not tx_hash:
        return payment_required_response(path)

    try:
        await verify_payment(tx_hash, path)
    except PaymentVerificationError as exc:
        return JSONResponse(
            status_code=402,
            content={
                "x402": True,
                "error": str(exc),
                "payment": {
                    "payee": settings.payment_wallet_address,
                    "amount": ENDPOINT_PRICES.get(path, 1_000),
                    "contract": settings.usdc_contract_address,
                },
            },
        )
    except Exception as exc:
        logger.exception("Unexpected error during payment verification: %s", exc)
        return JSONResponse(
            status_code=402,
            content={
                "x402": True,
                "error": "Payment verification failed. Please retry with a valid transaction hash.",
                "payment": {
                    "payee": settings.payment_wallet_address,
                    "amount": ENDPOINT_PRICES.get(path, 1_000),
                    "contract": settings.usdc_contract_address,
                },
            },
        )

    return await call_next(request)
