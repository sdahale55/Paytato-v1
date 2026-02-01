"""Cart validation against shopping plan using Keywords AI."""

from __future__ import annotations

import json
import logging

from .keywords import KeywordsClient
from .prompts import PROMPT_IDS
from .tracing import task
from .types import CartJson, ShoppingPlan, ValidationResult

logger = logging.getLogger(__name__)


@task(name="validate_cart_against_plan")
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
    plan_json, cart_json = await _serialize_plan_cart(plan, cart)

    # Call Keywords AI with prompt management
    prompt_vars = await _build_validation_variables(plan_json, cart_json, cart)
    prompt_meta = await _build_validation_metadata(plan, cart)

    result = await keywords_client.complete(
        prompt_id=PROMPT_IDS["cart_vs_plan_validator"],
        variables=prompt_vars,
        session_id=cart.cart_id,
        metadata=prompt_meta,
    )

    # Parse result into ValidationResult
    validation = await _parse_validation_result(result)

    logger.info(f"Validation result: {validation.decision}")
    for flag in validation.flags:
        logger.info(f"  Flag: {flag}")

    return validation


@task(name="serialize_plan_cart")
async def _serialize_plan_cart(
    plan: ShoppingPlan,
    cart: CartJson,
) -> tuple[str, str]:
    """Serialize plan and cart to JSON strings."""
    plan_json = json.dumps(plan.model_dump(), indent=2)
    cart_json = json.dumps(cart.model_dump(), indent=2)
    return plan_json, cart_json


@task(name="build_validation_variables")
async def _build_validation_variables(
    plan_json: str,
    cart_json: str,
    cart: CartJson,
) -> dict:
    """Build prompt variables for validation."""
    return {
        "plan_json": plan_json,
        "cart_json": cart_json,
        "merchant_origin": cart.merchant_origin,
        "total_cents": str(cart.totals.total_cents),
    }


@task(name="build_validation_metadata")
async def _build_validation_metadata(
    plan: ShoppingPlan,
    cart: CartJson,
) -> dict:
    """Build metadata for validation tracing."""
    return {
        "stage": "cart_validation",
        "merchant_origin": cart.merchant_origin,
        "cart_hash": cart.cart_fingerprint_sha256,
        "total_cents": cart.totals.total_cents,
        "plan_id": plan.plan_id,
    }


@task(name="parse_validation_result")
async def _parse_validation_result(result) -> ValidationResult:
    """Normalize validation result payload."""
    if result is None or not isinstance(result, dict):
        logger.warning("Validation result is not a dict, defaulting to ALLOW_WITH_FLAGS")
        result = {}

    decision = result.get("decision", "ALLOW_WITH_FLAGS")
    if decision not in ("ALLOW", "ALLOW_WITH_FLAGS", "REJECT"):
        logger.warning(f"Unknown decision: {decision}, defaulting to ALLOW_WITH_FLAGS")
        decision = "ALLOW_WITH_FLAGS"

    return ValidationResult(
        decision=decision,
        flags=result.get("flags", []),
        reasoning=result.get("reasoning"),
    )


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
