#!/usr/bin/env node
/**
 * Paytato Shopping Agent CLI
 * An interactive terminal UI for the autonomous shopping agent
 */

import React, { useState } from 'react';
import { render, Box, Text } from 'ink';
import meow from 'meow';

import { Welcome } from './components/Welcome.js';
import { InputForm, type FormData } from './components/InputForm.js';
import { Progress, type ProgressState } from './components/Progress.js';
import { Results, type AgentOutput } from './components/Results.js';
import { runAgent } from './utils/runAgent.js';

// CLI argument parsing
const cli = meow(`
  Usage
    $ paytato [options]

  Options
    --requirements, -r    Shopping requirements (skip interactive mode)
    --budget, -b          Budget (e.g., "$200" or "200")
    --domain, -d          Custom merchant domain URL
    --instructions, -i    Custom instructions for the agent
    --headless            Run browser in headless mode
    --help                Show this help message

  Examples
    $ paytato
    $ paytato -r "Buy a wireless mouse under $50"
    $ paytato -r "bluetooth speaker" -b 200 --headless
    $ paytato -r "laptop stand" -d "https://my-store.com"
`, {
  importMeta: import.meta,
  flags: {
    requirements: {
      type: 'string',
      shortFlag: 'r',
    },
    budget: {
      type: 'string',
      shortFlag: 'b',
    },
    domain: {
      type: 'string',
      shortFlag: 'd',
    },
    instructions: {
      type: 'string',
      shortFlag: 'i',
    },
    headless: {
      type: 'boolean',
      default: false,
    },
  },
});

type AppState = 'welcome' | 'input' | 'running' | 'results' | 'error';

interface AppProps {
  initialRequirements?: string;
  initialBudget?: string;
  initialDomain?: string;
  initialInstructions?: string;
  headless?: boolean;
}

function App({ 
  initialRequirements, 
  initialBudget,
  initialDomain,
  initialInstructions,
  headless = false 
}: AppProps) {
  const [state, setState] = useState<AppState>(
    initialRequirements ? 'running' : 'welcome'
  );
  const [formData, setFormData] = useState<FormData>({
    requirements: initialRequirements || '',
    budget: initialBudget || '',
    domain: initialDomain || '',
    instructions: initialInstructions || '',
  });
  const [progress, setProgress] = useState<ProgressState>({
    status: 'idle',
    step: '',
    logs: [],
  });
  const [result, setResult] = useState<AgentOutput | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Start running if initial requirements provided
  React.useEffect(() => {
    if (initialRequirements && state === 'running') {
      handleRun({
        requirements: initialRequirements,
        budget: initialBudget || '',
        domain: initialDomain || '',
        instructions: initialInstructions || '',
      });
    }
  }, []);

  const handleWelcomeContinue = () => {
    setState('input');
  };

  const handleFormSubmit = (data: FormData) => {
    setFormData(data);
    setState('running');
    handleRun(data);
  };

  const handleRun = async (data: FormData) => {
    setProgress({ status: 'running', step: 'Starting agent...', logs: [] });
    
    try {
      const output = await runAgent({
        requirements: data.requirements,
        budget: data.budget,
        domain: data.domain,
        instructions: data.instructions,
        headless,
        onProgress: (step, log) => {
          setProgress(prev => ({
            ...prev,
            step,
            logs: log ? [...prev.logs, log] : prev.logs,
          }));
        },
      });

      setResult(output);
      setState('results');
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      setError(message);
      setState('error');
    }
  };

  const handleRestart = () => {
    setFormData({ requirements: '', budget: '', domain: '', instructions: '' });
    setProgress({ status: 'idle', step: '', logs: [] });
    setResult(null);
    setError(null);
    setState('welcome');
  };

  return (
    <Box flexDirection="column" padding={1}>
      {state === 'welcome' && (
        <Welcome onContinue={handleWelcomeContinue} />
      )}

      {state === 'input' && (
        <InputForm onSubmit={handleFormSubmit} initialData={formData} />
      )}

      {state === 'running' && (
        <Progress state={progress} requirements={formData.requirements} />
      )}

      {state === 'results' && result && (
        <Results output={result} onRestart={handleRestart} />
      )}

      {state === 'error' && (
        <Box flexDirection="column" gap={1}>
          <Text color="red" bold>Error</Text>
          <Text color="red">{error}</Text>
          <Text dimColor>Press Ctrl+C to exit</Text>
        </Box>
      )}
    </Box>
  );
}

// Run the app
render(
  <App
    initialRequirements={cli.flags.requirements}
    initialBudget={cli.flags.budget}
    initialDomain={cli.flags.domain}
    initialInstructions={cli.flags.instructions}
    headless={cli.flags.headless}
  />
);
