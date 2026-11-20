/** Vite supplies "/" locally and "/chives/" for the published workbench. */
export function appPath(path: string): string {
  return import.meta.env.BASE_URL.replace(/\/$/, '') + path;
}
