/**
 * Test-only loader: transpiles `src/client` to JS in a temporary directory under
 * the package (so bare imports resolve through the package's node_modules) and
 * imports the resulting ESM module. Uses the existing `typescript` devDependency;
 * no new dependency and no production build step.
 */
import { mkdtempSync, mkdirSync, readFileSync, readdirSync, rmSync, statSync, writeFileSync } from 'node:fs'
import { join, relative } from 'node:path'
import { pathToFileURL } from 'node:url'
import * as ts from 'typescript'

const CLIENT_DIR = join(import.meta.dirname, '..', 'src', 'client')

function walk(dir: string): string[] {
  const files: string[] = []
  for (const entry of readdirSync(dir)) {
    const path = join(dir, entry)
    if (statSync(path).isDirectory()) files.push(...walk(path))
    else if (/\.(ts|tsx)$/.test(path)) files.push(path)
  }
  return files
}

function rewrite(specifier: string): string {
  return specifier.replace(/\.tsx?$/, '.js')
}

function transpile(source: string): string {
  const output = ts.transpileModule(source, {
    compilerOptions: {
      target: ts.ScriptTarget.ES2022,
      module: ts.ModuleKind.ESNext,
      moduleResolution: ts.ModuleResolutionKind.Bundler,
      jsx: ts.JsxEmit.ReactJSX,
      verbatimModuleSyntax: false,
      esModuleInterop: true,
      skipLibCheck: true,
    },
  }).outputText
  return output.replace(/((?:from|import)\s*\(?\s*['"])(\.{1,2}\/[^'"]+?)(['"])/g, (_match, prefix: string, spec: string, suffix: string) => `${prefix}${rewrite(spec)}${suffix}`)
}

/** Transpile the whole client directory and import one module from it. */
export async function loadClientModule(name: string): Promise<Record<string, unknown>> {
  const dir = mkdtempSync(join(import.meta.dirname, '.tmp-'))
  for (const file of walk(CLIENT_DIR)) {
    const target = join(dir, relative(CLIENT_DIR, file).replace(/\.tsx?$/, '.js'))
    mkdirSync(join(target, '..'), { recursive: true })
    writeFileSync(target, transpile(readFileSync(file, 'utf8')), 'utf8')
  }
  const entry = join(dir, name.replace(/\.tsx?$/, '.js'))
  const url = `${pathToFileURL(entry).href}?t=${Date.now()}`
  try {
    return await import(url) as Record<string, unknown>
  } finally {
    rmSync(dir, { recursive: true, force: true })
  }
}
