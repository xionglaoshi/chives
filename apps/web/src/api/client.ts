import { appPath } from '../appPath';
import type {
  ApiErrorBody,
  ApprovalDto,
  BotProfile,
  BotSummary,
  BotMemoryItem,
  BotMemoryList,
  DeliverableDto,
  CancelAccepted,
  MessageAccepted,
  ChivesStatusDto,
  SearchResponse,
  TaskDetail,
  TaskDto,
  TimelinePage,
  WorkspaceFileList,
  RoutineDto,
  AlertEventDto,
  ActiveRoutineDto,
  AppearanceSettingsDto,
  DataLocationDto,
  ComposerModelMenu, ComposerModelState, ModelTuning,
  ModelProviderDto,
  ModelSettingsDto,
  ProactiveSettingsDto,
  RuntimeSettingsDto,
  SettingsProfileDto,
  WatchDetailDto,
  WatchDto,
  NotificationDto,
  MarketDashboardDto,
  PortfolioDashboardDto,
  MessageAttachmentDto,
  StrategyPoolsDto
} from '@chives/server/protocol';

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;

  constructor(status: number, code: string, message: string) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
  }
}

async function readError(response: Response): Promise<ApiError> {
  let code = `http_${response.status}`;
  let message = `请求失败（HTTP ${response.status}）`;
  try {
    const body = (await response.json()) as Partial<ApiErrorBody>;
    if (body.error !== undefined) {
      code = body.error.code;
      message = body.error.message;
    }
  } catch {
    // Keep the generic message when the body is not JSON.
  }
  return new ApiError(response.status, code, message);
}

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(appPath(url), {
    headers: { accept: 'application/json', ...(init?.body === undefined ? {} : { 'content-type': 'application/json' }) },
    ...init
  });
  if (!response.ok) throw await readError(response);
  return (await response.json()) as T;
}

export function listBots(signal?: AbortSignal): Promise<BotSummary[]> {
  return request<BotSummary[]>('/api/bots', signal === undefined ? undefined : { signal });
}

export function readComposerSelection(id:string, signal:AbortSignal) {
  return request<{current:ComposerModelState}>(`/api/bots/${encodeURIComponent(id)}/composer-model?view=current`, {signal});
}

export function readComposerMenu(id:string, signal:AbortSignal) {
  return request<ComposerModelMenu>(`/api/bots/${encodeURIComponent(id)}/composer-model`, {signal});
}

export function saveComposerModel(id:string, selection:{followGlobal:true} | {connection:string; model:string; tuning?:ModelTuning}) {
  return request<ComposerModelState>(`/api/bots/${encodeURIComponent(id)}/composer-model`, {
    method:'PUT', body:JSON.stringify(selection)
  });
}

export function fetchBotProfile(botId: string, signal?: AbortSignal): Promise<BotProfile> {
  return request<BotProfile>(`/api/bots/${encodeURIComponent(botId)}/profile`, {
    ...(signal === undefined ? {} : { signal })
  });
}

export function fetchMemories(
  botId: string,
  signal?: AbortSignal
): Promise<BotMemoryList> {
  return request<BotMemoryList>(`/api/bots/${encodeURIComponent(botId)}/memories`, {
    ...(signal === undefined ? {} : { signal })
  });
}

export interface MemoryPatch {
  title?: string;
  body?: string;
  kind?: BotMemoryItem['kind'];
  expiresAt?: string | null;
}

export function updateMemory(
  botId: string,
  slug: string,
  patch: MemoryPatch
): Promise<{ ok: boolean; memory: BotMemoryItem | null; count: number }> {
  return request(`/api/bots/${encodeURIComponent(botId)}/memories/${encodeURIComponent(slug)}`, {
    method: 'PUT',
    body: JSON.stringify(patch)
  });
}

export function deleteMemory(
  botId: string,
  slug: string
): Promise<{ ok: boolean; count: number }> {
  return request(`/api/bots/${encodeURIComponent(botId)}/memories/${encodeURIComponent(slug)}`, {
    method: 'DELETE'
  });
}

export function fetchBotFiles(
  botId: string,
  dir = '',
  signal?: AbortSignal,
  recursive = false
): Promise<WorkspaceFileList> {
  const params = new URLSearchParams();
  if (dir !== '') params.set('dir', dir);
  if (recursive) params.set('recursive', '1');
  const query = params.toString();
  return request<WorkspaceFileList>(
    `/api/bots/${encodeURIComponent(botId)}/files${query === '' ? '' : `?${query}`}`,
    signal === undefined ? undefined : { signal }
  );
}

export function revealBotDirectory(botId: string): Promise<{ ok: boolean }> {
  return request<{ ok: boolean }>(`/api/bots/${encodeURIComponent(botId)}/reveal`, {
    method: 'POST'
  });
}

export interface BotPatch {
  displayName?: string | null;
  avatar?: { emblem: string; tone: string } | null;
}

export function updateBot(botId: string, patch: BotPatch): Promise<BotSummary> {
  return request<BotSummary>(`/api/bots/${encodeURIComponent(botId)}`, {
    method: 'PATCH',
    body: JSON.stringify(patch)
  });
}

export function fetchTimeline(
  botId: string,
  options: { beforeSeq?: number | null; limit?: number; signal?: AbortSignal } = {}
): Promise<TimelinePage> {
  const params = new URLSearchParams();
  params.set('limit', String(options.limit ?? 50));
  if (options.beforeSeq !== undefined && options.beforeSeq !== null) {
    params.set('beforeSeq', String(options.beforeSeq));
  }
  const signal = options.signal;
  return request<TimelinePage>(`/api/bots/${encodeURIComponent(botId)}/timeline?${params.toString()}`, {
    ...(signal === undefined ? {} : { signal })
  });
}

export function fetchTask(taskId: string, signal?: AbortSignal): Promise<TaskDetail> {
  return request<TaskDetail>(`/api/tasks/${encodeURIComponent(taskId)}`, {
    ...(signal === undefined ? {} : { signal })
  });
}

export function searchTimeline(
  botId: string,
  query: string,
  options: { limit?: number; signal?: AbortSignal } = {}
): Promise<SearchResponse> {
  const params = new URLSearchParams();
  params.set('q', query);
  if (options.limit !== undefined) params.set('limit', String(options.limit));
  return request<SearchResponse>(
    `/api/bots/${encodeURIComponent(botId)}/search?${params.toString()}`,
    options.signal === undefined ? undefined : { signal: options.signal }
  );
}

export function reopenTask(taskId: string): Promise<TaskDto> {
  return request<TaskDto>(`/api/tasks/${encodeURIComponent(taskId)}/reopen`, {
    method: 'POST'
  });
}

export function cancelReopenTask(taskId: string): Promise<TaskDto> {
  return request<TaskDto>(`/api/tasks/${encodeURIComponent(taskId)}/reopen/cancel`, {
    method: 'POST'
  });
}

export function fetchDeliverables(
  botId: string,
  options: { limit?: number; signal?: AbortSignal } = {}
): Promise<DeliverableDto[]> {
  const params = new URLSearchParams();
  params.set('limit', String(options.limit ?? 20));
  return request<DeliverableDto[]>(
    `/api/bots/${encodeURIComponent(botId)}/deliverables?${params.toString()}`,
    options.signal === undefined ? undefined : { signal: options.signal }
  );
}

export function fetchDeliverable(id: string, signal?: AbortSignal): Promise<DeliverableDto> {
  return request<DeliverableDto>(`/api/deliverables/${encodeURIComponent(id)}`, {
    ...(signal === undefined ? {} : { signal })
  });
}

export function deliverableContentUrl(id: string): string {
  return appPath(`/api/deliverables/${encodeURIComponent(id)}/content`);
}

/** Inline image from one bot workspace; `path` is relative to that workspace. */
export function botFileContentUrl(botId: string, path: string): string {
  const params = new URLSearchParams({ path });
  return appPath(`/api/bots/${encodeURIComponent(botId)}/files/content?${params.toString()}`);
}

export function botFileTextUrl(botId: string, path: string): string {
  const params = new URLSearchParams({ path });
  return appPath(`/api/bots/${encodeURIComponent(botId)}/files/text?${params.toString()}`);
}

/** Reads a Markdown file (MAP.md) from one bot workspace. */
export async function fetchBotFileText(
  botId: string,
  path: string,
  signal?: AbortSignal
): Promise<string> {
  const response = await fetch(botFileTextUrl(botId, path), {
    headers: { accept: 'text/markdown' },
    ...(signal === undefined ? {} : { signal })
  });
  if (!response.ok) throw await readError(response);
  return response.text();
}

export async function fetchDeliverableText(id: string, signal?: AbortSignal): Promise<string> {
  const response = await fetch(deliverableContentUrl(id), {
    headers: { accept: 'text/plain' },
    ...(signal === undefined ? {} : { signal })
  });
  if (!response.ok) throw await readError(response);
  return response.text();
}

export function revealDeliverable(id: string): Promise<{ ok: boolean }> {
  return request<{ ok: boolean }>(`/api/deliverables/${encodeURIComponent(id)}/reveal`, {
    method: 'POST'
  });
}

export function suggestFollowup(botId: string, signal: AbortSignal) {
  return request<{draft: string | null}>(`/api/bots/${encodeURIComponent(botId)}/followup-suggestion`, {
    method: 'POST', body: '{}', signal
  });
}

export function postMessage(
  botId: string,
  text: string,
  attachments: readonly MessageAttachmentDto[] = [],
  deferIfBusy=false
): Promise<MessageAccepted & {queued?:boolean}> {
  const body = attachments.length === 0 ? { text } : { text, attachments };
  return request<MessageAccepted>(`/api/bots/${encodeURIComponent(botId)}/messages`, {
    method: 'POST',
    body: JSON.stringify(deferIfBusy?{...body,deferIfBusy}:body)
  });
}

/** Uploads raw bytes; the file name travels in `X-File-Name` (percent-encoded). */
export async function uploadBotFile(
  botId: string,
  file: File,
  signal?: AbortSignal
): Promise<MessageAttachmentDto> {
  const response = await fetch(appPath(`/api/bots/${encodeURIComponent(botId)}/uploads`), {
    method: 'POST',
    headers: {
      accept: 'application/json',
      'content-type': file.type === '' ? 'application/octet-stream' : file.type,
      'x-file-name': encodeURIComponent(file.name)
    },
    body: file,
    ...(signal === undefined ? {} : { signal })
  });
  if (!response.ok) throw await readError(response);
  return (await response.json()) as MessageAttachmentDto;
}

export function revealBotPath(botId: string, path: string): Promise<{ ok: boolean }> {
  const params = new URLSearchParams({ path });
  return request<{ ok: boolean }>(
    `/api/bots/${encodeURIComponent(botId)}/reveal?${params.toString()}`,
    { method: 'POST' }
  );
}

export function retryTask(taskId: string): Promise<MessageAccepted> {
  return request<MessageAccepted>(`/api/tasks/${encodeURIComponent(taskId)}/retry`, {
    method: 'POST'
  });
}

export function fetchChivesStatus(signal?: AbortSignal): Promise<ChivesStatusDto> {
  return request<ChivesStatusDto>('/api/status', {
    ...(signal === undefined ? {} : { signal })
  });
}

export function cancelBot(botId: string): Promise<CancelAccepted> {
  return request<CancelAccepted>(`/api/bots/${encodeURIComponent(botId)}/cancel`, {
    method: 'POST'
  });
}

export function decideApproval(
  approvalId: string,
  decision: 'allow' | 'reject'
): Promise<ApprovalDto> {
  return request<ApprovalDto>(`/api/approvals/${encodeURIComponent(approvalId)}`, {
    method: 'POST',
    body: JSON.stringify({ decision })
  });
}


export function listRoutines(botId: string, signal?: AbortSignal): Promise<RoutineDto[]> {
  return request<RoutineDto[]>(`/api/bots/${encodeURIComponent(botId)}/routines`, {
    ...(signal === undefined ? {} : { signal })
  });
}

export function updateRoutine(id: string, patch: { enabled: boolean }): Promise<RoutineDto> {
  return request<RoutineDto>(`/api/routines/${encodeURIComponent(id)}`, {
    method: 'PATCH',
    body: JSON.stringify(patch)
  });
}

export function deleteRoutine(id: string): Promise<{ ok: boolean; id: string }> {
  return request(`/api/routines/${encodeURIComponent(id)}`, { method: 'DELETE' });
}

export function runRoutine(id: string): Promise<{ taskId: string; messageId: string }> {
  return request(`/api/routines/${encodeURIComponent(id)}/run`, { method: 'POST' });
}

export function fetchAlertEvents(limit = 50, signal?: AbortSignal): Promise<AlertEventDto[]> {
  return request<AlertEventDto[]>(`/api/alerts/events?limit=${limit}`, {
    ...(signal === undefined ? {} : { signal })
  });
}

export function fetchProactiveSettings(
  signal?: AbortSignal
): Promise<ProactiveSettingsDto> {
  return request<ProactiveSettingsDto>('/api/settings/proactive', {
    ...(signal === undefined ? {} : { signal })
  });
}

export function saveProactiveSettings(
  patch: Partial<ProactiveSettingsDto>
): Promise<ProactiveSettingsDto> {
  return request<ProactiveSettingsDto>('/api/settings/proactive', {
    method: 'PUT',
    body: JSON.stringify(patch)
  });
}

export function fetchSettingsProfile(signal?: AbortSignal): Promise<SettingsProfileDto> {
  return request<SettingsProfileDto>('/api/settings/profile', {
    ...(signal === undefined ? {} : { signal })
  });
}

export function updateSettingsProfile(
  fields: Record<string, unknown>
): Promise<SettingsProfileDto> {
  return request<SettingsProfileDto>('/api/settings/profile', {
    method: 'PUT',
    body: JSON.stringify({ fields })
  });
}

export function clearSettingsProfile(fields: string[]): Promise<SettingsProfileDto> {
  return request<SettingsProfileDto>('/api/settings/profile', {
    method: 'DELETE',
    body: JSON.stringify({ fields })
  });
}

export function fetchAppearance(signal?: AbortSignal): Promise<AppearanceSettingsDto> {
  return request<AppearanceSettingsDto>('/api/settings/appearance', {
    ...(signal === undefined ? {} : { signal })
  });
}

export function saveAppearance(
  patch: Partial<AppearanceSettingsDto>
): Promise<AppearanceSettingsDto> {
  return request<AppearanceSettingsDto>('/api/settings/appearance', {
    method: 'PUT',
    body: JSON.stringify(patch)
  });
}

export function fetchModelSettings(signal?: AbortSignal): Promise<ModelSettingsDto> {
  return request<ModelSettingsDto>('/api/settings/models', {
    ...(signal === undefined ? {} : { signal })
  });
}

export function saveDefaultModel(value: string | null): Promise<ModelSettingsDto> {
  return request<ModelSettingsDto>('/api/settings/models', {
    method: 'PUT',
    body: JSON.stringify({ value })
  });
}

export function fetchModelProvider(signal?: AbortSignal): Promise<ModelProviderDto> {
  return request<ModelProviderDto>('/api/settings/model-provider', {
    ...(signal === undefined ? {} : { signal })
  });
}

/** `apiKey`: empty or omitted keeps the saved key. */
export function saveModelProvider(
  fields: Omit<ModelProviderDto, 'keyConfigured' | 'active'> & { apiKey?: string }
): Promise<ModelProviderDto> {
  return request<ModelProviderDto>('/api/settings/model-provider', {
    method: 'PUT',
    body: JSON.stringify(fields)
  });
}

export function clearModelProvider(): Promise<ModelProviderDto> {
  return request<ModelProviderDto>('/api/settings/model-provider', { method: 'DELETE' });
}

export function fetchRuntimeSettings(signal?: AbortSignal): Promise<RuntimeSettingsDto> {
  return request<RuntimeSettingsDto>('/api/settings/runtime', {
    ...(signal === undefined ? {} : { signal })
  });
}

export function fetchManagedRoutines(signal?: AbortSignal): Promise<ActiveRoutineDto[]> {
  return request('/api/settings/routines?scope=all', signal ? { signal } : {});
}

export function toggleAllRoutines(enabled: boolean): Promise<ActiveRoutineDto[]> {
  return request('/api/settings/routines?scope=all', {method:'PATCH', body:JSON.stringify({enabled})});
}

export function fetchDataLocation(signal?: AbortSignal): Promise<DataLocationDto> {
  return request<DataLocationDto>('/api/settings/data', {
    ...(signal === undefined ? {} : { signal })
  });
}

export function revealDataLocation(): Promise<{ ok: boolean }> {
  return request<{ ok: boolean }>('/api/settings/data/reveal', { method: 'POST' });
}

export function exportDownloadUrl(): string {
  return appPath('/api/export');
}

export function fetchWatches(
  botId: string | undefined,
  status: 'active' | 'all' = 'active',
  signal?: AbortSignal
): Promise<WatchDto[]> {
  const params = new URLSearchParams();
  if (botId !== undefined) params.set('botId', botId);
  params.set('status', status);
  return request<WatchDto[]>(`/api/watches?${params.toString()}`, {
    ...(signal === undefined ? {} : { signal })
  });
}

export function fetchWatch(id: string, signal?: AbortSignal): Promise<WatchDetailDto> {
  return request<WatchDetailDto>(`/api/watches/${encodeURIComponent(id)}`, {
    ...(signal === undefined ? {} : { signal })
  });
}

export function cancelWatch(id: string): Promise<{ ok: boolean; watch: WatchDto }> {
  return request<{ ok: boolean; watch: WatchDto }>(
    `/api/watches/${encodeURIComponent(id)}/cancel`,
    { method: 'POST' }
  );
}

export function fetchNotifications(
  options: { botId?: string; unreadOnly?: boolean; allUnread?: boolean; limit?: number; signal?: AbortSignal } = {}
): Promise<NotificationDto[]> {
  const params = new URLSearchParams({ limit: String(options.limit ?? 50) });
  if (options.allUnread) params.set('unread', 'all');
  else if (options.unreadOnly === true) params.set('unread', '1');
  if (options.botId !== undefined) params.set('botId', options.botId);
  return request<NotificationDto[]>(`/api/notifications?${params.toString()}`, {
    ...(options.signal === undefined ? {} : { signal: options.signal })
  });
}

export function markNotificationRead(id: string): Promise<NotificationDto> {
  return request<NotificationDto>(`/api/notifications/${encodeURIComponent(id)}/read`, {
    method: 'POST'
  });
}

export function markAllNotificationsRead(): Promise<{ ok: boolean; count: number }> {
  return request<{ ok: boolean; count: number }>('/api/notifications/read-all', {
    method: 'POST'
  });
}

export function fetchDashboardMarket(signal?: AbortSignal): Promise<MarketDashboardDto> {
  return request<MarketDashboardDto>(
    '/api/dashboard/market',
    signal === undefined ? undefined : { signal }
  );
}

export function fetchDashboardPortfolio(signal?: AbortSignal): Promise<PortfolioDashboardDto> {
  return request<PortfolioDashboardDto>(
    '/api/dashboard/portfolio',
    signal === undefined ? undefined : { signal }
  );
}

export function fetchStrategyPools(
  strategyId: string,
  botId: string,
  date?: string,
  signal?: AbortSignal
): Promise<StrategyPoolsDto> {
  const params = new URLSearchParams({ botId });
  if (date !== undefined && date !== '') params.set('date', date);
  return request<StrategyPoolsDto>(
    `/api/strategies/${encodeURIComponent(strategyId)}/pools?${params.toString()}`,
    signal === undefined ? undefined : { signal }
  );
}

export interface ConversationHit {
  messageId: string; botId: string; createdAt: string; snippet: string;
}
export function findConversations(q: string, offset: number, signal: AbortSignal) {
  const query = new URLSearchParams({q,offset:String(offset)});
  return request<{hits:ConversationHit[];more:boolean}>(`/api/conversations/search?${query}`,{signal});
}
export function saveBotOrder(ids: string[]) {
  return request<{ids:string[]}>('/api/sidebar/order',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({ids})});
}
