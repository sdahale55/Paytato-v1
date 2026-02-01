# Shopping Agent

Autonomous shopping agent powered by Keywords AI for the Paytato workflow.

## Quick Start

```bash
# Create virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -e .

# Install Playwright browsers
playwright install chromium

# Run agent
python -m agent --requirements "Buy a wireless mouse under $30"
```

## Usage

```bash
# Basic usage
python -m agent -r "Buy headphones and a keyboard, budget $150 total"

# Run headless (no visible browser)
python -m agent -r "Get me a USB-C hub" --headless

# Custom output directory
python -m agent -r "Buy a gaming mouse" -o ./my-output

# Verbose logging
python -m agent -r "Buy a webcam" -v
```

## Output Files

After running, the agent produces:

- `output/shopping_plan.json` - Structured plan from user requirements
- `output/cart.json` - Cart state ready for Paytato approval
- `output/validation.json` - Validation result (ALLOW/REJECT)
- `output/agent_output.json` - Complete output with all data

## Environment Variables

Copy `.env.example` to `.env` and set:

```
KEYWORDS_API_KEY=your_keywords_api_key_here
MERCHANT_URL=https://joy-buy-test.lovable.app
```

## Architecture

1. **Intake**: User requirements → Keywords AI → `ShoppingPlan` JSON
2. **Shopping**: Playwright navigates store, adds items to cart
3. **Extraction**: Cart state extracted into `CartJson`
4. **Validation**: Keywords AI validates cart against plan
5. **Output**: JSON files ready for Paytato approval workflow
