/** Spawns a harness process and exposes its stdio JSON-RPC endpoint. */

import { spawn, type ChildProcessWithoutNullStreams } from 'node:child_process';
import { createInterface, type Interface } from 'node:readline';

import { AcpProcessExitedError } from './errors.js';
import {
  JsonRpcConnection,
  type RpcNotificationHandler,
  type RpcRequestHandler,
} from './rpc.js';

export interface AcpSpawnSpec {
  command: string;
  args?: readonly string[];
  cwd?: string;
  env?: Record<string, string | undefined>;
  /** Maximum stderr lines retained for diagnostics. Defaults to 50. */
  stderrLines?: number;
}

export interface AcpExitInfo {
  code: number | null;
  signal: string | null;
  stderrTail: readonly string[];
}

export interface AcpProcessOptions {
  onRequest: RpcRequestHandler;
  onNotification: RpcNotificationHandler;
}

const DEFAULT_STDERR_LINES = 50;
const DEFAULT_CLOSE_GRACE_MS = 2000;

/**
 * One harness child process speaking newline-delimited JSON-RPC 2.0 on stdio.
 * Stderr is diagnostic only: only the trailing lines are retained, never parsed
 * as protocol traffic. An exit rejects every pending request and notifies
 * {@link onExit} subscribers exactly once.
 */
export class AcpProcess {
  readonly pid: number | undefined;
  private readonly child: ChildProcessWithoutNullStreams;
  private readonly rpc: JsonRpcConnection;
  private readonly stderrBuffer: string[] = [];
  private readonly stderrLimit: number;
  private readonly exitListeners = new Set<(info: AcpExitInfo) => void>();
  private readonly stdoutReader: Interface;
  private readonly stderrReader: Interface;
  private finalInfo: AcpExitInfo | undefined;
  private readonly exitPromise: Promise<AcpExitInfo>;
  private resolveExit!: (info: AcpExitInfo) => void;

  constructor(spec: AcpSpawnSpec, options: AcpProcessOptions) {
    this.stderrLimit = spec.stderrLines ?? DEFAULT_STDERR_LINES;
    this.exitPromise = new Promise<AcpExitInfo>((resolve) => {
      this.resolveExit = resolve;
    });
    this.child = spawn(spec.command, [...spec.args ?? []], {
      ...(spec.cwd === undefined ? {} : { cwd: spec.cwd }),
      ...(spec.env === undefined ? {} : { env: spec.env }),
      stdio: ['pipe', 'pipe', 'pipe'],
    });
    this.pid = this.child.pid;
    this.rpc = new JsonRpcConnection(
      (line) => this.writeLine(line),
      options.onRequest,
      options.onNotification,
    );
    this.stdoutReader = createInterface({ input: this.child.stdout });
    this.stdoutReader.on('line', (line) => this.rpc.handleLine(line));
    this.stderrReader = createInterface({ input: this.child.stderr });
    this.stderrReader.on('line', (line) => {
      if (this.stderrBuffer.length >= this.stderrLimit) this.stderrBuffer.shift();
      this.stderrBuffer.push(line);
    });
    this.child.stdin.on('error', () => {
      // A closed pipe surfaces through the process exit path below.
    });
    this.child.on('error', (error) => {
      this.finalize(null, null, error);
    });
    this.child.on('close', (code, signal) => {
      this.finalize(code, signal === null ? null : String(signal), undefined);
    });
  }

  get stderrTail(): readonly string[] {
    return [...this.stderrBuffer];
  }

  get exited(): boolean {
    return this.finalInfo !== undefined;
  }

  get exitInfo(): AcpExitInfo | undefined {
    return this.finalInfo;
  }

  request(method: string, params: unknown = {}, timeoutMs = 0): Promise<unknown> {
    return this.rpc.request(method, params, timeoutMs);
  }

  notify(method: string, params: unknown = {}): void {
    this.rpc.notify(method, params);
  }

  /** Resolves when the child has closed; never rejects. */
  async waitForExit(): Promise<AcpExitInfo> {
    return this.exitPromise;
  }

  onExit(listener: (info: AcpExitInfo) => void): () => void {
    this.exitListeners.add(listener);
    return () => {
      this.exitListeners.delete(listener);
    };
  }

  /**
   * End stdin so the harness can quiesce, then escalate to SIGTERM/SIGKILL when
   * it does not exit within the grace window.
   */
  async close(graceMs = DEFAULT_CLOSE_GRACE_MS): Promise<AcpExitInfo> {
    if (this.finalInfo !== undefined) return this.finalInfo;
    try {
      this.child.stdin.end();
    } catch {
      // The pipe may already be closed; waitForExit still resolves below.
    }
    const graceful = await this.waitForExitWithin(graceMs);
    if (graceful !== undefined) return graceful;
    this.child.kill('SIGTERM');
    const terminated = await this.waitForExitWithin(1000);
    if (terminated !== undefined) return terminated;
    this.child.kill('SIGKILL');
    return await this.waitForExitWithin(1000) ?? this.currentInfo();
  }

  kill(signal: NodeJS.Signals = 'SIGTERM'): void {
    if (this.finalInfo === undefined) this.child.kill(signal);
  }

  private writeLine(line: string): void {
    if (this.finalInfo !== undefined) {
      throw new AcpProcessExitedError(
        this.finalInfo.code,
        this.finalInfo.signal,
        this.finalInfo.stderrTail,
      );
    }
    this.child.stdin.write(`${line}\n`);
  }

  private waitForExitWithin(ms: number): Promise<AcpExitInfo | undefined> {
    if (this.finalInfo !== undefined) return Promise.resolve(this.finalInfo);
    return new Promise<AcpExitInfo | undefined>((resolve) => {
      const timer = setTimeout(() => {
        this.exitListeners.delete(listener);
        resolve(undefined);
      }, ms);
      timer.unref();
      const listener = (info: AcpExitInfo): void => {
        clearTimeout(timer);
        resolve(info);
      };
      this.exitListeners.add(listener);
    });
  }

  private currentInfo(): AcpExitInfo {
    return this.finalInfo ?? {
      code: this.child.exitCode,
      signal: this.child.signalCode,
      stderrTail: this.stderrBuffer,
    };
  }

  private finalize(code: number | null, signal: string | null, cause: unknown): void {
    if (this.finalInfo !== undefined) return;
    const info: AcpExitInfo = { code, signal, stderrTail: this.stderrTail };
    this.finalInfo = info;
    this.stdoutReader.close();
    this.stderrReader.close();
    const error = new AcpProcessExitedError(code, signal, info.stderrTail, cause);
    this.rpc.failAll(error);
    this.resolveExit(info);
    for (const listener of [...this.exitListeners]) {
      this.exitListeners.delete(listener);
      listener(info);
    }
  }
}
