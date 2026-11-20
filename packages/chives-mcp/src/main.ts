/** stdio entry point: `node <repo>/packages/chives-mcp/dist/main.js`. */

import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js';

import { ChivesClient } from './client.js';
import { createChivesMcpServer } from './server.js';

async function main(): Promise<void> {
  const client = new ChivesClient({
    api: process.env.CHIVES_API ?? '',
    token: process.env.CHIVES_SESSION_TOKEN ?? '',
  });
  const features = (process.env.CHIVES_FEATURES ?? '')
    .split(',')
    .map((entry) => entry.trim())
    .filter((entry) => entry !== '');
  const server = createChivesMcpServer(client, { features });
  await server.connect(new StdioServerTransport());
}

main().catch((error: unknown) => {
  console.error('chives-mcp failed to start', error);
  process.exit(1);
});
