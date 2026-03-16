"""
x402 FPL Intelligence API

Agent-native FPL intelligence. Pay per query with USDC on Base.
No API keys. No signups. No subscriptions.
"""

import logging

from fastapi import FastAPI, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import ENDPOINT_PRICES, settings
from app.x402 import x402_middleware

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

app = FastAPI(
    title="x402 FPL Intelligence API",
    description=(
        "AI-agent-native Fantasy Premier League intelligence. Pay per query with USDC on Base via the x402 protocol."
    ),
    version="1.0.0",
    docs_url="/docs",
    redoc_url=None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["GET"],
    allow_headers=["X-Payment"],
)

# Register x402 payment middleware
app.middleware("http")(x402_middleware)


# ---------------------------------------------------------------------------
# Health / Discovery
# ---------------------------------------------------------------------------


@app.get("/", include_in_schema=False)
async def root():
    return {
        "service": settings.service_name,
        "description": settings.service_description,
        "protocol": "x402",
        "network": "base-sepolia",
        "payee": settings.payment_wallet_address,
        "endpoints": [
            {
                "path": path,
                "price_usdc_units": price,
                "price_display": f"${price / 1_000_000:.4f}",
            }
            for path, price in ENDPOINT_PRICES.items()
        ],
    }


@app.get("/health")
async def health():
    return {"status": "ok", "service": settings.service_name}


# ---------------------------------------------------------------------------
# Paid endpoints — all behind x402 middleware
# ---------------------------------------------------------------------------


@app.get("/api/fpl/captain-pick")
async def captain_pick(
    gameweek: int | None = Query(None, ge=1, le=38, description="Gameweek number 1-38 (defaults to current)"),
):
    """
    Top 5 captain recommendations for the given gameweek.

    Scored by: form, points per game, home advantage, fixture difficulty, ICT index, bonus rate.
    """
    from app.algorithms.captain import get_captain_picks

    return await get_captain_picks(gameweek=gameweek)


@app.get("/api/fpl/differentials")
async def differentials(
    max_ownership: float = Query(10.0, ge=0.1, le=100, description="Max ownership % threshold (0.1-100)"),
    gameweek: int | None = Query(None, ge=1, le=38, description="Gameweek number 1-38 (defaults to current)"),
):
    """
    Underowned players outperforming their ownership %.

    Great for competitive edge — find the players others haven't.
    """
    from app.algorithms.differentials import get_differentials

    return await get_differentials(max_ownership_pct=max_ownership, gameweek=gameweek)


@app.get("/api/fpl/fixture-outlook")
async def fixture_outlook(
    gameweeks_ahead: int = Query(5, ge=1, le=10, description="Number of GWs to look ahead"),
    position: str | None = Query(None, description="Filter by position: GKP, DEF, MID, FWD"),
):
    """
    Teams ranked by upcoming fixture difficulty + best players to target.
    """
    from app.algorithms.fixtures import get_fixture_outlook

    return await get_fixture_outlook(gameweeks_ahead=gameweeks_ahead, position=position)


@app.get("/api/fpl/price-predictions")
async def price_predictions():
    """
    Players likely to rise or fall in price tonight.

    Based on net transfer volume trends relative to price change thresholds.
    """
    from app.algorithms.prices import get_price_predictions

    return await get_price_predictions()


@app.get("/api/fpl/transfer-suggest")
async def transfer_suggest(
    team_id: int = Query(..., ge=1, le=20_000_000, description="FPL team ID"),
    free_transfers: int = Query(1, ge=1, le=2, description="Free transfers available"),
    bank: float = Query(0.0, ge=0, le=200, description="Bank balance in millions (e.g. 1.5)"),
):
    """
    Recommended transfers in/out for a given FPL team.
    """
    from app.algorithms.transfers import get_transfer_suggestions

    return await get_transfer_suggestions(
        team_id=team_id,
        free_transfers=free_transfers,
        bank_m=bank,
    )


@app.get("/api/fpl/live-points")
async def live_points(team_id: int = Query(..., ge=1, le=20_000_000, description="FPL team ID")):
    """
    Live score, projected bonus, auto-sub scenarios, rank estimate.
    """
    from app.algorithms.live import get_live_points

    return await get_live_points(team_id=team_id)


# ---------------------------------------------------------------------------
# Error handlers
# ---------------------------------------------------------------------------


@app.exception_handler(Exception)
async def generic_error_handler(request: Request, exc: Exception):
    logging.getLogger(__name__).exception("Unhandled error: %s", exc)
    return JSONResponse(status_code=500, content={"error": "Internal server error"})
