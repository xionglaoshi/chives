/** Typed failures raised by the ACP client. */

export class AcpError extends Error {
  constructor(message: string, cause?: unknown) {
    super(message, cause === undefined ? undefined : { cause });
    this.name = new.target.name;
  }
}

/** One request exceeded its timeout before a JSON-RPC response arrived. */
export class AcpTimeoutError extends AcpError {
  readonly method: string;
  readonly timeoutMs: number;

  constructor(method: string, timeoutMs: number) {
    super(`${method} timed out after ${timeoutMs}ms`);
    this.method = method;
    this.timeoutMs = timeoutMs;
  }
}

/** The harness process exited while requests were still in flight. */
export class AcpProcessExitedError extends AcpError {
  readonly exitCode: number | null;
  readonly signal: string | null;
  readonly stderrTail: readonly string[];

  constructor(exitCode: number | null, signal: string | null, stderrTail: readonly string[], cause?: unknown) {
    super(
      `harness process exited (code=${String(exitCode)}, signal=${String(signal)})`,
      cause,
    );
    this.exitCode = exitCode;
    this.signal = signal;
    this.stderrTail = stderrTail;
  }
}

/** The agent did not advertise a capability needed by the requested method. */
export class AcpUnsupportedError extends AcpError {
  readonly method: string;
  readonly capability: string;

  constructor(method: string, capability: string) {
    super(`${method} is not supported by this agent (missing capability: ${capability})`);
    this.method = method;
    this.capability = capability;
  }
}

/** A JSON-RPC error object returned by the agent. */
export class AcpRpcError extends AcpError {
  readonly code: number;
  readonly data: unknown;

  constructor(code: number, message: string, data?: unknown) {
    super(message);
    this.code = code;
    this.data = data;
  }
}

/** The agent sent an invalid or unexpected protocol message. */
export class AcpProtocolError extends AcpError {}
