/**
 * chives-stream: forwards dsh's in-process assistant stream (text / reasoning deltas) to a
 * side channel, because dsh-acp only publishes committed messages. When
 * CHIVES_STREAM_SOCKET is set the frames go to that Unix-domain socket as NDJSON;
 * otherwise they fall back to stderr as `@@chives-stream {...}` lines. Read-only:
 * it never changes agent behaviour, and every failure is silent.
 */
/* global process */
import net from 'node:net';

export const name = 'chives-stream';
const TAG = '@@chives-stream ';
const SOCKET_ENV = 'CHIVES_STREAM_SOCKET';

export function apply(ctx, config = {}) {
  const socketPath = process.env[SOCKET_ENV];
  let socket = null;
  let queue = [];
  let dead = false;

  const emitStderr = (obj) => {
    try {
      process.stderr.write(TAG + JSON.stringify(obj) + '\n');
    } catch {
      // never break a turn
    }
  };

  const writeFrame = (obj) => {
    if (socketPath === undefined || socketPath === '') {
      emitStderr(obj);
      return;
    }
    if (dead) return;
    const line = JSON.stringify(obj) + '\n';
    if (socket !== null && socket.writable) {
      try {
        socket.write(line);
      } catch {
        // never break a turn
      }
      return;
    }
    queue.push(line);
  };

  if (socketPath !== undefined && socketPath !== '') {
    try {
      socket = net.createConnection({ path: socketPath });
      socket.unref();
      socket.on('connect', () => {
        const pending = queue;
        queue = [];
        for (const line of pending) {
          try {
            socket.write(line);
          } catch {
            // never break a turn
          }
        }
      });
      socket.on('error', () => {
        dead = true;
        queue = [];
        socket = null;
      });
      socket.on('close', () => {
        dead = true;
        queue = [];
        socket = null;
      });
    } catch {
      dead = true;
      socket = null;
    }
  }

  ctx.on('agent/assistant-stream', ({ agent, frame }) => {
    try {
      const session = agent?.session?.id ?? agent?.id ?? null;
      if (frame.type === 'start') {
        writeFrame({ session, t: 'start', attemptId: frame.attemptId });
        return;
      }
      if (frame.type === 'end') {
        writeFrame({ session, t: 'end', attemptId: frame.attemptId, outcome: frame.outcome });
        return;
      }
      const chunk = frame.chunk;
      if (!chunk) return;
      if (chunk.type === 'text-delta' || chunk.type === 'reasoning-delta') {
        writeFrame({
          session,
          t: chunk.type,
          attemptId: frame.attemptId,
          i: chunk.index,
          text: chunk.text,
        });
      } else if (config.verbose) {
        writeFrame({ session, t: chunk.type, attemptId: frame.attemptId });
      }
    } catch {
      // never break a turn
    }
  });
}
