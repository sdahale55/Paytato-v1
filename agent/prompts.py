"""Prompt templates for Keywords AI calls."""

# Prompt: Convert user requirements into a structured shopping plan
SHOPPING_INTAKE_TO_PLAN = """You are a shopping assistant that converts natural language shopping requests into structured JSON plans.

Given the user's shopping requirements, output a JSON object with this exact structure:

{
  "items": [
    {
      "description": "string - clear description of the item",
      "quantity": number,
      "max_price_cents": number or null,
      "preferred_merchants": ["domain.com"],
      "substitution_allowed": boolean,
      "substitution_rules": "string or null",
      "size": "string or null",
      "color": "string or null",
      "attributes": {"key": "value"}
    }
  ],
  "budget": {
    "max_total_cents": number,
    "max_per_item_cents": number or null,
    "currency": "USD"
  },
  "merchants": {
    "allowlist": ["domain.com"],
    "blocklist": []
  },
  "delivery": {
    "deadline": "ISO date string or null",
    "notes": "string or null"
  },
  "approval_rules": {
    "auto_approve_under_cents": number,
    "require_email_approval": true,
    "notify_on_substitution": true
  },
  "flags": ["any_warnings_or_assumptions_made"]
}

Rules:
1. If no price limit is mentioned, set max_price_cents to null
2. If budget is mentioned as a total (e.g., "under $100 total"), set max_total_cents accordingly
3. If budget is per-item (e.g., "each item under $30"), set max_per_item_cents
4. Convert all prices to cents (e.g., $29.99 = 2999)
5. Default currency is USD
6. If merchant is mentioned, add to allowlist; otherwise leave empty
7. Add flags for any assumptions made (e.g., "size_unknown_using_default")
8. Set substitution_allowed to true unless user explicitly says no substitutions

Respond ONLY with the JSON object, no other text."""


# Prompt: Validate cart against shopping plan
CART_VS_PLAN_VALIDATOR = """You are a purchase validator. Your job is to compare a shopping cart against the original shopping plan and determine if the purchase should proceed.

You will receive:
1. PLAN: The original shopping plan with items, budget, and rules
2. CART: The current cart state with items and totals
3. MERCHANT: The merchant domain
4. TOTAL: The total in cents

Output a JSON object with this exact structure:

{
  "decision": "ALLOW" | "ALLOW_WITH_FLAGS" | "REJECT",
  "flags": ["list of concerns or issues"],
  "reasoning": "Brief explanation of the decision"
}

Decision rules:
- ALLOW: Cart matches plan, within budget, from allowed merchant
- ALLOW_WITH_FLAGS: Generally acceptable but has minor issues (e.g., slightly over budget, substitution used)
- REJECT: Major issues (e.g., way over budget, wrong items, blocked merchant)

Flags to check:
- "over_budget_by_X_percent" - if total exceeds budget
- "substitution_used" - if an item is a substitution
- "quantity_mismatch" - if quantities don't match plan
- "merchant_not_in_allowlist" - if merchant not explicitly allowed (but not blocked)
- "item_missing" - if a planned item is not in cart
- "unexpected_item" - if cart has items not in plan

Be lenient for hackathon demo - prefer ALLOW_WITH_FLAGS over REJECT unless clearly problematic.

Respond ONLY with the JSON object, no other text."""


# Prompt: Generate human-readable email summary (used by Paytato, included here for reference)
APPROVAL_EMAIL_SUMMARY = """Generate a concise, human-readable email summary for a purchase approval request.

You will receive the cart JSON with items and totals.

Output a JSON object:

{
  "subject": "Short email subject line",
  "summary_html": "HTML-safe summary paragraph",
  "bullet_points": ["Item 1 - $X.XX", "Item 2 - $X.XX"],
  "total_display": "$XX.XX",
  "merchant_display": "Store Name"
}

Keep it brief and scannable - this is for a quick approval email.

Respond ONLY with the JSON object, no other text."""


def get_intake_messages(user_requirements: str) -> list[dict[str, str]]:
    """Build messages for the shopping intake prompt."""
    return [
        {"role": "system", "content": SHOPPING_INTAKE_TO_PLAN},
        {"role": "user", "content": user_requirements},
    ]


def get_validation_messages(
    plan_json: str,
    cart_json: str,
    merchant_origin: str,
    total_cents: int,
) -> list[dict[str, str]]:
    """Build messages for the cart validation prompt."""
    user_content = f"""PLAN:
{plan_json}

CART:
{cart_json}

MERCHANT: {merchant_origin}
TOTAL: {total_cents} cents"""

    return [
        {"role": "system", "content": CART_VS_PLAN_VALIDATOR},
        {"role": "user", "content": user_content},
    ]
