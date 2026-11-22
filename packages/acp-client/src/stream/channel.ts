/** Local IPC server receiving the plugin's newline-delimited frames. */

import { randomUUID } from 'node:crypto';
import { mkdtemp, rm } from 'node:fs/promises';
import { createServer, type Server, type Socket } from 'node:net';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

import type { StreamFrame, StreamFrameType } from './draft.js';

const FRAME_TYPES = new Set<string>(['start', 'end', 'text-delta', 'reasoning-delta']);
const MAX_BUFFER_BYTES = 1024 * 1024;
const UNIX_SOCKET_PATH_LIMIT = 100;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function parseFrame(line: string): StreamFrame | undefined {
  let value: unknown;
  try {
    value = JSON.parse(line);
  } catch {
    return undefined;
  }
  if (!isRecord(value) || typeof value.session !== 'string' || value.session.length === 0) {
    return undefined;
  }
  if (typeof value.t !== 'string' || !FRAME_TYPES.has(value.t)) return undefined;
  const frame: StreamFrame = { session: value.session, t: value.t as StreamFrameType };
  if (typeof value.attemptId === 'string') frame.attemptId = value.attemptId;
  if (typeof value.i === 'number') frame.i = value.i;
  if (typeof value.text === 'string') frame.text = value.text;
  if (value.outcome !== undefined) frame.outcome = value.outcome;
  return frame;
}

/**
 * Listens on a unique Windows named pipe or a private Unix socket. Malformed
 * lines and client disconnects are ignored; a broken side channel must never
 * affect a conversation.
 */
export class StreamChannel {
  private server: Server | undefined;
  private directory: string | undefined;
  private path: string | undefined;
  private starting: Promise<string> | undefined;
  private readonly sockets = new Set<Socket>();
  private readonly listeners = new Set<(frame: StreamFrame) => void>();

  get socketPath(): string | undefined {
    return this.path;
  }

  onFrame(listener: (frame: StreamFrame) => void): () => void {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  }

  async start(): Promise<string> {
    if (this.path !== undefined) return this.path;
    if (this.starting !== undefined) return this.starting;
    this.starting = this.startOnce().finally(() => {
      this.starting = undefined;
    });
    return this.starting;
  }

  private async startOnce(): Promise<string> {
    const directory = process.platform === 'win32'
      ? undefined
      : await mkdtemp(join(tmpdir(), 'chives-acp-stream-'));
    const path = directory === undefined
      ? `\\\\.\\pipe\\chives-acp-stream-${randomUUID()}`
      : join(directory, 'stream.sock');
    const server = createServer((socket) => this.accept(socket));
    try {
      if (directory !== undefined && Buffer.byteLength(path) > UNIX_SOCKET_PATH_LIMIT) {
        throw new Error(`stream socket path is too long: ${path}`);
      }
      await new Promise<void>((resolve, reject) => {
        const onError = (error: Error): void => {
          server.removeListener('listening', onListening);
          reject(error);
        };
        const onListening = (): void => {
          server.removeListener('error', onError);
          resolve();
        };
        server.once('error', onError);
        server.once('listening', onListening);
        server.listen(path);
      });
    } catch (error) {
      if (directory !== undefined) await rm(directory, { recursive: true, force: true });
      throw error;
    }
    server.on('error', () => {
      // Post-listen errors only affect the optional side channel.
    });
    this.server = server;
    this.directory = directory;
    this.path = path;
    return path;
  }

  async close(): Promise<void> {
    const starting = this.starting;
    if (starting !== undefined) {
      try {
        await starting;
      } catch {
        // A failed start has nothing left to close.
      }
    }
    const server = this.server;
    const directory = this.directory;
    this.server = undefined;
    this.directory = undefined;
    this.path = undefined;
    for (const socket of this.sockets) socket.destroy();
    this.sockets.clear();
    this.listeners.clear();
    if (server !== undefined) {
      await new Promise<void>((resolve) => {
        server.close(() => resolve());
      });
    }
    if (directory !== undefined) await rm(directory, { recursive: true, force: true });
  }

  private accept(socket: Socket): void {
    this.sockets.add(socket);
    socket.setEncoding('utf8');
    let buffer = '';
    socket.on('data', (chunk: string) => {
      buffer += chunk;
      while (true) {
        const newline = buffer.indexOf('\n');
        if (newline < 0) break;
        const line = buffer.slice(0, newline);
        buffer = buffer.slice(newline + 1);
        this.dispatch(line);
      }
      if (buffer.length > MAX_BUFFER_BYTES) buffer = '';
    });
    const drop = (): void => {
      this.sockets.delete(socket);
    };
    socket.on('close', drop);
    socket.on('error', drop);
  }

  private dispatch(line: string): void {
    if (line.trim().length === 0) return;
    const frame = parseFrame(line.trim());
    if (frame === undefined) return;
    for (const listener of [...this.listeners]) listener(frame);
  }
}
