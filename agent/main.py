"""Shopping Agent CLI - Main entry point with Paytato integration."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from .keywords import KeywordsClient
from .paytato import PaytatoClient
from .prompts import PROMPT_IDS
from .shopper import JoyBuyShopper
from .tracing import workflow, task
from .types import AgentOutput, Budget, CartJson, PaymentMethod, PaymentResult, ShoppingPlan
from .validator import validate_cart

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


@task(name="intake_requirements_to_plan")
async def create_shopping_plan(
    requirements: str,
    keywords: KeywordsClient,
) -> ShoppingPlan:
    """Convert natural language requirements into a structured shopping plan."""
    logger.info("Converting requirements to shopping plan...")

    plan_data = await keywords.complete(
        prompt_id=PROMPT_IDS["shopping_intake_to_plan"],
        variables={"user_requirements": requirements},
        metadata={"stage": "intake_plan"},
    )

    # Handle missing or null budget gracefully
    if "budget" not in plan_data or plan_data["budget"] is None:
        plan_data["budget"] = {"max_total_cents": 100000, "currency": "USD"}
    else:
        if plan_data["budget"].get("max_total_cents") is None:
            plan_data["budget"]["max_total_cents"] = 100000

    # Handle missing or null approval rules gracefully
    approval_rules = plan_data.get("approval_rules")
    if not isinstance(approval_rules, dict):
        approval_rules = {}
    if approval_rules.get("auto_approve_under_cents") is None:
        approval_rules["auto_approve_under_cents"] = 0
    if approval_rules.get("require_email_approval") is None:
        approval_rules["require_email_approval"] = True
    if approval_rules.get("notify_on_substitution") is None:
        approval_rules["notify_on_substitution"] = True
    plan_data["approval_rules"] = approval_rules

    plan = ShoppingPlan(**plan_data)
    logger.info(f"Created plan with {len(plan.items)} items")
    budget_display = plan.budget.effective_max_total_cents / 100
    logger.info(f"Budget: ${budget_display:.2f} {plan.budget.currency}")

    return plan


@task(name="save_json_file")
async def save_json_file(path: Path, payload: dict) -> None:
    """Persist structured output to disk."""
    with open(path, "w") as f:
        json.dump(payload, f, indent=2)


@task(name="build_agent_output")
async def build_agent_output(
    plan: ShoppingPlan,
    cart: CartJson,
    validation,
) -> AgentOutput:
    """Build final AgentOutput model."""
    return AgentOutput(
        shopping_plan=plan,
        cart=cart,
        validation=validation,
        success=validation.decision != "REJECT",
    )


@task(name="ensure_output_dir")
async def ensure_output_dir(output_dir: Path) -> None:
    """Ensure output directory exists."""
    output_dir.mkdir(parents=True, exist_ok=True)


@workflow(name="shopping_agent_workflow")
async def run_agent(
    requirements: str,
    output_dir: Path,
    headless: bool = False,
    api_key: str | None = None,
    domain: str | None = None,
    instructions: str | None = None,
    paytato: PaytatoClient | None = None,
    mock_payload: PaymentMethod | None = None,
) -> tuple[AgentOutput, dict | None]:
    """
    Run the shopping agent with the given requirements.

    Args:
        requirements: Natural language shopping requirements
        output_dir: Directory to write output JSON files
        headless: Run browser in headless mode
        api_key: Keywords AI API key (defaults to env var)
        domain: Custom merchant domain URL
        instructions: Custom instructions to guide the agent
        paytato: PaytatoClient instance for payment orchestration

    Returns:
        Tuple of (AgentOutput, intent_result) - intent_result is None if no Paytato client
    """
    # Get API key
    if not api_key:
        api_key = os.getenv("KEYWORDS_API_KEY")
    if not api_key:
        raise ValueError("KEYWORDS_API_KEY not set. Check .env file.")

    await ensure_output_dir(output_dir)

    # Step 0: Start Paytato run if client provided
    if paytato:
        logger.info("=" * 50)
        logger.info("STEP 0: Starting Paytato agent run...")
        logger.info("=" * 50)
        await paytato.start_run(force=True)

    async with KeywordsClient(api_key) as keywords:
        # Step 1: Convert requirements to shopping plan
        logger.info("=" * 50)
        logger.info("STEP 1: Converting requirements to shopping plan...")
        logger.info("=" * 50)

        plan = await create_shopping_plan(requirements, keywords)

        # Save plan
        plan_path = output_dir / "shopping_plan.json"
        await save_json_file(plan_path, plan.model_dump())
        logger.info(f"Saved plan to {plan_path}")

        # Step 2: Shop autonomously
        logger.info("=" * 50)
        logger.info("STEP 2: Shopping autonomously...")
        logger.info("=" * 50)

        shopper = JoyBuyShopper(
            plan, 
            keywords, 
            headless=headless,
            domain=domain,
            instructions=instructions,
        )
        cart = await shopper.shop()

        logger.info(f"Cart total: ${cart.totals.total_cents / 100:.2f}")
        logger.info(f"Items in cart: {len(cart.items)}")

        # Save cart
        cart_path = output_dir / "cart.json"
        await save_json_file(cart_path, cart.model_dump())
        logger.info(f"Saved cart to {cart_path}")

        # Step 3: Validate cart against plan
        logger.info("=" * 50)
        logger.info("STEP 3: Validating cart against plan...")
        logger.info("=" * 50)

        validation = await validate_cart(plan, cart, keywords)
        logger.info(f"Validation decision: {validation.decision}")
        if validation.flags:
            logger.info(f"Flags: {', '.join(validation.flags)}")
        if validation.reasoning:
            logger.info(f"Reasoning: {validation.reasoning}")

        # Save validation
        validation_path = output_dir / "validation.json"
        await save_json_file(validation_path, validation.model_dump())
        logger.info(f"Saved validation to {validation_path}")

        # Build final output
        output = await build_agent_output(plan, cart, validation)

        # Save complete output
        output_path = output_dir / "agent_output.json"
        await save_json_file(output_path, output.model_dump())
        logger.info(f"Saved complete output to {output_path}")

        # Step 4: Submit payment intent to Paytato
        intent_result = None
        if paytato and output.success:
            logger.info("=" * 50)
            logger.info("STEP 4: Submitting payment intent to Paytato...")
            logger.info("=" * 50)
            
            intent_result = await paytato.submit_intent(plan, cart)
            intent_id = str(intent_result.get("intentId", ""))
            
            if not intent_id:
                logger.error("Paytato response missing intentId")
                return output, intent_result

            # Step 5: Wait for user approval
            logger.info("=" * 50)
            logger.info("STEP 5: Polling Paytato for credentials...")
            logger.info("=" * 50)
            
            payment_method = mock_payload
            if not payment_method:
                payment_method = await paytato.wait_for_approval(intent_id)
            else:
                logger.info("Using mock payment payload provided via CLI")
            
            if payment_method:
                logger.info(f"Agent successfully received payment data for: {payment_method.cardholder_name}")
                # Step 6: Execute payment
                logger.info("=" * 50)
                logger.info("STEP 6: Executing payment...")
                logger.info("=" * 50)
                
                try:
                    # 6.1 Proceed to checkout
                    if await shopper.proceed_to_checkout():
                        # 6.2 Fill payment form
                        if await shopper.fill_payment_form(payment_method):
                            # IMPORTANT: Wipe card data from memory after filling
                            payment_method = None
                            
                            logger.info("=" * 50)
                            logger.info("PAUSING 15 SECONDS BEFORE SUBMITTING PAYMENT...")
                            logger.info("=" * 50)
                            await asyncio.sleep(15)
                            
                            # 6.3 Complete purchase
                            payment_result = await shopper.complete_purchase()
                            cart.payment_result = payment_result
                            
                            # Step 7: Report back to Paytato
                            logger.info("=" * 50)
                            logger.info("STEP 7: Reporting payment result to Paytato...")
                            logger.info("=" * 50)
                            
                            metadata = {
                                "success": payment_result.success,
                                "confirmation_number": payment_result.confirmation_number,
                                "receipt_url": payment_result.receipt_url,
                                "error_message": payment_result.error_message,
                            }
                            await paytato.complete_intent(intent_id, metadata=metadata)
                            
                            if payment_result.success:
                                logger.info("Payment completed successfully!")
                            else:
                                logger.error(f"Payment failed: {payment_result.error_message}")
                        else:
                            payment_method = None
                            logger.error("Failed to fill payment form")
                            await paytato.complete_intent(intent_id, metadata={"success": False, "error_message": "Failed to fill payment form"})
                    else:
                        logger.error("Failed to navigate to checkout")
                        await paytato.complete_intent(intent_id, metadata={"success": False, "error_message": "Failed to navigate to checkout"})
                except Exception as e:
                    payment_method = None
                    logger.error(f"Unexpected error during payment: {e}")
                    await paytato.complete_intent(intent_id, metadata={"success": False, "error_message": str(e)})
            else:
                logger.warning("Approval not received or timed out. Shutting down.")
        
        elif paytato and not output.success:
            logger.warning("Skipping Paytato intent submission - validation failed")

        # Ensure browser is closed at the end
        await shopper._close_browser()

        return output, intent_result


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Autonomous shopping agent powered by Keywords AI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m agent --requirements "Buy a wireless mouse under $30"
  python -m agent -r "Buy headphones and a keyboard, budget $150 total" --headless
  python -m agent -r "Get me a USB-C hub from joy-buy-test" -o ./my-output
        """,
    )

    parser.add_argument(
        "-r",
        "--requirements",
        type=str,
        required=True,
        help="Natural language shopping requirements",
    )

    parser.add_argument(
        "-o",
        "--output-dir",
        type=Path,
        default=Path(__file__).parent.parent / "output",
        help="Directory to write output JSON files (default: ./output)",
    )

    parser.add_argument(
        "--headless",
        action="store_true",
        help="Run browser in headless mode (no visible window)",
    )

    parser.add_argument(
        "--api-key",
        type=str,
        default=None,
        help="Keywords AI API key (defaults to KEYWORDS_API_KEY env var)",
    )

    parser.add_argument(
        "--paytato-key",
        type=str,
        default=None,
        help="Paytato API key (defaults to PAYTATO_API_KEY env var)",
    )

    parser.add_argument(
        "--private-key",
        type=str,
        default=None,
        help="PayFill Private Key for decryption (defaults to PAYFILL_PRIVATE_KEY env var)",
    )

    parser.add_argument(
        "--mock-payload",
        type=str,
        default=None,
        help="JSON string or path to JSON file containing mock Paytato credentials for testing",
    )

    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable verbose/debug logging",
    )

    parser.add_argument(
        "-d",
        "--domain",
        type=str,
        default=None,
        help="Custom merchant domain URL (defaults to https://joy-buy-test.lovable.app)",
    )

    parser.add_argument(
        "-i",
        "--instructions",
        type=str,
        default=None,
        help="Custom instructions to guide the shopping agent",
    )

    args = parser.parse_args()

    # Load .env file
    env_path = Path(__file__).parent.parent / ".env"
    if env_path.exists():
        load_dotenv(env_path)
        logger.info(f"Loaded environment from {env_path}")

    # Set log level
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # Print banner
    print()
    print("=" * 60)
    print("  SHOPPING AGENT - Autonomous Shopping with Keywords AI")
    print("=" * 60)
    print()
    print(f"Requirements: {args.requirements}")
    print(f"Output dir:   {args.output_dir}")
    print(f"Headless:     {args.headless}")
    if args.domain:
        print(f"Domain:       {args.domain}")
    if args.instructions:
        print(f"Instructions: {args.instructions}")
    print()

    # Run agent
    async def run_with_paytato() -> tuple[AgentOutput, dict | None]:
        """Run agent with Paytato integration."""
        paytato_key = args.paytato_key or os.getenv("PAYTATO_API_KEY")
        
        # Parse mock payload if provided
        mock_data = None
        if args.mock_payload:
            try:
                if Path(args.mock_payload).exists():
                    with open(args.mock_payload) as f:
                        mock_json = json.load(f)
                else:
                    mock_json = json.loads(args.mock_payload)
                
                # Check if it's the raw Paytato format or our PaymentMethod format
                # If it has 'cardNumber', it's the raw format that needs mapping
                if "cardNumber" in mock_json:
                    from .types import Address, ContactInfo
                    mock_data = PaymentMethod(
                        pan=mock_json.get("cardNumber", ""),
                        exp_month=str(mock_json.get("expiryMonth", "")),
                        exp_year=str(mock_json.get("expiryYear", "")),
                        cvv=mock_json.get("cvv", ""),
                        cardholder_name=mock_json.get("cardholderName", ""),
                        billing_zip=mock_json.get("billingAddress", {}).get("zip") if mock_json.get("billingAddress") else None,
                        billingAddress=Address(**mock_json.get("billingAddress")) if mock_json.get("billingAddress") else None,
                        email=mock_json.get("email"),
                        phone=mock_json.get("phone"),
                        contactInfo=ContactInfo(**mock_json.get("contactInfo")) if mock_json.get("contactInfo") else None,
                    )
                else:
                    mock_data = PaymentMethod(**mock_json)
            except Exception as e:
                logger.error(f"Failed to parse mock payload: {e}")
                sys.exit(1)

        # Set private key in env if provided via CLI
        if args.private_key:
            os.environ["PAYFILL_PRIVATE_KEY"] = args.private_key
            
        if paytato_key:
            async with PaytatoClient(paytato_key) as paytato:
                return await run_agent(
                    requirements=args.requirements,
                    output_dir=args.output_dir,
                    headless=args.headless,
                    api_key=args.api_key,
                    domain=args.domain,
                    instructions=args.instructions,
                    paytato=paytato,
                    mock_payload=mock_data,
                )
        else:
            logger.warning("PAYTATO_API_KEY not set - running without Paytato integration")
            return await run_agent(
                requirements=args.requirements,
                output_dir=args.output_dir,
                headless=args.headless,
                api_key=args.api_key,
                domain=args.domain,
                instructions=args.instructions,
                mock_payload=mock_data,
            )

    try:
        output, intent_result = asyncio.run(run_with_paytato())

        # Print summary
        print()
        print("=" * 60)
        print("  RESULT")
        print("=" * 60)
        print()
        print(f"Success:    {output.success}")
        print(f"Decision:   {output.validation.decision}")
        print(f"Cart total: ${output.cart.totals.total_cents / 100:.2f}")
        print(f"Items:      {len(output.cart.items)}")
        print()
        print("Output files:")
        print(f"  - {args.output_dir}/shopping_plan.json")
        print(f"  - {args.output_dir}/cart.json")
        print(f"  - {args.output_dir}/validation.json")
        print(f"  - {args.output_dir}/agent_output.json")
        
        # Print Paytato intent result
        if intent_result:
            print(f"  - {args.output_dir}/paytato_intent.json")
            print()
            print("=" * 60)
            print("  PAYTATO STATUS")
            print("=" * 60)
            print()
            print(f"Intent ID:  {intent_result.get('intentId')}")
            print(f"Status:     {intent_result.get('status')}")
            
            # Check if payment was executed
            if output.cart.payment_result:
                pr = output.cart.payment_result
                print(f"Payment:    {'SUCCESS' if pr.success else 'FAILED'}")
                if pr.confirmation_number:
                    print(f"Conf #:     {pr.confirmation_number}")
                if pr.error_message:
                    print(f"Error:      {pr.error_message}")
            else:
                print("Payment:    Pending/Not executed (approval timeout or browser closed)")
            
            print()
            print("Agent run complete.")
        else:
            print()
            if not output.success:
                print("Note: Payment intent NOT submitted (validation failed)")
            elif not os.getenv("PAYTATO_API_KEY"):
                print("Note: PAYTATO_API_KEY not set - no intent submitted")
        print()

        if not output.success:
            sys.exit(1)

    except KeyboardInterrupt:
        print("\nAborted by user.")
        sys.exit(130)
    except Exception as e:
        logger.error(f"Agent failed: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
