export {
  buildDshPatch,
  buildMcpServers,
  DEFAULT_REPO_ROOT,
  dshPatchPath,
  dshSpawnSpec,
  evaluateOverlayEnv,
  chivesMcpServer,
  writeDshPatch,
} from './dsh.js';
export type {
  DshModelRoute,
  DshPatchOptions,
  DshSpawnOptions,
  DshSpawnSpec,
  ChivesMcpServerOptions,
} from './dsh.js';
export { DshDriver } from './dsh-driver.js';
export type { DshDriverOptions } from './dsh-driver.js';
export { FAKE_DEFAULT_SCRIPT, FakeDriver } from './fake.js';
export type { FakeDriverOptions, FakeStep } from './fake.js';
export type {
  HarnessDriver,
  HarnessEvent,
  HarnessPromptResult,
  HarnessSink,
} from './types.js';
export {
  isJsExpression,
  JS_ENV_SENTINEL,
  jsExpression,
  loadOverlayMcpConfigs,
  parseCordisPatch,
  readCordisPatch,
  stripJsTags,
} from './overlays.js';
export type { LoadedOverlayConfigs, McpOverlayConfig, PatchEntry } from './overlays.js';
