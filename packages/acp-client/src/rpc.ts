/** Newline-delimited JSON-RPC 2.0 peer used by {@link AcpProcess}. */

import {
  AcpProtocolError,
  AcpRpcError,
  AcpTimeoutError,
} from './errors.js';

interface PendingRequest {
  readonly method: string;
  readonly resolve: (value: unknown) => void;
  readonly reject: (error: Error) => void;
  readonly timer: ReturnType<typeof setTimeout> | undefined;
}

export type RpcRequestHandler = (method: string, params: unknown) => Promise<unknown>;
export type RpcNotificationHandler = (method: string, params: unknown) => void;
export type RpcWrite = (line: string) => void;

interface RpcErrorShape {
  code: number;
  message: string;
  data?: unknown;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function asRpcError(value: unknown): RpcErrorShape | undefined {
  if (!isRecord(value) || typeof value.code !== 'number' || typeof value.message !== 'string') {
    return undefined;
  }
  return {
    code: value.code,
    message: value.message,
    ...(value.data === undefined ? {} : { data: value.data }),
  };
}

/**
 * Correlates requests with responses and dispatches agent-to-client requests and
 * notifications. A request may carry its own timeout; a timed-out request is
 * forgotten, so a late response is ignored instead of resolving a stale caller.
 */
export class JsonRpcConnection {
  private nextId = 1;
  private readonly pending = new Map<string, PendingRequest>();
  private closedError: Error | undefined;

  constructor(
    private readonly writeLine: RpcWrite,
    private readonly onRequest: RpcRequestHandler,
    private readonly onNotification: RpcNotificationHandler,
  ) {}

  get pendingCount(): number {
    return this.pending.size;
  }

  request(method: string, params: unknown = {}, timeoutMs = 0): Promise<unknown> {
    if (this.closedError !== undefined) return Promise.reject(this.closedError);
    const id = this.nextId++;
    return new Promise<unknown>((resolve, reject) => {
      const timer = timeoutMs > 0
        ? setTimeout(() => {
          this.pending.delete(String(id));
          reject(new AcpTimeoutError(method, timeoutMs));
        }, timeoutMs)
        : undefined;
      timer?.unref();
      this.pending.set(String(id), { method, resolve, reject, timer });
      try {
        this.writeLine(JSON.stringify({ jsonrpc: '2.0', id, method, params }));
      } catch (error: unknown) {
        this.pending.delete(String(id));
        if (timer !== undefined) clearTimeout(timer);
        reject(error instanceof Error ? error : new AcpProtocolError(String(error)));
      }
    });
  }

  notify(method: string, params: unknown = {}): void {
    if (this.closedError !== undefined) throw this.closedError;
    this.writeLine(JSON.stringify({ jsonrpc: '2.0', method, params }));
  }

  /** Parse one newline-delimited message; malformed lines are ignored. */
  handleLine(line: string): void {
    const trimmed = line.trim();
    if (trimmed.length === 0) return;
    let message: unknown;
    try {
      message = JSON.parse(trimmed);
    } catch {
      return;
    }
    if (!isRecord(message)) return;
    if (typeof message.method === 'string') {
      if (message.id === undefined) {
        this.onNotification(message.method, message.params ?? {});
        return;
      }
      const id = message.id;
      void this.dispatchRequest(id, message.method, message.params ?? {});
      return;
    }
    if (message.id === undefined) return;
    const pending = this.pending.get(String(message.id));
    if (pending === undefined) return;
    this.pending.delete(String(message.id));
    if (pending.timer !== undefined) clearTimeout(pending.timer);
    const rpcError = asRpcError(message.error);
    if (rpcError !== undefined) {
      pending.reject(new AcpRpcError(rpcError.code, rpcError.message, rpcError.data));
      return;
    }
    if (!('result' in message)) {
      pending.reject(new AcpProtocolError(`${pending.method}: response has neither result nor error`));
      return;
    }
    pending.resolve(message.result);
  }

  /** Reject every in-flight request and all future requests with the same error. */
  failAll(error: Error): void {
    if (this.closedError !== undefined) return;
    this.closedError = error;
    const pending = [...this.pending.values()];
    this.pending.clear();
    for (const entry of pending) {
      if (entry.timer !== undefined) clearTimeout(entry.timer);
      entry.reject(error);
    }
  }

  private async dispatchRequest(id: unknown, method: string, params: unknown): Promise<void> {
    try {
      const result = await this.onRequest(method, params);
      this.writeLine(JSON.stringify({ jsonrpc: '2.0', id, result: result ?? null }));
    } catch (error: unknown) {
      const rpcError = error instanceof AcpRpcError
        ? { code: error.code, message: error.message, ...(error.data === undefined ? {} : { data: error.data }) }
        : { code: -32603, message: error instanceof Error ? error.message : String(error) };
      try {
        this.writeLine(JSON.stringify({ jsonrpc: '2.0', id, error: rpcError }));
      } catch {
        // The process is already gone; the caller sees the exit through failAll.
      }
    }
  }
}
