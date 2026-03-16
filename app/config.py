from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    # Payment
    payment_wallet_address: str = "0x0000000000000000000000000000000000000000"
    base_rpc_url: str = "https://sepolia.base.org"
    usdc_contract_address: str = "0x036CbD53842c5426634e7929541eC2318f3dCF7e"
    required_confirmations: int = 1

    # Set to True to bypass on-chain verification (local dev only)
    test_mode: bool = False

    # Service metadata
    service_name: str = "x402-fpl-api"
    service_description: str = "AI-agent-native Fantasy Premier League intelligence"

    # FPL API
    fpl_base_url: str = "https://fantasy.premierleague.com/api"
    fpl_cache_ttl_seconds: int = 300  # 5 minutes


settings = Settings()

# Endpoint pricing in USDC (6 decimal places = microdollars)
# $0.001 = 1_000 units, $0.002 = 2_000 units, $0.005 = 5_000 units
ENDPOINT_PRICES: dict[str, int] = {
    "/api/fpl/captain-pick":     2_000,   # $0.002
    "/api/fpl/transfer-suggest": 5_000,   # $0.005
    "/api/fpl/differentials":    1_000,   # $0.001
    "/api/fpl/fixture-outlook":  1_000,   # $0.001
    "/api/fpl/price-predictions": 2_000,  # $0.002
    "/api/fpl/live-points":      1_000,   # $0.001
}
