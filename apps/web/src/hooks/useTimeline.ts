import { useCallback, useEffect, useReducer, useRef, useState } from 'react';

import type {
  MessageDto,
  ServerEvent,
  TaskDto,
  TimelinePage,
  ToolEventDto
} from '@chives/server/protocol';

import { fetchTimeline } from '../api/client';

export interface DraftState {
  taskId: string;
  text: string;
  reasoning?:string;
  committed: boolean;
}

export interface TimelineState {
  status: 'idle' | 'loading' | 'ready' | 'error';
  botId: string | null;
  messages: MessageDto[];
  tasks: Record<string, TaskDto>;
  toolEvents: Record<string, ToolEventDto[]>;
  draft: DraftState | null;
  hasMore: boolean;
  nextBeforeSeq: number | null;
  loadingOlder: boolean;
  error: string | null;
}

export const initialTimelineState: TimelineState = {
  status: 'idle',
  botId: null,
  messages: [],
  tasks: {},
  toolEvents: {},
  draft: null,
  hasMore: false,
  nextBeforeSeq: null,
  loadingOlder: false,
  error: null
};

export type TimelineAction =
  | { type: 'reset'; botId: string | null }
  | { type: 'loading' }
  | { type: 'page'; page: TimelinePage }
  | { type: 'error'; message: string }
  | { type: 'olderStart' }
  | { type: 'olderError' }
  | { type: 'event'; event: ServerEvent };

function bySeq(left: MessageDto, right: MessageDto): number {
  return left.seq - right.seq;
}

function mergeMessages(current: MessageDto[], incoming: MessageDto[]): MessageDto[] {
  const byId = new Map<string, MessageDto>();
  for (const message of current) byId.set(message.id, message);
  for (const message of incoming) byId.set(message.id, message);
  return [...byId.values()].sort(bySeq);
}

function groupTools(events: readonly ToolEventDto[]): Record<string, ToolEventDto[]> {
  const grouped: Record<string, ToolEventDto[]> = {};
  for (const event of events) {
    const list = grouped[event.taskId] ?? [];
    list.push(event);
    grouped[event.taskId] = list;
  }
  for (const list of Object.values(grouped)) {
    list.sort((left, right) => left.startedAt.localeCompare(right.startedAt));
  }
  return grouped;
}

function mergeTools(
  current: Record<string, ToolEventDto[]>,
  incoming: readonly ToolEventDto[]
): Record<string, ToolEventDto[]> {
  const grouped = groupTools(incoming);
  const next: Record<string, ToolEventDto[]> = {};
  for (const [taskId, tools] of Object.entries(current)) {
    next[taskId] = [...tools];
  }
  for (const [taskId, tools] of Object.entries(grouped)) {
    const byId = new Map<string, ToolEventDto>();
    for (const tool of next[taskId] ?? []) byId.set(tool.id, tool);
    for (const tool of tools) byId.set(tool.id, tool);
    next[taskId] = [...byId.values()].sort((left, right) =>
      left.startedAt.localeCompare(right.startedAt)
    );
  }
  return next;
}

function upsertTool(
  current: Record<string, ToolEventDto[]>,
  taskId: string,
  tool: ToolEventDto
): Record<string, ToolEventDto[]> {
  const list = current[taskId] ?? [];
  const index = list.findIndex((item) => item.id === tool.id || item.toolCallId === tool.toolCallId);
  const nextList = index === -1 ? [...list, tool] : list.map((item, at) => (at === index ? tool : item));
  nextList.sort((left, right) => left.startedAt.localeCompare(right.startedAt));
  return { ...current, [taskId]: nextList };
}

function mergeTasks(current: Record<string, TaskDto>, incoming: readonly TaskDto[]): Record<string, TaskDto> {
  const next = { ...current };
  for (const task of incoming) next[task.id] = task;
  return next;
}

/** A delegated child's events are published under the root bot; its drafts belong in the delegation row, not the main draft. */
function isDelegatedTask(state: TimelineState, taskId: string): boolean {
  if (state.tasks[taskId]?.delegated === true) return true;
  return state.messages.some(
    (message) => message.kind === 'delegation' && message.meta?.['childTaskId'] === taskId
  );
}

function applyDraftEvent(state: TimelineState, event: ServerEvent): DraftState | null {
  if (
    (event.type === 'draft.reset' || event.type === 'draft.delta' || event.type === 'draft.commit') &&
    isDelegatedTask(state, event.taskId)
  ) {
    return state.draft;
  }
  switch (event.type) {
    case 'draft.reset':
      return { taskId: event.taskId, text: '', committed: false };
    case 'draft.delta': {
      if(event.kind==='reasoning' && document.documentElement.dataset.showProcess==='true'){
        const current=state.draft?.taskId===event.taskId?state.draft:{taskId:event.taskId,text:'',committed:false};
        return {...current,reasoning:((current.reasoning??'')+event.text).slice(-12000)};
      }
      if (event.kind !== 'text') return state.draft;
      const current = state.draft;
      if (current === null || current.taskId !== event.taskId || current.committed) {
        return { taskId: event.taskId, text: event.text, committed: false };
      }
      return { ...current, text: current.text + event.text };
    }
    case 'draft.commit': {
      const current = state.draft;
      if (current === null || current.taskId !== event.taskId) {
        return { taskId: event.taskId, text: event.text, committed: true };
      }
      return { ...current, text: event.text === '' ? current.text : event.text, committed: true };
    }
    case 'message.created':
      return event.message.role === 'bot' ? null : state.draft;
    default:
      return state.draft;
  }
}

export function timelineReducer(state: TimelineState, action: TimelineAction): TimelineState {
  switch (action.type) {
    case 'reset':
      return { ...initialTimelineState, botId: action.botId };
    case 'loading':
      return { ...state, status: 'loading', error: null };
    case 'page': {
      const { page } = action;
      const messages = mergeMessages(state.messages, page.messages);
      const tasks = mergeTasks(state.tasks, page.tasks);
      const toolEvents = mergeTools(state.toolEvents, page.toolEvents);
      return {
        ...state,
        status: 'ready',
        messages,
        tasks,
        toolEvents,
        hasMore: page.hasMore,
        nextBeforeSeq: page.nextBeforeSeq,
        loadingOlder: false,
        error: null
      };
    }
    case 'error':
      return { ...state, status: state.messages.length > 0 ? 'ready' : 'error', error: action.message, loadingOlder: false };
    case 'olderStart':
      return { ...state, loadingOlder: true };
    case 'olderError':
      return { ...state, loadingOlder: false };
    case 'event': {
      const event = action.event;
      switch (event.type) {
        case 'message.created': {
          const messages = mergeMessages(state.messages, [event.message]);
          return { ...state, messages, draft: applyDraftEvent(state, event) };
        }
        case 'task.started':
        case 'task.updated':
        case 'task.closed':
          return { ...state, tasks: mergeTasks(state.tasks, [event.task]) };
        case 'delegation.updated': {
          const delegation = event.delegation;
          const messages = state.messages.map((message) => {
            const id = message.meta?.delegationId;
            if (id !== delegation.delegationId) return message;
            return { ...message, meta: { ...message.meta, ...delegation } };
          });
          const tasks =
            event.task === undefined ? state.tasks : mergeTasks(state.tasks, [event.task]);
          return { ...state, messages, tasks };
        }
        case 'tool.started':
          return { ...state, toolEvents: upsertTool(state.toolEvents, event.taskId, event.tool) };
        case 'tool.ended':
          return { ...state, toolEvents: upsertTool(state.toolEvents, event.taskId, event.tool) };
        case 'approval.decided': {
          const messages = state.messages.map((message) =>
            message.meta?.['approvalId'] === event.approval.id
              ? {
                  ...message,
                  meta: {
                    ...message.meta,
                    ...event.approval,
                    approvalId: event.approval.id,
                    decision: event.approval.decision,
                    decidedAt: event.approval.decidedAt,
                    decidedBy: event.approval.decidedBy
                  }
                }
              : message
          );
          return { ...state, messages };
        }
        case 'draft.reset':
        case 'draft.delta':
        case 'draft.commit':
          return { ...state, draft: applyDraftEvent(state, event) };
        default:
          return state;
      }
    }
    default:
      return state;
  }
}

export interface TimelineController {
  state: TimelineState;
  applyEvent: (event: ServerEvent) => void;
  loadOlder: () => void;
  reload: () => void;
}

export function useTimeline(botId: string | null): TimelineController {
  const [state, dispatch] = useReducer(timelineReducer, initialTimelineState);
  const botIdRef = useRef<string | null>(botId);
  botIdRef.current = botId;
  const controllerRef = useRef<AbortController | null>(null);
  const loadingOlderRef = useRef(false);
  const [reloadToken, setReloadToken] = useState(0);

  useEffect(() => {
    controllerRef.current?.abort();
    loadingOlderRef.current = false;
    if (botId === null) {
      dispatch({ type: 'reset', botId: null });
      return;
    }
    const controller = new AbortController();
    controllerRef.current = controller;
    dispatch({ type: 'reset', botId });
    dispatch({ type: 'loading' });
    void fetchTimeline(botId, { signal: controller.signal })
      .then((page) => {
        if (!controller.signal.aborted) dispatch({ type: 'page', page });
      })
      .catch((cause: unknown) => {
        if (controller.signal.aborted) return;
        dispatch({ type: 'error', message: cause instanceof Error ? cause.message : '时间线加载失败' });
      });
    return () => {
      controller.abort();
    };
  }, [botId, reloadToken]);

  const applyEvent = useCallback((event: ServerEvent) => {
    if (event.botId === botIdRef.current) dispatch({ type: 'event', event });
  }, []);

  const loadOlder = useCallback(() => {
    if (botId === null || loadingOlderRef.current) return;
    if (!state.hasMore || state.nextBeforeSeq === null || state.status !== 'ready') return;
    loadingOlderRef.current = true;
    dispatch({ type: 'olderStart' });
    const controller = new AbortController();
    controllerRef.current = controller;
    void fetchTimeline(botId, { beforeSeq: state.nextBeforeSeq, signal: controller.signal })
      .then((page) => {
        if (!controller.signal.aborted) dispatch({ type: 'page', page });
      })
      .catch(() => {
        if (!controller.signal.aborted) dispatch({ type: 'olderError' });
      })
      .finally(() => {
        loadingOlderRef.current = false;
      });
  }, [botId, state.hasMore, state.nextBeforeSeq, state.status]);

  const reload = useCallback(() => setReloadToken((value) => value + 1), []);

  return { state, applyEvent, loadOlder, reload };
}
