"""Shopping Agent - Pydantic models for structured data."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field


# --- Shopping Plan (output from intake prompt) ---


class ShoppingItem(BaseModel):
    """A single item in the shopping plan."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    description: str
    quantity: int = 1
    max_price_cents: int | None = None
    preferred_merchants: list[str] = Field(default_factory=list)
    substitution_allowed: bool = True
    substitution_rules: str | None = None
    size: str | None = None
    color: str | None = None
    attributes: dict[str, str] = Field(default_factory=dict)


class Budget(BaseModel):
    """Budget constraints for shopping."""

    max_total_cents: int | None = None  # None means no limit
    max_per_item_cents: int | None = None
    currency: Literal["USD", "EUR", "GBP"] = "USD"

    @property
    def effective_max_total_cents(self) -> int:
        """Return effective max total (default to $1000 if not set)."""
        return self.max_total_cents if self.max_total_cents is not None else 100000


class MerchantRules(BaseModel):
    """Merchant allowlist/blocklist."""

    allowlist: list[str] = Field(default_factory=list)
    blocklist: list[str] = Field(default_factory=list)


class DeliveryPreferences(BaseModel):
    """Delivery preferences."""

    deadline: str | None = None  # ISO 8601 date
    address_id: str | None = None
    notes: str | None = None


class ApprovalRules(BaseModel):
    """Rules for auto-approval vs email approval."""

    auto_approve_under_cents: int = 0
    require_email_approval: bool = True
    notify_on_substitution: bool = True


class ShoppingPlan(BaseModel):
    """Complete shopping plan generated from user requirements."""

    plan_id: str = Field(default_factory=lambda: str(uuid4()))
    user_id: str = "demo-user"
    created_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())

    items: list[ShoppingItem]

    budget: Budget
    merchants: MerchantRules = Field(default_factory=MerchantRules)
    delivery: DeliveryPreferences = Field(default_factory=DeliveryPreferences)
    approval_rules: ApprovalRules = Field(default_factory=ApprovalRules)

    flags: list[str] = Field(default_factory=list)


# --- Cart JSON (output from shopping) ---


class CartItem(BaseModel):
    """A single item in the cart."""

    item_id: str = Field(default_factory=lambda: str(uuid4()))
    plan_item_id: str | None = None  # Links to ShoppingItem.id

    title: str
    url: str
    image_url: str | None = None

    price_cents: int
    quantity: int = 1

    seller: str | None = None
    is_substitution: bool = False
    substitution_reason: str | None = None

    attributes: dict[str, str] = Field(default_factory=dict)


class CartTotals(BaseModel):
    """Cart totals breakdown."""

    subtotal_cents: int
    tax_cents: int | None = None
    shipping_cents: int | None = None
    total_cents: int
    currency: Literal["USD", "EUR", "GBP"] = "USD"


class CartJson(BaseModel):
    """Complete cart state ready for checkout."""

    cart_id: str = Field(default_factory=lambda: str(uuid4()))
    plan_id: str

    merchant_origin: str
    checkout_url: str

    items: list[CartItem]
    totals: CartTotals

    cart_fingerprint_sha256: str = ""
    created_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    expires_at: str = ""

    def compute_fingerprint(self) -> str:
        """Compute SHA256 fingerprint of cart contents."""
        canonical = json.dumps(
            {
                "merchant_origin": self.merchant_origin,
                "items": [
                    {
                        "title": item.title,
                        "price_cents": item.price_cents,
                        "quantity": item.quantity,
                    }
                    for item in self.items
                ],
                "total_cents": self.totals.total_cents,
            },
            sort_keys=True,
        )
        self.cart_fingerprint_sha256 = hashlib.sha256(canonical.encode()).hexdigest()
        return self.cart_fingerprint_sha256


# --- Validation Result ---


class ValidationResult(BaseModel):
    """Result of validating cart against shopping plan."""

    decision: Literal["ALLOW", "ALLOW_WITH_FLAGS", "REJECT"]
    flags: list[str] = Field(default_factory=list)
    reasoning: str | None = None


# --- Agent Output (final output combining everything) ---


class AgentOutput(BaseModel):
    """Complete output from the shopping agent."""

    shopping_plan: ShoppingPlan
    cart: CartJson
    validation: ValidationResult
    success: bool = True
    error: str | None = None
