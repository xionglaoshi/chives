/** Low-level MCP server exposing the chives tool catalog over any transport. */

import { Server } from '@modelcontextprotocol/sdk/server/index.js';
import {
  CallToolRequestSchema,
  ListToolsRequestSchema,
  type CallToolResult,
} from '@modelcontextprotocol/sdk/types.js';

import { ChivesClient } from './client.js';
import {
  WATCH_DISABLED_MESSAGE,
  callTool,
  isToolEnabled,
  toolsForFeatures,
} from './tools.js';

export const CHIVES_MCP_NAME = '@chives/chives-mcp';
export const CHIVES_MCP_VERSION = '0.1.0';

export interface ChivesMcpServerOptions {
  /** Features enabled for this bot, e.g. `['watches']`; absent means none. */
  features?: readonly string[];
}

export function createChivesMcpServer(
  client: ChivesClient,
  options: ChivesMcpServerOptions = {},
): Server {
  const features = options.features ?? [];
  const tools = toolsForFeatures(features);
  const server = new Server(
    { name: CHIVES_MCP_NAME, version: CHIVES_MCP_VERSION },
    { capabilities: { tools: {} } },
  );

  server.setRequestHandler(ListToolsRequestSchema, async () => ({
    tools: [...tools],
  }));

  server.setRequestHandler(CallToolRequestSchema, async (request): Promise<CallToolResult> => {
    const { name, arguments: args } = request.params;
    if (!isToolEnabled(name, features)) {
      const content = [
        {
          type: 'text' as const,
          text: JSON.stringify({ error: 'forbidden', message: WATCH_DISABLED_MESSAGE }),
        },
      ];
      return { content, isError: true };
    }
    const result = await callTool(client, name, args);
    const content = [{ type: 'text' as const, text: JSON.stringify(result.value) }];
    return result.isError ? { content, isError: true } : { content };
  });

  return server;
}
