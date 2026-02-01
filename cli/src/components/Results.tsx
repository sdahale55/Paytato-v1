import React from 'react';
import { Box, Text, useInput } from 'ink';

export interface CartItem {
  title: string;
  price_cents: number;
  quantity: number;
}

export interface CartTotals {
  subtotal_cents: number;
  tax_cents?: number;
  shipping_cents?: number;
  total_cents: number;
}

export interface ValidationResult {
  decision: 'ACCEPT' | 'REJECT' | 'NEEDS_REVIEW';
  flags: string[];
  reasoning: string;
}

export interface AgentOutput {
  success: boolean;
  shopping_plan: {
    items: Array<{ description: string; quantity: number }>;
    budget: { max_total_cents: number; currency: string };
  };
  cart: {
    items: CartItem[];
    totals: CartTotals;
    payment_result?: {
      success: boolean;
      confirmation_number?: string;
      receipt_url?: string;
      error_message?: string;
    };
  };
  validation: ValidationResult;
}

interface ResultsProps {
  output: AgentOutput;
  onRestart: () => void;
}

function formatCents(cents: number): string {
  return `$${(cents / 100).toFixed(2)}`;
}

function DecisionBadge({ decision }: { decision: string }) {
  const color = decision === 'ACCEPT' ? 'green' : decision === 'REJECT' ? 'red' : 'yellow';
  return (
    <Text color={color} bold>
      [{decision}]
    </Text>
  );
}

export function Results({ output, onRestart }: ResultsProps) {
  useInput((input, key) => {
    if (input === 'r' || input === 'R') {
      onRestart();
    }
  });

  const { cart, validation, shopping_plan } = output;

  return (
    <Box flexDirection="column" gap={1}>
      {/* Header */}
      <Box>
        <Text bold color={output.success ? 'green' : 'red'}>
          {output.success ? 'Shopping Complete!' : 'Shopping Failed'}
        </Text>
        <Text> </Text>
        <DecisionBadge decision={validation.decision} />
      </Box>

      {/* Shopping Plan Summary */}
      <Box marginLeft={2} flexDirection="column">
        <Text bold underline>Requested Items:</Text>
        {shopping_plan.items.map((item, i) => (
          <Text key={i} dimColor>
            - {item.quantity}x {item.description}
          </Text>
        ))}
        {shopping_plan.budget && (
          <Text dimColor>
            Budget: {formatCents(shopping_plan.budget.max_total_cents)} {shopping_plan.budget.currency}
          </Text>
        )}
      </Box>

      {/* Cart Items */}
      <Box marginLeft={2} flexDirection="column">
        <Text bold underline>Cart Contents:</Text>
        {cart.items.length === 0 ? (
          <Text dimColor>No items in cart</Text>
        ) : (
          cart.items.map((item, i) => (
            <Box key={i}>
              <Text>
                {item.quantity}x {item.title}
              </Text>
              <Text dimColor> - {formatCents(item.price_cents)}</Text>
            </Box>
          ))
        )}
      </Box>

      {/* Totals */}
      <Box marginLeft={2} flexDirection="column">
        <Text bold underline>Totals:</Text>
        <Box flexDirection="column" marginLeft={2}>
          <Text>Subtotal: {formatCents(cart.totals.subtotal_cents)}</Text>
          {cart.totals.tax_cents !== undefined && cart.totals.tax_cents !== null && (
            <Text>Tax: {formatCents(cart.totals.tax_cents)}</Text>
          )}
          {cart.totals.shipping_cents !== undefined && cart.totals.shipping_cents !== null && (
            <Text>Shipping: {formatCents(cart.totals.shipping_cents)}</Text>
          )}
          <Text bold color="cyan">
            Total: {formatCents(cart.totals.total_cents)}
          </Text>
        </Box>
      </Box>

      {/* Payment Result */}
      {cart.payment_result && (
        <Box marginLeft={2} flexDirection="column">
          <Text bold underline>Payment Result:</Text>
          <Box marginLeft={2} flexDirection="column">
            <Text color={cart.payment_result.success ? 'green' : 'red'}>
              Status: {cart.payment_result.success ? 'SUCCESS' : 'FAILED'}
            </Text>
            {cart.payment_result.confirmation_number && (
              <Text>Confirmation #: {cart.payment_result.confirmation_number}</Text>
            )}
            {cart.payment_result.error_message && (
              <Text color="red">Error: {cart.payment_result.error_message}</Text>
            )}
          </Box>
        </Box>
      )}

      {/* Validation */}
      <Box marginLeft={2} flexDirection="column">
        <Text bold underline>Validation:</Text>
        <Box marginLeft={2} flexDirection="column">
          <Box>
            <Text>Decision: </Text>
            <DecisionBadge decision={validation.decision} />
          </Box>
          {validation.flags.length > 0 && (
            <Box flexDirection="column">
              <Text>Flags:</Text>
              {validation.flags.map((flag, i) => (
                <Text key={i} color="yellow">  - {flag}</Text>
              ))}
            </Box>
          )}
          {validation.reasoning && (
            <Text dimColor wrap="wrap">Reasoning: {validation.reasoning}</Text>
          )}
        </Box>
      </Box>

      {/* Output files */}
      <Box marginTop={1} marginLeft={2} flexDirection="column">
        <Text bold>Output files saved to ./output/</Text>
        <Text dimColor>  - shopping_plan.json</Text>
        <Text dimColor>  - cart.json</Text>
        <Text dimColor>  - validation.json</Text>
        <Text dimColor>  - agent_output.json</Text>
      </Box>

      {/* Actions */}
      <Box marginTop={1} marginLeft={2}>
        <Text>
          Press <Text color="green" bold>R</Text> to restart, <Text color="gray">Ctrl+C</Text> to exit
        </Text>
      </Box>
    </Box>
  );
}
