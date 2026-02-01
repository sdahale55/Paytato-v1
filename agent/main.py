"""Shopping Agent CLI - Main entry point."""

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
from .prompts import PROMPT_IDS
from .shopper import JoyBuyShopper
from .tracing import workflow, task
from .types import AgentOutput, Budget, ShoppingPlan
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

    plan = ShoppingPlan(**plan_data)
    logger.info(f"Created plan with {len(plan.items)} items")
    budget_display = plan.budget.effective_max_total_cents / 100
    logger.info(f"Budget: ${budget_display:.2f} {plan.budget.currency}")

    return plan


@workflow(name="shopping_agent_workflow")
async def run_agent(
    requirements: str,
    output_dir: Path,
    headless: bool = False,
    api_key: str | None = None,
) -> AgentOutput:
    """
    Run the shopping agent with the given requirements.

    Args:
        requirements: Natural language shopping requirements
        output_dir: Directory to write output JSON files
        headless: Run browser in headless mode
        api_key: Keywords AI API key (defaults to env var)

    Returns:
        AgentOutput with plan, cart, and validation result
    """
    # Get API key
    if not api_key:
        api_key = os.getenv("KEYWORDS_API_KEY")
    if not api_key:
        raise ValueError("KEYWORDS_API_KEY not set. Check .env file.")

    output_dir.mkdir(parents=True, exist_ok=True)

    async with KeywordsClient(api_key) as keywords:
        # Step 1: Convert requirements to shopping plan
        logger.info("=" * 50)
        logger.info("STEP 1: Converting requirements to shopping plan...")
        logger.info("=" * 50)

        plan = await create_shopping_plan(requirements, keywords)

        # Save plan
        plan_path = output_dir / "shopping_plan.json"
        with open(plan_path, "w") as f:
            json.dump(plan.model_dump(), f, indent=2)
        logger.info(f"Saved plan to {plan_path}")

        # Step 2: Shop autonomously
        logger.info("=" * 50)
        logger.info("STEP 2: Shopping autonomously...")
        logger.info("=" * 50)

        shopper = JoyBuyShopper(plan, keywords, headless=headless)
        cart = await shopper.shop()

        logger.info(f"Cart total: ${cart.totals.total_cents / 100:.2f}")
        logger.info(f"Items in cart: {len(cart.items)}")

        # Save cart
        cart_path = output_dir / "cart.json"
        with open(cart_path, "w") as f:
            json.dump(cart.model_dump(), f, indent=2)
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
        with open(validation_path, "w") as f:
            json.dump(validation.model_dump(), f, indent=2)
        logger.info(f"Saved validation to {validation_path}")

        # Build final output
        output = AgentOutput(
            shopping_plan=plan,
            cart=cart,
            validation=validation,
            success=validation.decision != "REJECT",
        )

        # Save complete output
        output_path = output_dir / "agent_output.json"
        with open(output_path, "w") as f:
            json.dump(output.model_dump(), f, indent=2)
        logger.info(f"Saved complete output to {output_path}")

        return output


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
        "-v",
        "--verbose",
        action="store_true",
        help="Enable verbose/debug logging",
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
    print()

    # Run agent
    try:
        output = asyncio.run(
            run_agent(
                requirements=args.requirements,
                output_dir=args.output_dir,
                headless=args.headless,
                api_key=args.api_key,
            )
        )

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
