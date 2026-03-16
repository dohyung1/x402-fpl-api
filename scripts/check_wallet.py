"""
Script: check_wallet.py

Checks the USDC balance of your payment wallet on Base Sepolia.
Run after funding with the Coinbase faucet:
  https://faucet.quicknode.com/base/sepolia

Usage:
  uv run python scripts/check_wallet.py
"""

import asyncio
import os
import sys

from dotenv import load_dotenv
from web3 import Web3

load_dotenv()

USDC_ABI = [
    {
        "inputs": [{"name": "account", "type": "address"}],
        "name": "balanceOf",
        "outputs": [{"name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "decimals",
        "outputs": [{"name": "", "type": "uint8"}],
        "stateMutability": "view",
        "type": "function",
    },
]


def main():
    rpc_url = os.getenv("BASE_RPC_URL", "https://sepolia.base.org")
    wallet = os.getenv("PAYMENT_WALLET_ADDRESS", "")
    usdc_address = os.getenv(
        "USDC_CONTRACT_ADDRESS",
        "0x036CbD53842c5426634e7929541eC2318f3dCF7e",
    )

    if not wallet or wallet == "0xYourWalletAddressHere":
        print("❌ PAYMENT_WALLET_ADDRESS not set in .env")
        sys.exit(1)

    w3 = Web3(Web3.HTTPProvider(rpc_url))
    if not w3.is_connected():
        print(f"❌ Cannot connect to {rpc_url}")
        sys.exit(1)

    print(f"✅ Connected to Base via {rpc_url}")
    print(f"   Wallet: {wallet}")

    # ETH balance
    eth_balance = w3.eth.get_balance(Web3.to_checksum_address(wallet))
    print(f"   ETH balance: {w3.from_wei(eth_balance, 'ether'):.6f} ETH")

    # USDC balance
    usdc = w3.eth.contract(
        address=Web3.to_checksum_address(usdc_address),
        abi=USDC_ABI,
    )
    decimals = usdc.functions.decimals().call()
    balance = usdc.functions.balanceOf(Web3.to_checksum_address(wallet)).call()
    print(f"   USDC balance: {balance / (10 ** decimals):.2f} USDC")
    print(f"   (USDC contract: {usdc_address})")


if __name__ == "__main__":
    main()
