/** A tiny TTL cache that merges concurrent loads of the same value. */

export class CoalescedTtlCache<T> {
  private entry: { value: T; expiresAt: number } | null = null;
  private pending: Promise<T> | null = null;

  constructor(private readonly now: () => number) {}

  get(ttlMs: number, load: () => Promise<T>): Promise<T> {
    if (this.entry !== null && this.now() < this.entry.expiresAt) {
      return Promise.resolve(this.entry.value);
    }
    if (this.pending !== null) return this.pending;
    const pending = load()
      .then((value) => {
        this.entry = { value, expiresAt: this.now() + ttlMs };
        return value;
      })
      .finally(() => {
        this.pending = null;
      });
    this.pending = pending;
    return pending;
  }

  /** Drops the cached value; an in-flight load still resolves for its callers. */
  clear(): void {
    this.entry = null;
  }
}
