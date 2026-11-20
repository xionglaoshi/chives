import assert from 'node:assert/strict'
import { test } from 'node:test'
import { Poller, backoffDelay, pollVisible } from '../src/client/polling.ts'
import type { PollChannel, PollerPort } from '../src/client/polling.ts'

interface Job {
  at: number
  run: () => void
}

class FakeTimers implements PollerPort {
  time = 0
  visible = true
  private seq = 0
  readonly jobs = new Map<number, Job>()
  setTimeout(run: () => void, ms: number): number {
    const id = ++this.seq
    this.jobs.set(id, { at: this.time + ms, run })
    return id
  }
  clearTimeout(id: number): void {
    this.jobs.delete(id)
  }
  isVisible(): boolean {
    return this.visible
  }
  async advance(ms: number): Promise<void> {
    this.time += ms
    const due = [...this.jobs.entries()].filter(([, job]) => job.at <= this.time).sort((left, right) => left[1].at - right[1].at)
    for (const [id, job] of due) {
      this.jobs.delete(id)
      job.run()
    }
    await flush()
  }
  nextDelay(): number | null {
    const times = [...this.jobs.values()].map((job) => job.at - this.time)
    return times.length === 0 ? null : Math.min(...times)
  }
}

async function flush(): Promise<void> {
  await new Promise<void>((resolve) => setImmediate(resolve))
}

function channel(name: string, intervalMs: number, loads: { count: number }): PollChannel {
  return {
    name,
    intervalMs,
    load: async () => {
      loads.count += 1
    },
  }
}

test('backoffDelay doubles and caps', () => {
  assert.equal(backoffDelay(5000, 0), 5000)
  assert.equal(backoffDelay(5000, 1), 10000)
  assert.equal(backoffDelay(5000, 2), 20000)
  assert.equal(backoffDelay(5000, 10), 60000)
  assert.equal(backoffDelay(5000, -1), 5000)
  assert.equal(backoffDelay(0, 2), 60000)
  assert.equal(backoffDelay(1000, 2, 3000), 3000)
})

test('pollVisible combines page and panel visibility', () => {
  assert.equal(pollVisible(false, true), true)
  assert.equal(pollVisible(true, true), false)
  assert.equal(pollVisible(false, false), false)
})

test('start runs every channel immediately and schedules its cadence', async () => {
  const timers = new FakeTimers()
  const a = { count: 0 }
  const b = { count: 0 }
  const poller = new Poller([channel('a', 5000, a), channel('b', 15000, b)], timers)
  poller.start()
  await flush()
  assert.equal(a.count, 1)
  assert.equal(b.count, 1)
  assert.equal(timers.jobs.size, 2)
  assert.equal(timers.nextDelay(), 5000)
})

test('a failed load doubles the next delay and success resets it', async () => {
  const timers = new FakeTimers()
  let fail = true
  let count = 0
  const poller = new Poller([{
    name: 'x',
    intervalMs: 1000,
    load: async () => {
      count += 1
      if (fail) throw new Error('boom')
    },
  }], timers)
  poller.start()
  await flush()
  assert.equal(count, 1)
  assert.equal(poller.failureCount('x'), 1)
  assert.equal(timers.nextDelay(), 2000)
  fail = false
  await timers.advance(2000)
  assert.equal(count, 2)
  assert.equal(poller.failureCount('x'), 0)
  assert.equal(timers.nextDelay(), 1000)
})

test('pause clears timers and stops loads; resume refreshes immediately', async () => {
  const timers = new FakeTimers()
  const loads = { count: 0 }
  const poller = new Poller([channel('x', 1000, loads)], timers)
  poller.start()
  await flush()
  assert.equal(loads.count, 1)
  poller.pause()
  assert.equal(timers.jobs.size, 0)
  await timers.advance(5000)
  assert.equal(loads.count, 1)
  poller.resume()
  await flush()
  assert.equal(loads.count, 2)
  assert.equal(timers.nextDelay(), 1000)
})

test('start while hidden schedules nothing until resume', async () => {
  const timers = new FakeTimers()
  timers.visible = false
  const loads = { count: 0 }
  const poller = new Poller([channel('x', 1000, loads)], timers)
  poller.start()
  await flush()
  assert.equal(loads.count, 0)
  assert.equal(timers.jobs.size, 0)
  timers.visible = true
  poller.resume()
  await flush()
  assert.equal(loads.count, 1)
})

test('visibleChanged pauses and resumes the loop', async () => {
  const timers = new FakeTimers()
  const loads = { count: 0 }
  const poller = new Poller([channel('x', 1000, loads)], timers)
  poller.start()
  await flush()
  poller.visibleChanged(false)
  assert.equal(timers.jobs.size, 0)
  await timers.advance(2000)
  assert.equal(loads.count, 1)
  poller.visibleChanged(true)
  await flush()
  assert.equal(loads.count, 2)
})

test('pollNow runs exactly one channel without disturbing the schedule', async () => {
  const timers = new FakeTimers()
  const a = { count: 0 }
  const b = { count: 0 }
  const poller = new Poller([channel('a', 1000, a), channel('b', 2000, b)], timers)
  poller.start()
  await flush()
  const before = timers.jobs.size
  await poller.pollNow('a')
  assert.equal(a.count, 2)
  assert.equal(b.count, 1)
  assert.equal(timers.jobs.size, before)
  await poller.pollNow('missing')
  assert.equal(a.count, 2)
})

test('stop clears every timer and prevents further loads', async () => {
  const timers = new FakeTimers()
  const loads = { count: 0 }
  const poller = new Poller([channel('x', 1000, loads)], timers)
  poller.start()
  await flush()
  poller.stop()
  assert.equal(timers.jobs.size, 0)
  await timers.advance(10000)
  assert.equal(loads.count, 1)
})
