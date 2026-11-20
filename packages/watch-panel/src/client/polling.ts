/**
 * Small layered polling scheduler used by both panels. Each channel keeps its
 * own cadence and its own exponential backoff, overlapping loads are skipped,
 * and nothing is scheduled while the panel or page is not visible.
 */

export interface PollChannel {
  readonly name: string
  readonly intervalMs: number
  load(): Promise<unknown>
}

export interface TimerPort {
  setTimeout(handler: () => void, ms: number): number
  clearTimeout(id: number): void
}

export interface PollerPort extends TimerPort {
  isVisible(): boolean
}

export const MAX_BACKOFF_MS = 60_000

/** Base interval multiplied by 2^failures, capped; failures above 6 are clamped. */
export function backoffDelay(baseMs: number, failures: number, cap = MAX_BACKOFF_MS): number {
  if (!Number.isFinite(baseMs) || baseMs <= 0) return cap
  const exponent = Math.min(6, Math.max(0, Math.trunc(failures)))
  return Math.min(cap, baseMs * 2 ** exponent)
}

/** Page and panel visibility combined into the scheduler's single switch. */
export function pollVisible(documentHidden: boolean, panelVisible: boolean): boolean {
  return !documentHidden && panelVisible
}

export class Poller {
  private readonly channels: readonly PollChannel[]
  private readonly port: PollerPort
  private readonly handles = new Map<string, number>()
  private readonly failures = new Map<string, number>()
  private running = false
  private paused = false

  constructor(channels: readonly PollChannel[], port: PollerPort) {
    this.channels = channels
    this.port = port
  }

  /** Run every channel immediately and schedule its next tick. */
  start(): void {
    if (this.running) return
    this.running = true
    this.paused = !this.port.isVisible()
    if (this.paused) return
    for (const channel of this.channels) void this.run(channel)
  }

  stop(): void {
    this.running = false
    this.paused = false
    for (const id of this.handles.values()) this.port.clearTimeout(id)
    this.handles.clear()
  }

  pause(): void {
    if (!this.running || this.paused) return
    this.paused = true
    for (const id of this.handles.values()) this.port.clearTimeout(id)
    this.handles.clear()
  }

  /** Resume with an immediate refresh, then the normal cadence. */
  resume(): void {
    if (!this.running || !this.paused) return
    this.paused = false
    for (const channel of this.channels) void this.run(channel)
  }

  visibleChanged(visible: boolean): void {
    if (visible) this.resume()
    else this.pause()
  }

  /** Manual tick for tests and explicit refresh buttons. */
  async pollNow(name: string): Promise<void> {
    const channel = this.channels.find((entry) => entry.name === name)
    if (!channel) return
    await this.execute(channel)
  }

  failureCount(name: string): number {
    return this.failures.get(name) ?? 0
  }

  private async run(channel: PollChannel): Promise<void> {
    if (!this.running || this.paused) return
    await this.execute(channel)
    if (!this.running || this.paused) return
    const delay = backoffDelay(channel.intervalMs, this.failures.get(channel.name) ?? 0)
    this.handles.set(channel.name, this.port.setTimeout(() => { void this.run(channel) }, delay))
  }

  private async execute(channel: PollChannel): Promise<void> {
    if (!this.running || this.paused || !this.port.isVisible()) return
    try {
      await channel.load()
      this.failures.set(channel.name, 0)
    } catch {
      this.failures.set(channel.name, (this.failures.get(channel.name) ?? 0) + 1)
    }
  }
}
