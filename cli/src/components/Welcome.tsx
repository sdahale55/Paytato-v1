import React, { useEffect } from 'react';
import { Box, Text, useInput } from 'ink';

const LOGO = `
  ____              _        _        
 |  _ \\ __ _ _   _| |_ __ _| |_ ___  
 | |_) / _\` | | | | __/ _\` | __/ _ \\ 
 |  __/ (_| | |_| | || (_| | || (_) |
 |_|   \\__,_|\\__, |\\__\\__,_|\\__\\___/ 
             |___/                    
`;

interface WelcomeProps {
  onContinue: () => void;
}

export function Welcome({ onContinue }: WelcomeProps) {
  useInput((input, key) => {
    if (key.return || input === ' ') {
      onContinue();
    }
  });

  return (
    <Box flexDirection="column" gap={1}>
      <Text color="yellow">{LOGO}</Text>
      
      <Box flexDirection="column" marginLeft={2}>
        <Text bold color="cyan">Autonomous Shopping Agent</Text>
        <Text dimColor>Powered by Keywords AI + Playwright</Text>
      </Box>

      <Box marginTop={1} marginLeft={2} flexDirection="column" gap={0}>
        <Text>This agent will:</Text>
        <Text dimColor>  1. Parse your shopping requirements</Text>
        <Text dimColor>  2. Browse the store autonomously</Text>
        <Text dimColor>  3. Add matching items to cart</Text>
        <Text dimColor>  4. Validate the cart against your plan</Text>
      </Box>

      <Box marginTop={1} marginLeft={2}>
        <Text color="green" bold>Press Enter or Space to continue...</Text>
      </Box>
    </Box>
  );
}
