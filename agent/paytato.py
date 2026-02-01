"""Paytato API client for payment orchestration."""

from __future__ import annotations

import logging
import os
from typing import Any
from uuid import uuid4

import httpx

from .types import CartJson, ShoppingPlan

logger = logging.getLogger(__name__)


class PaytatoClient:
    """Async client for Paytato Agent API."""

    BASE_URL = "https://fortunate-tern-109.convex.site/api/v1"

    def __init__(self, api_key: str | None = None):
        """Initialize Paytato client.
        
        Args:
            api_key: Paytato API key (starts with ptk_). 
                     Defaults to PAYTATO_API_KEY env var.
        """
        self.api_key = api_key or os.getenv("PAYTATO_API_KEY")
        if not self.api_key:
            raise ValueError("PAYTATO_API_KEY not set. Check .env file.")
        
        self._client: httpx.AsyncClient | None = None
        self._run_id: str | None = None

    async def __aenter__(self) -> "PaytatoClient":
        self._client = httpx.AsyncClient(timeout=30.0)
        return self

    async def __aexit__(self, *args: Any) -> None:
        if self._client:
            await self._client.aclose()

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    async def start_run(self, run_id: str | None = None, force: bool = False) -> dict[str, Any]:
        """Start a shopping session (agent run).
        
        Args:
            run_id: Custom run identifier (auto-generated if not provided)
            force: If True, abandons any existing active run
            
        Returns:
            Response with runId, status, startedAt
        """
        if not self._client:
            raise RuntimeError("Client not initialized. Use 'async with' context.")

        payload: dict[str, Any] = {"force": force}
        if run_id:
            payload["run_id"] = run_id

        logger.info("Starting Paytato agent run...")
        
        response = await self._client.post(
            f"{self.BASE_URL}/agent-runs/start",
            json=payload,
            headers=self._headers(),
        )

        if response.status_code != 200:
            logger.error(f"Paytato start run failed: {response.status_code} - {response.text}")
            raise httpx.HTTPStatusError(
                f"Paytato returned {response.status_code}: {response.text}",
                request=response.request,
                response=response,
            )

        result = response.json()
        self._run_id = result.get("runId")
        logger.info(f"Paytato run started: {self._run_id} (status: {result.get('status')})")
        
        return result

    async def submit_intent(
        self,
        plan: ShoppingPlan,
        cart: CartJson,
        intent_id: str | None = None,
    ) -> dict[str, Any]:
        """Submit a payment intent for approval.
        
        Args:
            plan: The original shopping plan (for context)
            cart: The cart with items and totals
            intent_id: Custom intent ID (auto-generated if not provided)
            
        Returns:
            Response with intentId, status, isDuplicate
        """
        if not self._client:
            raise RuntimeError("Client not initialized. Use 'async with' context.")

        # Generate intent_id if not provided
        if not intent_id:
            intent_id = f"intent_{uuid4().hex[:16]}"

        # Build items array from cart
        items = []
        for item in cart.items:
            items.append({
                "name": item.title,
                "qty": item.quantity,
                "unit_price_cents": item.price_cents,
                "currency": cart.totals.currency,
                "sku": item.item_id,
            })

        # Extract merchant info from cart
        merchant_domain = cart.merchant_origin.replace("https://", "").replace("http://", "")
        
        # Build the intent payload
        payload: dict[str, Any] = {
            "intent_id": intent_id,
            "items": items,
            "total_amount_cents": cart.totals.total_cents,
            "currency": cart.totals.currency,
            "payment_link": cart.checkout_url,
            "payment_link_type": "checkout",
            "merchant": {
                "name": merchant_domain,
                "domain": merchant_domain,
            },
        }

        # Add run_id if we have one
        if self._run_id:
            payload["run_id"] = self._run_id

        # Add constraints from budget
        if plan.budget.max_total_cents:
            payload["constraints"] = {
                "max_amount_cents": plan.budget.max_total_cents,
                "must_match_currency": True,
            }

        logger.info(f"Submitting Paytato intent: {intent_id}")
        logger.info(f"  Items: {len(items)}")
        logger.info(f"  Total: ${cart.totals.total_cents / 100:.2f} {cart.totals.currency}")
        logger.info(f"  Merchant: {merchant_domain}")

        response = await self._client.post(
            f"{self.BASE_URL}/intents",
            json=payload,
            headers=self._headers(),
        )

        if response.status_code != 200:
            logger.error(f"Paytato submit intent failed: {response.status_code} - {response.text}")
            raise httpx.HTTPStatusError(
                f"Paytato returned {response.status_code}: {response.text}",
                request=response.request,
                response=response,
            )

        result = response.json()
        logger.info(f"Paytato intent submitted: {result.get('intentId')} (status: {result.get('status')})")
        
        return result

    async def get_intent_status(self, intent_id: str) -> dict[str, Any]:
        """Check the status of a payment intent.
        
        Args:
            intent_id: The Paytato intent ID
            
        Returns:
            Intent details including status
        """
        if not self._client:
            raise RuntimeError("Client not initialized. Use 'async with' context.")

        response = await self._client.get(
            f"{self.BASE_URL}/intents/{intent_id}",
            headers=self._headers(),
        )

        if response.status_code != 200:
            logger.error(f"Paytato get intent failed: {response.status_code} - {response.text}")
            raise httpx.HTTPStatusError(
                f"Paytato returned {response.status_code}: {response.text}",
                request=response.request,
                response=response,
            )

        return response.json()

    async def complete_intent(
        self,
        intent_id: str,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Acknowledge that payment was completed.
        
        Args:
            intent_id: The Paytato intent ID
            metadata: Optional metadata about the payment
            
        Returns:
            Completion acknowledgment
        """
        if not self._client:
            raise RuntimeError("Client not initialized. Use 'async with' context.")

        payload: dict[str, Any] = {}
        if metadata:
            payload["metadata"] = metadata

        response = await self._client.post(
            f"{self.BASE_URL}/intents/{intent_id}/complete",
            json=payload,
            headers=self._headers(),
        )

        if response.status_code != 200:
            logger.error(f"Paytato complete intent failed: {response.status_code} - {response.text}")
            raise httpx.HTTPStatusError(
                f"Paytato returned {response.status_code}: {response.text}",
                request=response.request,
                response=response,
            )

        result = response.json()
        logger.info(f"Paytato intent completed: {result.get('status')}")
        
        return result

    @property
    def run_id(self) -> str | None:
        """Get the current run ID."""
        return self._run_id
