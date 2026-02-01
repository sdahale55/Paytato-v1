"""Cart validation against shopping plan using Keywords AI."""

from __future__ import annotations

import json
import logging

from .keywords import KeywordsClient
from .prompts import PROMPT_IDS
from .types import CartJson, ShoppingPlan, ValidationResult

logger = logging.getLogger(__name__)


async def validate_cart(
    plan: ShoppingPlan,
    cart: CartJson,
    keywords_client: KeywordsClient,
) -> ValidationResult:
    """
    Validate a cart against the shopping plan using Keywords AI.

    Args:
        plan: The original shopping plan
        cart: The cart state to validate
        keywords_client: Keywords AI client

    Returns:
        ValidationResult with decision, flags, and reasoning
    """
    # Serialize for the prompt
    plan_json = json.dumps(plan.model_dump(), indent=2)
    cart_json = json.dumps(cart.model_dump(), indent=2)

    # Call Keywords AI with prompt management
    result = await keywords_client.complete(
        prompt_id=PROMPT_IDS["cart_vs_plan_validator"],
        variables={
            "plan_json": plan_json,
            "cart_json": cart_json,
            "merchant_origin": cart.merchant_origin,
            "total_cents": str(cart.totals.total_cents),
        },
        session_id=cart.cart_id,
        metadata={
            "stage": "cart_validation",
            "merchant_origin": cart.merchant_origin,
            "cart_hash": cart.cart_fingerprint_sha256,
            "total_cents": cart.totals.total_cents,
            "plan_id": plan.plan_id,
        },
    )

    # Parse result into ValidationResult
    decision = result.get("decision", "ALLOW_WITH_FLAGS")
    if decision not in ("ALLOW", "ALLOW_WITH_FLAGS", "REJECT"):
        logger.warning(f"Unknown decision: {decision}, defaulting to ALLOW_WITH_FLAGS")
        decision = "ALLOW_WITH_FLAGS"

    validation = ValidationResult(
        decision=decision,
        flags=result.get("flags", []),
        reasoning=result.get("reasoning"),
    )

    logger.info(f"Validation result: {validation.decision}")
    for flag in validation.flags:
        logger.info(f"  Flag: {flag}")

    return validation


def quick_validate(plan: ShoppingPlan, cart: CartJson) -> ValidationResult:
    """
    Quick local validation without LLM call.

    Checks basic rules:
    - Total within budget
    - Item count matches
    - Merchant not blocked

    Returns ALLOW, ALLOW_WITH_FLAGS, or REJECT based on rules.
    """
    flags = []

    # Check total vs budget (using effective max which has a default)
    max_budget = plan.budget.effective_max_total_cents
    if cart.totals.total_cents > max_budget:
        over_percent = (
            (cart.totals.total_cents - max_budget)
            / max_budget
            * 100
        )
        flags.append(f"over_budget_by_{over_percent:.0f}_percent")

    # Check item count
    if len(cart.items) != len(plan.items):
        if len(cart.items) < len(plan.items):
            flags.append("item_missing")
        else:
            flags.append("unexpected_item")

    # Check merchant not blocked
    merchant_domain = cart.merchant_origin.replace("https://", "").replace("http://", "")
    if merchant_domain in plan.merchants.blocklist:
        return ValidationResult(
            decision="REJECT",
            flags=["merchant_blocked"],
            reasoning=f"Merchant {merchant_domain} is in blocklist",
        )

    # Determine decision
    if not flags:
        return ValidationResult(
            decision="ALLOW",
            flags=[],
            reasoning="Cart matches plan within constraints",
        )

    # Check if any flags are critical
    critical_flags = ["over_budget_by_50_percent", "item_missing"]
    has_critical = any(
        any(critical in flag for critical in critical_flags) for flag in flags
    )

    if has_critical:
        return ValidationResult(
            decision="REJECT",
            flags=flags,
            reasoning="Critical validation issues found",
        )

    return ValidationResult(
        decision="ALLOW_WITH_FLAGS",
        flags=flags,
        reasoning="Minor issues found but acceptable for approval",
    )
