export { CnWatchClient } from './engine.js';
export type {
  CnWatchClientOptions,
  EngineListResult,
  EnginePlanState,
  EngineRemoveResult,
  EngineUpsertResult,
} from './engine.js';
export {
  DEFAULT_EXPIRES_DAYS,
  MAX_CONDITIONS,
  MAX_LABEL_CHARS,
  MAX_CHIVES_WATCHES,
  MAX_NOTE_CHARS,
  MAX_WATCHES_PER_BOT,
  WatchValidationError,
  buildPlan,
  describeCondition,
  describeGiveUp,
  describeWatch,
  normalizeWatchCode,
  planIdFor,
  validateCondition,
  validateWatchInput,
  watchIdFromPlan,
} from './plan.js';
export {
  REPEAT_COOLDOWN_MS,
  WATCH_SYNC_INTERVAL_MS,
  WatchService,
  consumeWatchNotices,
} from './service.js';
export type {
  WatchCreateInput,
  WatchDetail,
  WatchServiceOptions,
  WatchTriggerInput,
  WatchTriggerResult,
  WatchUpdateInput,
} from './service.js';
