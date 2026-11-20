/** Minimal Node globals used by the stdio entry point (avoids adding @types/node). */
declare const process: {
  env: Record<string, string | undefined>;
  exit(code?: number): never;
};
