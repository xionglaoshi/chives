/** Validation failures collected while loading bot manifests. */

export interface BotLoadIssue {
  /** File the issue belongs to (absolute or caller-relative path). */
  file: string;
  message: string;
}

export class BotLoadError extends Error {
  readonly issues: readonly BotLoadIssue[];

  constructor(issues: readonly BotLoadIssue[]) {
    super(issues.map((issue) => `${issue.file}: ${issue.message}`).join('\n'));
    this.name = 'BotLoadError';
    this.issues = issues;
  }
}
