import React from 'react';
import { Box, Text } from 'ink';
import Spinner from 'ink-spinner';

export interface ProgressState {
  status: 'idle' | 'running' | 'complete' | 'error';
  step: string;
  logs: string[];
}

interface ProgressProps {
  state: ProgressState;
  requirements: string;
}

const STEPS = [
  { id: 'plan', label: 'Creating shopping plan', pattern: /plan|requirements/i },
  { id: 'browse', label: 'Browsing store', pattern: /navigating|browse|shop/i },
  { id: 'add', label: 'Adding items to cart', pattern: /add|click|found match/i },
  { id: 'cart', label: 'Extracting cart state', pattern: /cart|extract/i },
  { id: 'validate', label: 'Validating cart', pattern: /validat/i },
  { id: 'intent', label: 'Submitting payment intent', pattern: /intent|step 4/i },
  { id: 'approval', label: 'Awaiting user approval', pattern: /approval|credentials|step 5/i },
  { id: 'payment', label: 'Executing payment', pattern: /executing payment|filling payment|step 6/i },
  { id: 'complete', label: 'Finalizing order', pattern: /reporting|complete|step 7/i },
];

function getCurrentStep(logs: string[]): number {
  const allLogs = logs.join('\n').toLowerCase();
  
  for (let i = STEPS.length - 1; i >= 0; i--) {
    if (STEPS[i].pattern.test(allLogs)) {
      return i;
    }
  }
  return 0;
}

export function Progress({ state, requirements }: ProgressProps) {
  const currentStep = getCurrentStep(state.logs);
  const recentLogs = state.logs.slice(-8);

  return (
    <Box flexDirection="column" gap={1}>
      <Box>
        <Text bold color="cyan">Shopping Agent Running</Text>
      </Box>

      <Box marginLeft={2} flexDirection="column">
        <Text dimColor>Requirements:</Text>
        <Text>{requirements}</Text>
      </Box>

      {/* Progress steps */}
      <Box marginTop={1} marginLeft={2} flexDirection="column">
        {STEPS.map((step, index) => {
          const isComplete = index < currentStep;
          const isCurrent = index === currentStep;
          
          return (
            <Box key={step.id}>
              <Box width={3}>
                {isCurrent && state.status === 'running' ? (
                  <Text color="green">
                    <Spinner type="dots" />
                  </Text>
                ) : isComplete ? (
                  <Text color="green">+</Text>
                ) : (
                  <Text dimColor>-</Text>
                )}
              </Box>
              <Text 
                color={isComplete ? 'green' : isCurrent ? 'yellow' : 'gray'}
                bold={isCurrent}
              >
                {step.label}
              </Text>
            </Box>
          );
        })}
      </Box>

      {/* Current step detail */}
      {state.step && (
        <Box marginTop={1} marginLeft={2}>
          <Text color="yellow">{state.step}</Text>
        </Box>
      )}

      {/* Recent logs */}
      {recentLogs.length > 0 && (
        <Box marginTop={1} marginLeft={2} flexDirection="column">
          <Text dimColor>Recent activity:</Text>
          <Box flexDirection="column" marginLeft={2}>
            {recentLogs.map((log, i) => (
              <Text key={i} dimColor wrap="truncate-end">
                {log.length > 70 ? log.substring(0, 70) + '...' : log}
              </Text>
            ))}
          </Box>
        </Box>
      )}

      <Box marginTop={1} marginLeft={2}>
        <Text dimColor>Press Ctrl+C to abort</Text>
      </Box>
    </Box>
  );
}
