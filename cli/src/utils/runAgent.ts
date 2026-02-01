import { spawn } from 'node:child_process';
import { createReadStream, existsSync } from 'node:fs';
import { readFile } from 'node:fs/promises';
import { createInterface } from 'node:readline';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import type { AgentOutput } from '../components/Results.js';

interface RunAgentOptions {
  requirements: string;
  budget?: string;
  domain?: string;
  instructions?: string;
  headless?: boolean;
  onProgress?: (step: string, log?: string) => void;
}

// Get the project root (parent of cli directory)
const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);
const PROJECT_ROOT = join(__dirname, '..', '..', '..');

export async function runAgent(options: RunAgentOptions): Promise<AgentOutput> {
  const { requirements, budget, domain, instructions, headless = false, onProgress } = options;

  return new Promise((resolve, reject) => {
    // Build requirements string with budget if provided
    let fullRequirements = requirements;
    if (budget) {
      // Check if budget is already in requirements
      if (!requirements.toLowerCase().includes('budget') && !requirements.includes('$')) {
        fullRequirements = `${requirements}, budget ${budget.startsWith('$') ? budget : '$' + budget}`;
      }
    }

    // Build command arguments
    const args = [
      '-m', 'agent',
      '-r', fullRequirements,
      '-o', join(PROJECT_ROOT, 'output'),
    ];

    if (headless) {
      args.push('--headless');
    }

    if (domain) {
      args.push('--domain', domain);
    }

    if (instructions) {
      args.push('--instructions', instructions);
    }

    onProgress?.('Starting Python agent...');

    // Spawn the Python process
    const proc = spawn('python', args, {
      cwd: PROJECT_ROOT,
      env: { ...process.env },
      stdio: ['pipe', 'pipe', 'pipe'],
    });

    let stdout = '';
    let stderr = '';

    // Stream stdout for progress updates
    if (proc.stdout) {
      const rl = createInterface({ input: proc.stdout });
      rl.on('line', (line) => {
        stdout += line + '\n';
        
        // Parse log lines for progress updates
        if (line.includes('STEP 1')) {
          onProgress?.('Creating shopping plan...', line);
        } else if (line.includes('STEP 2')) {
          onProgress?.('Shopping autonomously...', line);
        } else if (line.includes('STEP 3')) {
          onProgress?.('Validating cart...', line);
        } else if (line.includes('STEP 4')) {
          onProgress?.('Submitting payment intent...', line);
        } else if (line.includes('STEP 5')) {
          onProgress?.('Awaiting Paytato approval...', line);
        } else if (line.includes('STEP 6')) {
          onProgress?.('Executing payment...', line);
        } else if (line.includes('STEP 7')) {
          onProgress?.('Reporting results to Paytato...', line);
        } else if (line.includes('PAUSING 15 SECONDS')) {
          onProgress?.('Pausing before final submission...', line);
        } else if (line.includes('Navigating')) {
          onProgress?.('Navigating to store...', line);
        } else if (line.includes('Found match')) {
          onProgress?.('Found matching product', line);
        } else if (line.includes('Clicked Add')) {
          onProgress?.('Adding item to cart', line);
        } else if (line.includes('Cart total')) {
          onProgress?.('Cart ready', line);
        } else if (line.includes('[INFO]') || line.includes('[DEBUG]')) {
          // Extract the message part
          const match = line.match(/\[(?:INFO|DEBUG)\]\s+\S+:\s+(.+)/);
          if (match) {
            onProgress?.(match[1], line);
          }
        }
      });
    }

    // Capture stderr
    if (proc.stderr) {
      const rl = createInterface({ input: proc.stderr });
      rl.on('line', (line) => {
        stderr += line + '\n';
        // Still pass errors as progress updates
        if (line.includes('ERROR') || line.includes('error')) {
          onProgress?.('Error: ' + line.substring(0, 50), line);
        }
      });
    }

    proc.on('close', async (code) => {
      if (code !== 0 && code !== null) {
        reject(new Error(`Agent exited with code ${code}\n${stderr}`));
        return;
      }

      // Read the output file
      const outputPath = join(PROJECT_ROOT, 'output', 'agent_output.json');
      
      try {
        if (!existsSync(outputPath)) {
          reject(new Error('Agent output file not found. Check logs for errors.'));
          return;
        }

        const content = await readFile(outputPath, 'utf-8');
        const output = JSON.parse(content) as AgentOutput;
        resolve(output);
      } catch (err) {
        reject(new Error(`Failed to read agent output: ${err}`));
      }
    });

    proc.on('error', (err) => {
      reject(new Error(`Failed to spawn agent: ${err.message}`));
    });
  });
}
