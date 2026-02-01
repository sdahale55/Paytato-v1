"""Keywords AI REST client for LLM calls with prompt management support."""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class KeywordsClient:
    """Async client for Keywords AI chat completions API with prompt management."""

    BASE_URL = "https://api.keywordsai.co/api/chat/completions"

    def __init__(self, api_key: str):
        self.api_key = api_key
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> "KeywordsClient":
        self._client = httpx.AsyncClient(timeout=60.0)
        return self

    async def __aexit__(self, *args: Any) -> None:
        if self._client:
            await self._client.aclose()

    async def complete(
        self,
        messages: list[dict[str, str]] | None = None,
        *,
        model: str = "gpt-4o",
        prompt_id: str | None = None,
        variables: dict[str, str] | None = None,
        user_id: str | None = None,
        session_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        json_mode: bool = True,
    ) -> dict[str, Any]:
        """
        Call Keywords AI chat completions endpoint.

        Supports two modes:
        1. Prompt Management: Pass prompt_id + variables to use dashboard prompts
        2. Inline Messages: Pass messages directly (legacy mode)

        Args:
            messages: Chat messages (optional if using prompt management)
            model: Model to use (ignored if prompt management with override=True)
            prompt_id: Prompt ID from Keywords AI dashboard
            variables: Variables to fill in prompt template
            user_id: Optional user identifier for tracking
            session_id: Optional session identifier for tracking
            metadata: Optional metadata dict for tracking
            json_mode: Whether to request JSON output

        Returns:
            Parsed JSON response from the model
        """
        if not self._client:
            raise RuntimeError("Client not initialized. Use 'async with' context.")

        # Build request payload
        payload: dict[str, Any] = {}

        # Use prompt management if prompt_id and variables provided
        if prompt_id and variables is not None:
            payload["prompt"] = {
                "prompt_id": prompt_id,
                "variables": variables,
                "override": True,  # Use dashboard config for model/temp
            }
            # Still need a placeholder message for API compatibility
            payload["model"] = model
            payload["messages"] = [{"role": "user", "content": "placeholder"}]
        else:
            # Legacy inline messages mode
            if not messages:
                raise ValueError("Either messages or (prompt_id + variables) must be provided")
            payload["model"] = model
            payload["messages"] = messages

        # Add JSON mode if requested
        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        # Add Keywords AI tracking params
        customer_params: dict[str, Any] = {}
        if user_id:
            customer_params["customer_identifier"] = user_id
        if metadata or session_id:
            customer_params["metadata"] = {
                **(metadata or {}),
                **({"session_id": session_id} if session_id else {}),
            }
        if customer_params:
            payload["customer_params"] = customer_params

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        logger.debug(f"Keywords AI request: {json.dumps(payload, indent=2)}")

        response = await self._client.post(
            self.BASE_URL,
            json=payload,
            headers=headers,
        )

        if response.status_code != 200:
            logger.error(f"Keywords AI error: {response.status_code} - {response.text}")
            raise httpx.HTTPStatusError(
                f"Keywords AI returned {response.status_code}",
                request=response.request,
                response=response,
            )

        result = response.json()
        logger.debug(f"Keywords AI response: {json.dumps(result, indent=2)}")

        # Extract content from response
        content = result.get("choices", [{}])[0].get("message", {}).get("content", "{}")

        # Parse JSON content
        try:
            return json.loads(content)
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON response: {content}")
            raise ValueError(f"Invalid JSON in response: {e}") from e


async def test_keywords_client(api_key: str) -> bool:
    """Test the Keywords AI connection."""
    async with KeywordsClient(api_key) as client:
        try:
            result = await client.complete(
                messages=[
                    {"role": "system", "content": "Respond with JSON: {\"status\": \"ok\"}"},
                    {"role": "user", "content": "ping"},
                ],
                model="gpt-4o-mini",
                prompt_id="connection_test",
            )
            return result.get("status") == "ok"
        except Exception as e:
            logger.error(f"Keywords AI connection test failed: {e}")
            return False
