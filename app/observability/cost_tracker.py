"""Cost per run, from token usage and a price table."""

from dataclasses import dataclass

from app.domain.models import Usage

TOKENS_PER_MTOK = 1_000_000


@dataclass(frozen=True)
class ModelPrice:
    input_per_mtok: float
    output_per_mtok: float


# USD per million tokens. Keep in sync with the provider's price list.
PRICES: dict[str, ModelPrice] = {
    "claude-opus-5-5": ModelPrice(4.00, 20.00),
    "claude-sonnet-5-5": ModelPrice(2.00, 10.00),
    "claude-haiku-4-5": ModelPrice(1.00, 5.00),
}


def estimate_cost_usd(model: str, usage: Usage) -> float | None:
    """Cost of one call, or None when the model has no known price (never guess)."""
    price = PRICES.get(model)
    return None if price is None else cost_usd(price, usage)


def cost_usd(price: ModelPrice, usage: Usage) -> float:
    cost = (
        usage.input_tokens * price.input_per_mtok + usage.output_tokens * price.output_per_mtok
    ) / TOKENS_PER_MTOK
    return round(cost, 6)
