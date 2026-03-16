"""
x402 Payment Protocol implementation.

Flow:
  1. Agent hits endpoint with no auth → server returns 402 + payment details
  2. Agent pays USDC on Base → gets tx hash
  3. Agent retries with X-Payment: <tx_hash> header
  4. We verify the tx on-chain → serve the response

Replay protection: used tx hashes stored in memory (reset on restart).
Upgrade to Redis/DB in Phase 5 for persistence.
"""

import logging
from functools import lru_cache

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

# In-memory replay protection — tx hashes that have already been spent
_used_tx_hashes: set[str] = set()


@lru_cache(maxsize=1)
def _get_web3() -> Web3:
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


def verify_payment(tx_hash: str, path: str) -> None:
    """
    Verify that tx_hash is a valid USDC payment to our wallet for the correct amount.

    Raises PaymentVerificationError with a human-readable message on failure.
    """
    if settings.test_mode:
        logger.info("TEST_MODE: skipping on-chain verification for %s (tx: %s)", path, tx_hash)
        if tx_hash.lower() in _used_tx_hashes:
            raise PaymentVerificationError("Transaction already used for a previous request.")
        _used_tx_hashes.add(tx_hash.lower())
        return

    required_amount = ENDPOINT_PRICES.get(path, 1_000)
    wallet = settings.payment_wallet_address.lower()
    usdc_address = Web3.to_checksum_address(settings.usdc_contract_address)

    # Normalise hash
    if not tx_hash.startswith("0x"):
        tx_hash = "0x" + tx_hash
    tx_hash_lower = tx_hash.lower()

    # Replay protection
    if tx_hash_lower in _used_tx_hashes:
        raise PaymentVerificationError("Transaction already used for a previous request.")

    w3 = _get_web3()

    # Fetch receipt
    try:
        receipt = w3.eth.get_transaction_receipt(tx_hash)  # type: ignore[arg-type]
    except TransactionNotFound:
        raise PaymentVerificationError("Transaction not found on Base Sepolia.")

    if receipt is None:
        raise PaymentVerificationError("Transaction not found on Base Sepolia.")

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
        raise PaymentVerificationError(
            f"Insufficient payment. Required {required_amount} USDC units "
            f"(${required_amount / 1_000_000:.4f}), received {paid_amount}."
        )

    # Mark as used
    _used_tx_hashes.add(tx_hash_lower)
    logger.info("Payment accepted: %s (%.4f USDC) for %s", tx_hash, paid_amount / 1_000_000, path)


async def x402_middleware(request: Request, call_next):
    """
    FastAPI middleware that enforces x402 payment on all /api/fpl/* routes.

    - No X-Payment header → 402 with payment details
    - X-Payment header present → verify on-chain → proceed or 402 error
    """
    path = request.url.path

    if not path.startswith("/api/fpl/"):
        return await call_next(request)

    tx_hash = request.headers.get("X-Payment")

    if not tx_hash:
        return payment_required_response(path)

    try:
        verify_payment(tx_hash, path)
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
