import { spawn, type ChildProcess } from 'node:child_process';
import { join } from 'node:path';
import type { ProcessHealth } from '../api/protocol.js';

/** A supervised scheduling process with cache and storage operations in the core. */
export class BackgroundService {
  state: ProcessHealth = 'not_started';
  detail = '';
  private child: ChildProcess | undefined;
  private timer: ReturnType<typeof setTimeout> | undefined;
  private pending: Promise<void> | undefined;
  private started = false;

  constructor(
    private readonly root: string,
    private readonly name: string,
    private readonly interval: number,
    private readonly work: () => Promise<void>,
  ) {}

  start(delay = 0): void {
    if (this.started) return;
    this.started = true;
    this.launch(delay);
  }

  private launch(delay: number): void {
    const child = spawn(process.execPath, [
      join(this.root, 'scripts/background-service.cjs'), this.name, String(this.interval), String(delay),
    ], { stdio: ['ignore', 'ignore', 'inherit', 'ipc'], windowsHide: true });
    this.child = child;
    child.on('message', message => {
      if (this.child !== child || !this.started) return;
      if (message === 'ready' && this.state === 'not_started') this.state = 'running';
      if (message !== 'tick') return;
      const previous = this.pending;
      this.pending = Promise.resolve(previous).then(async () => {
        if (this.child !== child || !this.started) return;
        try {
          await this.work();
          if (this.child === child) {
            this.state = 'running';
            this.detail = '';
          }
        } catch (error) {
          if (this.child === child) {
            this.state = 'error';
            this.detail = error instanceof Error ? error.message : String(error);
          }
        }
        if (child.connected) child.send('complete', () => {});
      });
    });
    child.once('error', error => { this.detail = error.message; });
    child.once('close', (code, signal) => {
      if (this.child !== child) return;
      this.child = undefined;
      if (!this.started) return;
      this.state = 'error';
      this.detail = `服务进程退出（${signal ?? code ?? '未知'}），正在等待重启。`;
      this.timer = setTimeout(() => this.launch(0), 5_000);
      this.timer.unref();
    });
  }

  async stop(): Promise<void> {
    this.started = false;
    clearTimeout(this.timer);
    const child = this.child;
    this.child = undefined;
    if (child?.connected) child.disconnect();
    child?.kill();
    await this.pending;
    this.state = 'not_started';
  }
}
