"""Playwright-based shopping automation for joy-buy-test.lovable.app."""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from playwright.async_api import Page, async_playwright

from .keywords import KeywordsClient
from .prompts import PROMPT_IDS
from .tracing import task
from .types import CartItem, CartJson, CartTotals, ShoppingItem, ShoppingPlan

if TYPE_CHECKING:
    from playwright.async_api import Browser, BrowserContext

logger = logging.getLogger(__name__)


class JoyBuyShopper:
    """Autonomous shopper for e-commerce stores.
    
    Default store is joy-buy-test.lovable.app but can be customized via domain parameter.
    
    The store typically has a simple layout:
    - Home page lists all products with "Add" buttons
    - No search functionality
    - Cart accessible via /cart link
    """

    DEFAULT_DOMAIN = "https://joy-buy-test.lovable.app"

    def __init__(
        self,
        plan: ShoppingPlan,
        keywords_client: KeywordsClient,
        headless: bool = False,
        domain: str | None = None,
        instructions: str | None = None,
    ):
        self.plan = plan
        self.keywords = keywords_client
        self.headless = headless
        self.base_url = domain.rstrip("/") if domain else self.DEFAULT_DOMAIN
        self.instructions = instructions
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None
        self._added_items: list[CartItem] = []

    @task(name="shopping_browse_and_add")
    async def shop(self) -> CartJson:
        """
        Execute the shopping plan and return a CartJson.

        This navigates the store, adds items to cart, and extracts the cart state.
        Does NOT submit payment.
        """
        async with async_playwright() as p:
            # Launch browser (visible for demo)
            self._browser = await p.chromium.launch(headless=self.headless)
            self._context = await self._browser.new_context(
                viewport={"width": 1280, "height": 800}
            )
            self._page = await self._context.new_page()

            try:
                # Navigate to store
                logger.info(f"Navigating to {self.base_url}")
                await self._page.goto(self.base_url, wait_until="networkidle")
                await self._page.wait_for_timeout(2000)  # Let React hydrate

                # Get all available products on the page
                products = await self._get_available_products()
                logger.info(f"Found {len(products)} products on store")

                # Process each item in the plan
                for item in self.plan.items:
                    await self._add_item_to_cart(item, products)

                # Navigate to cart/checkout and extract state
                cart = await self._extract_cart_state()
                return cart

            finally:
                if self._browser:
                    await self._browser.close()

    async def _get_available_products(self) -> list[dict]:
        """Extract all available products from the page."""
        # The store shows products in a grid with title, description, price, and Add button
        # We'll extract product cards
        
        products = []
        
        # Try to find product cards - they typically have a structure with title, price, and button
        # Looking at the page content, products seem to follow pattern:
        # CATEGORY\nProduct Name\nDescription\n$XX.XX\nAdd
        
        page_text = await self._page.inner_text("body")
        
        # Parse products from the page text
        # Pattern: products have category, name, description, price, Add
        lines = page_text.split("\n")
        
        i = 0
        while i < len(lines):
            line = lines[i].strip()
            # Look for price pattern
            if line.startswith("$"):
                # Found a price, backtrack to find product info
                price = line
                # Product name is typically 2 lines before price
                if i >= 2:
                    name = lines[i-2].strip() if i >= 2 else ""
                    description = lines[i-1].strip() if i >= 1 else ""
                    category = lines[i-3].strip() if i >= 3 else ""
                    
                    if name and not name.startswith("$"):
                        products.append({
                            "name": name,
                            "description": description,
                            "price": price,
                            "category": category,
                        })
            i += 1
        
        return products

    @task(name="find_product_match")
    async def _add_item_to_cart(self, item: ShoppingItem, products: list[dict]) -> None:
        """Add a single item to the cart by finding the best matching product."""
        logger.info(f"Looking for: {item.description} (quantity: {item.quantity})")

        # Format products for LLM with clear index and structure
        products_text = "\n".join([
            f"{i}. {p['name']} | {p['description']} | {p['price']}"
            for i, p in enumerate(products)
        ])
        
        # Debug: log what products we found
        logger.debug(f"Available products:\n{products_text}")

        # Ask LLM to find the best match using prompt management
        result = await self.keywords.complete(
            prompt_id=PROMPT_IDS["find_product"],
            variables={
                "products_text": products_text,
                "item_description": item.description,
            },
            metadata={"stage": "find_product", "item": item.description},
        )

        if not result.get("found", False):
            logger.warning(f"No matching product found for: {item.description}")
            logger.warning(f"Reason: {result.get('reasoning', 'unknown')}")
            return

        product_index = result.get("product_index", -1)
        product_name = result.get("product_name", "")
        logger.info(f"Found match at index {product_index}: {product_name}")
        logger.info(f"Reason: {result.get('reasoning', '')}")

        # Use product name from our parsed list if index is valid
        if 0 <= product_index < len(products):
            actual_product = products[product_index]
            product_name = actual_product["name"]
            logger.info(f"Using product name from index: {product_name}")

        # Click the Add button for this product (respecting quantity)
        for i in range(item.quantity):
            await self._click_add_for_product(product_name, product_index)
            if item.quantity > 1:
                logger.info(f"Added {i + 1}/{item.quantity} of: {product_name}")

    async def _click_add_for_product(self, product_name: str, product_index: int = -1) -> None:
        """Click the Add button next to a specific product."""
        # The store has product cards with Add buttons
        # We need to find the product card containing the product name and click its Add button
        
        try:
            # Strategy 0: Use product index to click nth Add button directly
            if product_index >= 0:
                add_buttons = self._page.locator("button:has-text('Add')")
                count = await add_buttons.count()
                if product_index < count:
                    await add_buttons.nth(product_index).click()
                    logger.info(f"Clicked Add button #{product_index} for: {product_name}")
                    await self._page.wait_for_timeout(1000)
                    return
        except Exception as e:
            logger.debug(f"Strategy 0 (index-based) failed: {e}")
        
        try:
            # Strategy 1: Find the product card by text and click its Add button
            # Locate the product title, then find the nearby Add button
            
            # First, try to find a container with the product name
            product_locator = self._page.locator(f"text={product_name}").first
            
            # Get the parent card element
            # Go up to find the card container, then find the Add button within
            card = product_locator.locator("xpath=ancestor::*[contains(@class, 'card') or contains(@class, 'product') or self::article or self::div[.//button]]").first
            
            # Find Add button in the card
            add_button = card.locator("button:has-text('Add')").first
            
            await add_button.click()
            logger.info(f"Clicked Add for: {product_name}")
            await self._page.wait_for_timeout(1000)
            return
            
        except Exception as e:
            logger.debug(f"Strategy 1 failed: {e}")

        try:
            # Strategy 2: Find product element position and click the nearest Add button
            # This uses bounding box proximity to match product to its button
            
            # Find the element containing the product name
            product_element = await self._page.query_selector(f"text={product_name}")
            if not product_element:
                # Try partial match
                product_element = await self._page.query_selector(f"text=/{product_name[:30]}/i")
            
            if product_element:
                product_box = await product_element.bounding_box()
                
                if product_box:
                    # Find all Add buttons and their positions
                    add_buttons = await self._page.query_selector_all("button")
                    
                    best_button = None
                    best_distance = float("inf")
                    
                    for button in add_buttons:
                        btn_text = await button.inner_text()
                        if btn_text.strip().lower() != "add":
                            continue
                        
                        is_visible = await button.is_visible()
                        if not is_visible:
                            continue
                        
                        box = await button.bounding_box()
                        if not box:
                            continue
                        
                        # Calculate distance between product and button
                        # Prefer buttons that are below or to the right of the product (typical card layout)
                        # and on the same "row" (similar Y position for grid layouts)
                        product_center_y = product_box["y"] + product_box["height"] / 2
                        button_center_y = box["y"] + box["height"] / 2
                        
                        # Check if button is roughly in the same card (within 200px vertically)
                        y_diff = abs(button_center_y - product_center_y)
                        if y_diff > 200:
                            continue
                        
                        # Calculate horizontal distance too
                        product_center_x = product_box["x"] + product_box["width"] / 2
                        button_center_x = box["x"] + box["width"] / 2
                        x_diff = abs(button_center_x - product_center_x)
                        
                        # Prefer buttons close to the product (same card)
                        distance = y_diff + x_diff * 0.5  # Weight vertical proximity more
                        
                        if distance < best_distance:
                            best_distance = distance
                            best_button = button
                    
                    if best_button:
                        await best_button.click()
                        logger.info(f"Clicked Add button for: {product_name}")
                        await self._page.wait_for_timeout(1000)
                        return
                                
        except Exception as e:
            logger.debug(f"Strategy 2 failed: {e}")

        # Strategy 3: No fallback - don't click random buttons
        # This prevents adding wrong items to cart
        logger.warning(f"Could not find Add button for product: {product_name}")

    @task(name="extract_cart_state")
    async def _extract_cart_state(self) -> CartJson:
        """Extract cart state from the checkout page."""
        # Navigate to cart
        logger.info("Navigating to cart...")
        
        try:
            # Try clicking cart link
            await self._page.click('a[href="/cart"]', timeout=3000)
        except Exception:
            try:
                # Fallback to direct navigation
                await self._page.goto(f"{self.base_url}/cart", wait_until="networkidle")
            except Exception:
                logger.warning("Could not navigate to cart")

        await self._page.wait_for_timeout(2000)

        # Get page content
        page_text = await self._page.inner_text("body")
        page_text = re.sub(r"\s+", " ", page_text).strip()[:3000]
        current_url = self._page.url

        logger.info(f"Cart page URL: {current_url}")
        logger.debug(f"Cart page content: {page_text[:500]}...")

        # Ask LLM to extract cart data using prompt management
        cart_data = await self.keywords.complete(
            prompt_id=PROMPT_IDS["cart_extraction"],
            variables={"page_text": page_text},
            metadata={"stage": "cart_extraction"},
        )

        # Normalize cart_data to a dict shape.
        if isinstance(cart_data, list):
            cart_data = {"items": cart_data}
        elif cart_data is None:
            cart_data = {}
        elif not isinstance(cart_data, dict):
            logger.warning(f"Unexpected cart data type: {type(cart_data)}")
            cart_data = {}

        logger.info(f"Extracted cart data: {cart_data}")

        # Build CartJson from extracted data
        items = []
        items_data = cart_data.get("items", [])
        if not isinstance(items_data, list):
            logger.warning("Cart items is not a list, defaulting to empty.")
            items_data = []

        for i, item_data in enumerate(items_data):
            # Try to match with plan items
            plan_item_id = None
            if i < len(self.plan.items):
                plan_item_id = self.plan.items[i].id

            items.append(
                CartItem(
                    title=item_data.get("title", "Unknown Item"),
                    url=current_url,
                    price_cents=item_data.get("price_cents", 0) or 0,
                    quantity=item_data.get("quantity", 1) or 1,
                    plan_item_id=plan_item_id,
                )
            )

        # Handle empty cart or null values
        totals = CartTotals(
            subtotal_cents=cart_data.get("subtotal_cents") or 0,
            tax_cents=cart_data.get("tax_cents"),
            shipping_cents=cart_data.get("shipping_cents"),
            total_cents=cart_data.get("total_cents") or 0,
        )

        cart = CartJson(
            plan_id=self.plan.plan_id,
            merchant_origin=self.base_url,
            checkout_url=current_url,
            items=items,
            totals=totals,
            expires_at=(datetime.utcnow() + timedelta(hours=1)).isoformat(),
        )

        # Compute fingerprint
        cart.compute_fingerprint()

        return cart
