"""Playwright-based shopping automation for joy-buy-test.lovable.app."""

from __future__ import annotations

import logging
import os
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

from playwright.async_api import Page, async_playwright

from .keywords import KeywordsClient
from .prompts import PROMPT_IDS
from .tracing import task
from .types import (
    BrowserProfile,
    CartItem,
    CartJson,
    CartTotals,
    PaymentMethod,
    PaymentResult,
    ShoppingItem,
    ShoppingPlan,
)

if TYPE_CHECKING:
    from playwright.async_api import Browser, BrowserContext

logger = logging.getLogger(__name__)

# Default profile directory for persistent browser sessions
DEFAULT_PROFILE_DIR = Path(__file__).parent.parent / "output" / "browser_profile"


class JoyBuyShopper:
    """Autonomous shopper for e-commerce stores.
    
    Default store is joy-buy-test.lovable.app but can be customized via domain parameter.
    
    The store typically has a simple layout:
    - Home page lists all products with "Add" buttons
    - No search functionality
    - Cart accessible via /cart link
    
    Uses a persistent browser profile so PayFill can continue the session.
    """

    DEFAULT_DOMAIN = "https://joy-buy-test.lovable.app"

    def __init__(
        self,
        plan: ShoppingPlan,
        keywords_client: KeywordsClient,
        headless: bool = False,
        domain: str | None = None,
        instructions: str | None = None,
        profile_dir: Path | None = None,
    ):
        self.plan = plan
        self.keywords = keywords_client
        self.headless = headless
        self.base_url = domain.rstrip("/") if domain else self.DEFAULT_DOMAIN
        self.instructions = instructions
        self._profile_dir = profile_dir or DEFAULT_PROFILE_DIR
        self._playwright = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None
        self._added_items: list[CartItem] = []

    @task(name="shopping_browse_and_add")
    async def shop(self, keep_browser_open: bool = True) -> CartJson:
        """
        Execute the shopping plan and return a CartJson.

        This navigates the store, adds items to cart, and extracts the cart state.
        Does NOT submit payment.
        
        If keep_browser_open=True (default), the browser stays open for PayFill
        to connect and continue the session. The CDP URL is included in cart.json.
        """
        # Ensure profile directory exists
        self._profile_dir.mkdir(parents=True, exist_ok=True)
        profile_path = str(self._profile_dir.resolve())
        logger.info(f"Using persistent browser profile: {profile_path}")
        
        self._playwright = await async_playwright().start()
        
        # Launch browser with persistent context for session continuity
        # Use --remote-debugging-port=0 to get auto-assigned port for CDP
        self._context = await self._playwright.chromium.launch_persistent_context(
            user_data_dir=profile_path,
            channel="chrome",  # Use system Chrome, not bundled Chromium
            headless=self.headless,
            viewport={"width": 1280, "height": 800},
            args=[
                "--disable-blink-features=AutomationControlled",
                "--remote-debugging-port=0",  # Auto-assign CDP port
            ],
        )
        self._page = self._context.pages[0] if self._context.pages else await self._context.new_page()

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
            cart = await self._extract_cart_state(profile_path)
            
            # Since we are keeping the browser open in the same process,
            # we don't need to pass CDP URL to another process.
            if not keep_browser_open:
                await self._close_browser()
            
            return cart

        except Exception as e:
            # On error, close browser
            await self._close_browser()
            raise
    
    async def _close_browser(self) -> None:
        """Close the browser and cleanup."""
        if self._page:
            logger.info("Waiting for browser storage to sync...")
            await self._page.wait_for_timeout(2000)
        
        if self._context:
            await self._context.close()
            logger.info("Browser closed.")
        
        if self._playwright:
            await self._playwright.stop()
            self._playwright = None

    @task(name="collect_products_catalog")
    async def _get_available_products(self) -> list[dict]:
        """Extract all available products from the page."""
        # The store shows products in a grid with title, description, price, and Add button
        # We'll extract product cards

        products = []

        # Try to find product cards - they typically have a structure with title, price, and button
        # Looking at the page content, products seem to follow pattern:
        # CATEGORY\nProduct Name\nDescription\n$XX.XX\nAdd

        page_text = await self._get_page_text()

        # Parse products from the page text
        # Pattern: products have category, name, description, price, Add
        lines = page_text.split("\n")

        products = await self._parse_products_from_lines(lines)

        return products

    @task(name="get_page_text")
    async def _get_page_text(self) -> str:
        """Return raw page text for catalog parsing."""
        return await self._page.inner_text("body")

    @task(name="parse_products_from_lines")
    async def _parse_products_from_lines(self, lines: list[str]) -> list[dict]:
        """Parse product entries from raw page lines."""
        products: list[dict] = []
        i = 0
        while i < len(lines):
            line = lines[i].strip()
            # Look for price pattern
            if line.startswith("$"):
                price = line
                if i >= 2:
                    name = lines[i - 2].strip() if i >= 2 else ""
                    description = lines[i - 1].strip() if i >= 1 else ""
                    category = lines[i - 3].strip() if i >= 3 else ""

                    if name and not name.startswith("$"):
                        products.append(
                            {
                                "name": name,
                                "description": description,
                                "price": price,
                                "category": category,
                            }
                        )
            i += 1

        return products

    @task(name="find_product_match")
    async def _add_item_to_cart(self, item: ShoppingItem, products: list[dict]) -> None:
        """Add a single item to the cart by finding the best matching product."""
        logger.info(f"Looking for: {item.description} (quantity: {item.quantity})")

        # Format products for LLM with clear index and structure
        products_text = await self._format_products_text(products)
        
        # Debug: log what products we found
        logger.debug(f"Available products:\n{products_text}")

        # Ask LLM to find the best match using prompt management
        result = await self._run_find_product_prompt(item.description, products_text)

        if not result.get("found", False):
            logger.warning(f"No matching product found for: {item.description}")
            logger.warning(f"Reason: {result.get('reasoning', 'unknown')}")
            return

        product_index, product_name = await self._select_product_match(result, products)
        logger.info(f"Found match at index {product_index}: {product_name}")
        logger.info(f"Reason: {result.get('reasoning', '')}")

        # Click the Add button for this product (respecting quantity)
        await self._add_quantity(product_name, product_index, item.quantity)

    @task(name="format_products_text")
    async def _format_products_text(self, products: list[dict]) -> str:
        """Build LLM-friendly product catalog text."""
        return "\n".join(
            [
                f"{i}. {p['name']} | {p['description']} | {p['price']}"
                for i, p in enumerate(products)
            ]
        )

    @task(name="run_find_product_prompt")
    async def _run_find_product_prompt(self, description: str, products_text: str) -> dict:
        """Call Keywords AI to match a product."""
        return await self.keywords.complete(
            prompt_id=PROMPT_IDS["find_product"],
            variables={
                "products_text": products_text,
                "item_description": description,
            },
            metadata={"stage": "find_product", "item": description},
        )

    @task(name="select_product_match")
    async def _select_product_match(
        self,
        result: dict,
        products: list[dict],
    ) -> tuple[int, str]:
        """Normalize product match output."""
        product_index = result.get("product_index", -1)
        product_name = result.get("product_name", "")

        if 0 <= product_index < len(products):
            actual_product = products[product_index]
            product_name = actual_product["name"]
            logger.info(f"Using product name from index: {product_name}")

        return product_index, product_name

    @task(name="add_item_quantity")
    async def _add_quantity(
        self,
        product_name: str,
        product_index: int,
        quantity: int,
    ) -> None:
        """Add item quantity to cart."""
        for i in range(quantity):
            await self._click_add_for_product(product_name, product_index)
            if quantity > 1:
                logger.info(f"Added {i + 1}/{quantity} of: {product_name}")

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

    @task(name="proceed_to_checkout")
    async def proceed_to_checkout(self) -> bool:
        """Navigate from cart to the checkout/payment page."""
        logger.info("Looking for checkout button...")
        
        # Common checkout button selectors
        selectors = [
            'button:has-text("Proceed to Checkout")',
            'button:has-text("Checkout")',
            'button:has-text("Continue to Checkout")',
            'button:has-text("Go to Checkout")',
            'a:has-text("Proceed to Checkout")',
            'a:has-text("Checkout")',
            '[data-testid="checkout-button"]',
            '[data-testid="proceed-checkout"]',
            '.checkout-button',
            '#checkout-button',
            'a[href*="/checkout"]',
        ]
        
        for selector in selectors:
            try:
                locator = self._page.locator(selector).first
                if await locator.is_visible(timeout=2000):
                    logger.info(f"Found checkout button: {selector}")
                    await locator.click()
                    await self._page.wait_for_load_state("networkidle")
                    await self._page.wait_for_timeout(2000)
                    logger.info(f"Navigated to checkout page: {self._page.url}")
                    return True
            except Exception:
                continue
                
        logger.warning("Could not find checkout button.")
        return False

    @task(name="fill_payment_form")
    async def fill_payment_form(self, card: PaymentMethod) -> bool:
        """Fill out the credit card and contact information form."""
        logger.info("Filling payment and contact form...")
        
        # Define field selector groups
        field_selectors = {
            "pan": [
                'input[name="cardNumber"]',
                'input[name="card-number"]',
                'input[name="cc-number"]',
                'input[id="cardNumber"]',
                'input[id="card-number"]',
                'input[autocomplete="cc-number"]',
                'input[data-testid="card-number"]',
                'input[placeholder*="card number" i]',
                'input[aria-label*="card number" i]',
            ],
            "cvv": [
                'input[name="cvv"]',
                'input[name="cvc"]',
                'input[name="securityCode"]',
                'input[name="cc-csc"]',
                'input[autocomplete="cc-csc"]',
                'input[data-testid="cvv"]',
                'input[placeholder*="CVV" i]',
                'input[placeholder*="CVC" i]',
                'input[placeholder*="security" i]',
            ],
            "name": [
                'input[name="cardholderName"]',
                'input[name="cardholder-name"]',
                'input[name="cc-name"]',
                'input[autocomplete="cc-name"]',
                'input[placeholder*="name on card" i]',
                'input[placeholder*="cardholder" i]',
            ],
            "zip": [
                'input[name="billingZip"]',
                'input[name="postalCode"]',
                'input[name="postal-code"]',
                'input[name="zip"]',
                'input[autocomplete="postal-code"]',
                'input[placeholder*="zip" i]',
                'input[placeholder*="postal" i]',
            ],
            "email": [
                'input[name="email"]',
                'input[type="email"]',
                'input[autocomplete="email"]',
                'input[placeholder*="email" i]',
            ],
            "phone": [
                'input[name="phone"]',
                'input[name="telephone"]',
                'input[name="mobile"]',
                'input[autocomplete="tel"]',
                'input[placeholder*="phone" i]',
            ],
            "firstName": [
                'input[name="firstName"]',
                'input[name="first-name"]',
                'input[autocomplete="given-name"]',
                'input[placeholder*="first name" i]',
            ],
            "lastName": [
                'input[name="lastName"]',
                'input[name="last-name"]',
                'input[autocomplete="family-name"]',
                'input[placeholder*="last name" i]',
            ],
            "address": [
                'input[name="address"]',
                'input[name="street"]',
                'input[name="address1"]',
                'input[autocomplete="address-line1"]',
                'input[placeholder*="address" i]',
            ],
            "city": [
                'input[name="city"]',
                'input[autocomplete="address-level2"]',
                'input[placeholder*="city" i]',
            ],
            "state": [
                'input[name="state"]',
                'input[name="region"]',
                'input[autocomplete="address-level1"]',
                'input[placeholder*="state" i]',
                'select[name="state"]',
            ],
            "country": [
                'input[name="country"]',
                'select[name="country"]',
                'input[autocomplete="country"]',
            ]
        }

        async def fill_field(field_name, selectors, value):
            if not value:
                return False
            for selector in selectors:
                try:
                    locator = self._page.locator(selector).first
                    if await locator.is_visible(timeout=1000):
                        await locator.fill(value)
                        logger.info(f"Filled {field_name}")
                        return True
                except Exception:
                    continue
            return False

        # 1. Fill Contact Info
        if card.email:
            await fill_field("Email", field_selectors["email"], card.email)
        if card.phone:
            await fill_field("Phone", field_selectors["phone"], card.phone)
        
        if card.contactInfo:
            await fill_field("First Name", field_selectors["firstName"], card.contactInfo.firstName)
            await fill_field("Last Name", field_selectors["lastName"], card.contactInfo.lastName)
            await fill_field("Address", field_selectors["address"], card.contactInfo.address)
            await fill_field("City", field_selectors["city"], card.contactInfo.city)
            await fill_field("ZIP Code", field_selectors["zip"], card.contactInfo.zipCode)
        
        # 2. Fill Billing Info (if different or specifically for card)
        if card.billingAddress:
            await fill_field("Billing Street", field_selectors["address"], card.billingAddress.street)
            await fill_field("Billing City", field_selectors["city"], card.billingAddress.city)
            await fill_field("Billing State", field_selectors["state"], card.billingAddress.state)
            await fill_field("Billing ZIP", field_selectors["zip"], card.billingAddress.zip)
            await fill_field("Billing Country", field_selectors["country"], card.billingAddress.country)

        # 3. Fill Card Details
        # Fill PAN
        if not await fill_field("PAN", field_selectors["pan"], card.pan):
            logger.error("Failed to fill card number")
            return False

        # Fill Expiry (handling both combined MM/YY and separate fields)
        expiry_filled = False
        expiry_selectors = [
            'input[name="expiry"]',
            'input[name="cardExpiry"]',
            'input[name="cc-exp"]',
            'input[autocomplete="cc-exp"]',
            'input[placeholder*="MM/YY" i]',
        ]
        
        # Try combined first
        for sel in expiry_selectors:
            try:
                locator = self._page.locator(sel).first
                if await locator.is_visible(timeout=1000):
                    month = card.exp_month.zfill(2)
                    year = card.exp_year[-2:]
                    await locator.fill(f"{month}/{year}")
                    logger.info("Filled combined expiry")
                    expiry_filled = True
                    break
            except Exception:
                continue

        if not expiry_filled:
            # Try separate month/year
            month_sel = ['input[name="expiryMonth"]', 'select[name="expiryMonth"]', 'input[autocomplete="cc-exp-month"]']
            year_sel = ['input[name="expiryYear"]', 'select[name="expiryYear"]', 'input[autocomplete="cc-exp-year"]']
            
            m_filled = await fill_field("exp_month", month_sel, card.exp_month.zfill(2))
            y_filled = await fill_field("exp_year", year_sel, card.exp_year[-2:])
            expiry_filled = m_filled and y_filled

        if not expiry_filled:
            logger.error("Failed to fill expiry date")
            return False

        # Fill CVV
        if not await fill_field("CVV", field_selectors["cvv"], card.cvv):
            logger.error("Failed to fill security code")
            return False

        # Fill Name (optional but recommended)
        await fill_field("Cardholder Name", field_selectors["name"], card.cardholder_name)
        
        # Fill ZIP (fallback)
        if card.billing_zip:
            await fill_field("Billing ZIP", field_selectors["zip"], card.billing_zip)

        return True

    @task(name="complete_purchase")
    async def complete_purchase(self) -> PaymentResult:
        """Submit the payment and capture the result."""
        logger.info("Submitting order...")
        
        submit_selectors = [
            'button[type="submit"]',
            'button:has-text("Pay")',
            'button:has-text("Place Order")',
            'button:has-text("Complete Purchase")',
            'button:has-text("Submit Order")',
            '[data-testid="submit-button"]',
        ]
        
        submit_button = None
        for sel in submit_selectors:
            try:
                locator = self._page.locator(sel).first
                if await locator.is_visible(timeout=2000):
                    submit_button = locator
                    break
            except Exception:
                continue

        if not submit_button:
            return PaymentResult(success=False, error_message="Could not find submit button")

        await submit_button.click()
        logger.info("Clicked submit. Waiting for confirmation...")
        
        # Wait for potential success indicators
        await self._page.wait_for_timeout(5000)
        
        # Capture confirmation info
        page_text = await self._page.inner_text("body")
        current_url = self._page.url
        
        # Simple success detection
        success_keywords = ["thank you", "confirmed", "order #", "receipt", "success"]
        is_success = any(kw in page_text.lower() for kw in success_keywords)
        
        conf_number = None
        if is_success:
            import re
            # Try to find order number pattern
            match = re.search(r"order\s*(?:#|number|id)?[:\s]*([A-Z0-9-]+)", page_text, re.I)
            if match:
                conf_number = match.group(1)
                logger.info(f"Captured confirmation number: {conf_number}")

        return PaymentResult(
            success=is_success,
            confirmation_number=conf_number,
            receipt_url=current_url,
            error_message=None if is_success else "Could not confirm purchase success from page content"
        )

    @task(name="extract_cart_state")
    async def _extract_cart_state(self, profile_path: str) -> CartJson:
        """Extract cart state from the checkout page."""
        # Navigate to cart
        logger.info("Navigating to cart...")
        await self._navigate_to_cart()
        page_text, current_url = await self._get_cart_page_snapshot()

        # Ask LLM to extract cart data using prompt management
        cart_data = await self.keywords.complete(
            prompt_id=PROMPT_IDS["cart_extraction"],
            variables={"page_text": page_text},
            metadata={"stage": "cart_extraction"},
        )

        cart_data = await self._normalize_cart_data(cart_data)

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

        # Create browser profile info for PayFill handover
        browser_profile = BrowserProfile(
            user_data_dir=profile_path,
        )

        cart = CartJson(
            plan_id=self.plan.plan_id,
            merchant_origin=self.base_url,
            checkout_url=current_url,
            items=items,
            totals=totals,
            expires_at=(datetime.utcnow() + timedelta(hours=1)).isoformat(),
            browser_profile=browser_profile,
        )

        # Compute fingerprint
        cart.compute_fingerprint()
        
        logger.info(f"Cart ready for PayFill handover. Profile: {profile_path}")

        return cart

    @task(name="cart_navigation")
    async def _navigate_to_cart(self) -> None:
        """Navigate to cart page with fallbacks."""
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

    @task(name="cart_page_snapshot")
    async def _get_cart_page_snapshot(self) -> tuple[str, str]:
        """Capture cart page text and URL for extraction."""
        page_text = await self._page.inner_text("body")
        page_text = re.sub(r"\s+", " ", page_text).strip()[:3000]
        current_url = self._page.url

        logger.info(f"Cart page URL: {current_url}")
        logger.debug(f"Cart page content: {page_text[:500]}...")

        return page_text, current_url

    @task(name="normalize_cart_data")
    async def _normalize_cart_data(self, cart_data) -> dict:
        """Normalize LLM cart data into dict shape."""
        if isinstance(cart_data, list):
            return {"items": cart_data}
        if cart_data is None:
            return {}
        if not isinstance(cart_data, dict):
            logger.warning(f"Unexpected cart data type: {type(cart_data)}")
            return {}
        return cart_data
