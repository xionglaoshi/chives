import { BotWorkbench } from './components/BotWorkbench';
import { useFollowupSuggestion } from './hooks/useFollowupSuggestion';
import {initializationPrompts,useInitialization,type InitializationStep} from './components/DockInitialization';
import { Hotspots } from './components/Hotspots';
import { DashboardBotMessagesDemo } from './components/DashboardBotMessagesDemo';
import { DashboardBotMessages } from './components/DashboardBotMessages';
import { MarketBoard } from './components/MarketBoard';
import {StyleAssessment} from './components/StyleAssessment';
import {portraitDescription} from './components/SettingsNav';
import {Watchlist} from './components/Watchlist';
import {Holdings} from './components/Holdings';
import { workbenchTools } from './utils/routes';
import { saveBotOrder } from './api/client';
import {desk,applyDesk,type Preferences} from './components/deskApi';
import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { DragEvent, ReactElement } from 'react';

import type {
  BotSummary,
  DeliverableDto,
  MessageAttachmentDto,
  NotificationDto,
  ProactiveSettingsDto,
  SearchTaskGroup,
  ServerEvent
} from '@chives/server/protocol';

import {
  ApiError,
  cancelBot,
  cancelWatch,
  fetchNotifications,
  fetchProactiveSettings,
  markAllNotificationsRead,
  markNotificationRead,
  cancelReopenTask,
  decideApproval,
  deleteRoutine,
  postMessage,
  reopenTask,
  retryTask,
  revealBotPath,
  updateRoutine,
  uploadBotFile
} from './api/client';
import { BotProfile } from './components/BotProfile';
import { BotsOverview } from './components/BotsOverview';
import { ResponsiveNavigation } from './components/ResponsiveNavigation';
import { Dock } from './components/Dock';
import { Composer } from './components/Composer';
import { DeliverablePreview } from './components/DeliverablePreview';
import { SearchOverlay } from './components/SearchOverlay';
import { ServiceBanner } from './components/ServiceBanner';
import { Settings } from './components/Settings';
import { Sidebar } from './components/Sidebar';
import { Timeline, type PendingMessage } from './components/Timeline';
import { Welcome } from './components/Welcome';
import { useBots } from './hooks/useBots';
import { useEventStream } from './hooks/useEventStream';
import { useTimeline } from './hooks/useTimeline';
import { applyAppearance, watchSystemTheme } from './theme/appearance';
import { defaultBotId, isBotRunning } from './utils/bots';
import { readRoute, routeHash, routeKey, type AppRoute } from './utils/routes';
import './App.css';

const MAX_UPLOAD_BYTES = 20 * 1024 * 1024;
const MAX_ATTACHMENTS = 10;
const ALLOWED_UPLOAD_EXTENSIONS = new Set([
  'pdf',
  'md',
  'txt',
  'csv',
  'tsv',
  'json',
  'xlsx',
  'xls',
  'docx',
  'pptx',
  'png',
  'jpg',
  'jpeg',
  'webp',
  'gif'
]);

function uploadExtension(name: string): string {
  const dot = name.lastIndexOf('.');
  return dot <= 0 ? '' : name.slice(dot + 1).toLowerCase();
}

function uploadError(files: readonly File[], existing: number): string | null {
  if (existing + files.length > MAX_ATTACHMENTS) {
    return `一条消息最多 ${MAX_ATTACHMENTS} 个文件`;
  }
  for (const file of files) {
    const extension = uploadExtension(file.name);
    if (!ALLOWED_UPLOAD_EXTENSIONS.has(extension)) {
      return `不支持的文件类型：${file.name}（允许 pdf、md、txt、csv、tsv、json、xlsx、xls、docx、pptx 和图片）`;
    }
    if (file.size > MAX_UPLOAD_BYTES) {
      return `${file.name} 超过 20 MB，未上传`;
    }
  }
  return null;
}

let pendingCounter = 0;

function newPendingId(): string {
  pendingCounter += 1;
  return `pending-${Date.now()}-${pendingCounter}`;
}

function TimelineSkeleton(): ReactElement {
  return (
    <div className="timeline-skeleton" role="status" aria-label="时间线加载中" aria-busy="true">
      <div className="timeline-skeleton__row timeline-skeleton__row--short">
        <span className="skeleton timeline-skeleton__bubble" />
      </div>
      <div className="timeline-skeleton__row">
        <span className="skeleton timeline-skeleton__block" />
      </div>
      <div className="timeline-skeleton__row timeline-skeleton__row--short">
        <span className="skeleton timeline-skeleton__bubble" />
      </div>
      <div className="timeline-skeleton__row">
        <span className="skeleton timeline-skeleton__block" />
      </div>
    </div>
  );
}

function MainError({ message, onRetry }: { message: string; onRetry: () => void }): ReactElement {
  return (
    <div className="main-error" role="alert">
      <div className="main-error__title">时间线没有加载出来</div>
      <div className="main-error__message">{message}</div>
      <button type="button" className="main-error__retry" onClick={onRetry}>
        重试
      </button>
    </div>
  );
}

interface PreviewState {
  deliverable: DeliverableDto;
  /** Set for MAP.md, which is read from the workspace instead of the deliverables table. */
  workspaceFile?: { botId: string; path: string };
}

interface ConversationTarget {
  botId: string;
  messageId?: string;
  taskId?: string;
  draft?: string;
  askFile?: File;
}

const GlobalSearch = lazy(() => import('./components/GlobalSearch'));

export function App(): ReactElement {
  const initialization=useInitialization();
  const [initializationFocus,setInitializationFocus]=useState<InitializationStep|null>(null);
  const [briefingReply,setBriefingReply]=useState('');
  const [briefingBusy,setBriefingBusy]=useState(false);
  const [briefingError,setBriefingError]=useState('');

  const { bots, loading, error: serverError, setBots, setBotStatus, reload } = useBots();
  const [route, setRoute] = useState<AppRoute>(() => readRoute(window.location.hash));
  const [composerText, setComposerText] = useState('');
  const [askFile, setAskFile] = useState<File | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [sending, setSending] = useState(false);
  useEffect(()=>{void desk<Preferences>('prefs').then(applyDesk).catch(()=>{});},[]);
  const [attachments, setAttachments] = useState<MessageAttachmentDto[]>([]);
  const [uploading, setUploading] = useState(false);
  const [uploadNotice, setUploadNotice] = useState<string | null>(null);
  const [dragActive, setDragActive] = useState(false);
  const [pendingByBot, setPendingByBot] = useState<Record<string, PendingMessage[]>>({});
  const [preview, setPreview] = useState<PreviewState | null>(null);
  const previewTriggerRef = useRef<HTMLElement | null>(null);
  const [search, setSearch] = useState<'global' | 'timeline' | null>(null);
  const [continuation, setContinuation] = useState<{ taskId: string; title: string } | null>(null);
  const [locateTarget, setLocateTarget] = useState<string | null>(null);
  const [memoryRevision, setMemoryRevision] = useState(0);
  const [highlightMessageId, setHighlightMessageId] = useState<string | null>(null);
  const [composerFocusToken, setComposerFocusToken] = useState(0);
  const [notifications, setNotifications] = useState<NotificationDto[]>([]);
  const [expandedNotifications, setExpandedNotifications] = useState(false);
  const [loadingUnread, setLoadingUnread] = useState(false);
  const [unreadLoadError, setUnreadLoadError] = useState(false);

  async function loadUnreadNotifications() {
    setLoadingUnread(true);
    setUnreadLoadError(false);
    try {
      const unread = await fetchNotifications({ allUnread: true });
      setNotifications(current => {
        const seen = new Set(current.map(entry => entry.id));
        return [...current, ...unread.filter(entry => !seen.has(entry.id))]
          .sort((a, b) => b.createdAt.localeCompare(a.createdAt));
      });
      setExpandedNotifications(true);
    } catch {
      setUnreadLoadError(true);
    } finally {
      setLoadingUnread(false);
    }
  }
  const [proactiveSettings, setProactiveSettings] = useState<ProactiveSettingsDto | null>(null);
  const [locateTaskId, setLocateTaskId] = useState<string | null>(null);
  const [watchRevision, setWatchRevision] = useState(0);

  const hiredBots = useMemo(() => bots.filter(bot => bot.hired !== false), [bots]);
  const selectedId =
    route.name === 'conversation' || route.name === 'profile' ? route.botId : null;
  const selectedBot = useMemo(
    () => bots.find((bot) => bot.id === selectedId) ?? null,
    [bots, selectedId]
  );
  const timeline = useTimeline(selectedBot?.id ?? null);
  const { applyEvent } = timeline;
  const selectedBotIdRef = useRef<string | null>(null);
  selectedBotIdRef.current = selectedId;

  const navigate = useCallback((next: AppRoute, replace = false): void => {
    setRoute(next);
    const hash = routeHash(next);
    if (window.location.hash === hash) return;
    if (replace) window.history.replaceState(null, '', hash);
    else window.history.pushState(null, '', hash);
  }, []);

  useEffect(() => {
    if (bots.length === 0) return;
    if (route.name !== 'conversation' && route.name !== 'profile') return;
    if (route.botId !== null && bots.some((bot) => bot.id === route.botId)) return;
    const fallback = defaultBotId(hiredBots);
    if (fallback !== null) {
      navigate({ name: 'conversation', botId: fallback }, true);
    }
  }, [bots, hiredBots, route, navigate]);

  useEffect(() => {
    const onHashChange = (): void => {
      setRoute(readRoute(window.location.hash));
    };
    window.addEventListener('hashchange', onHashChange);
    return () => window.removeEventListener('hashchange', onHashChange);
  }, []);

  useEffect(() => {
    return watchSystemTheme(() => {
      const root = document.documentElement.dataset;
      if (root['themePreference'] !== 'system') return;
      applyAppearance({
        theme: 'system',
        changeColor: root['changeColor'] === 'green-up' ? 'green-up' : 'red-up'
      });
    });
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    void fetchNotifications({ limit: 50, signal: controller.signal })
      .then((list) => {
        if (!controller.signal.aborted) setNotifications(current => {
          const seen = new Set(current.map(entry => entry.id));
          return [...current, ...list.filter(entry => !seen.has(entry.id))]
            .sort((a, b) => b.createdAt.localeCompare(a.createdAt));
        });
      })
      .catch(() => undefined);
    void fetchProactiveSettings(controller.signal)
      .then((value) => {
        if (!controller.signal.aborted) setProactiveSettings(value);
      })
      .catch(() => undefined);
    return () => controller.abort();
  }, []);

  useEffect(() => {
    const onKeyDown = (event: globalThis.KeyboardEvent): void => {
      const target = event.target;
      const typing =
        target instanceof HTMLElement &&
        (target.tagName === 'INPUT' ||
          target.tagName === 'TEXTAREA' ||
          target.isContentEditable);
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault();
        setSearch('global');
        return;
      }
      if (event.key === '/' && !typing && !event.metaKey && !event.ctrlKey && !event.altKey) {
        event.preventDefault();
        setSearch('global');
      }
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, []);

  const pendingTarget = useRef<ConversationTarget | null>(null);
  const orderSaving = useRef(false);
  const [orderError,setOrderError] = useState('');
  const moveDot = async (source:string,target:string) => {
    if(orderSaving.current || source===target || source==='ceo' || target==='ceo') return;
    const ids=bots.filter(b=>b.id!=='ceo').map(b=>b.id);
    const from=ids.indexOf(source), to=ids.indexOf(target);
    if(from<0 || to<0) return;
    ids.splice(from,1);ids.splice(to,0,source);
    orderSaving.current=true;
    try {
      await saveBotOrder(ids);
      const ranks=new Map(['ceo',...ids].map((id,i)=>[id,i]));
      setBots(list=>[...list].sort((a,b)=>(ranks.get(a.id)??ranks.size)-(ranks.get(b.id)??ranks.size)));
      setOrderError('');
    } catch {setOrderError('排序未保存，请重试。');reload();}
    finally {orderSaving.current=false;}
  };
  const openConversationTarget = useCallback((target: ConversationTarget) => {
    setSearch(null);
    if (route.name !== 'conversation' || selectedId !== target.botId) {
      pendingTarget.current = target;
      navigate({name: 'conversation', botId: target.botId});
      return;
    }
    setPreview(null);
    if (target.messageId) setLocateTarget(target.messageId);
    if (target.taskId) setLocateTaskId(target.taskId);
    if (target.draft !== undefined) {
      setComposerText(target.draft);
      if (target.askFile) {
        setAttachments([]);
        setAskFile(target.askFile);
        setNotice(null);
        setUploadNotice(null);
        setContinuation(null);
      }
      setComposerFocusToken(value => value + 1);
    }
  }, [navigate, route.name, selectedId]);
  const currentRouteKey = routeKey(route);
  useEffect(() => {
    const target = pendingTarget.current?.botId === selectedId ? pendingTarget.current : null;
    pendingTarget.current = null;
    setComposerText(target?.draft ?? '');
    if (target?.draft !== undefined) setComposerFocusToken(value => value + 1);
    setNotice(null);
    setAttachments([]);
    setAskFile(target?.askFile ?? null);
    setUploadNotice(null);
    setDragActive(false);
    setPreview(null);
    setSearch(null);
    setContinuation(null);
    setLocateTarget(target?.messageId ?? null);
    setLocateTaskId(target?.taskId ?? new URLSearchParams(window.location.hash.split('?')[1]).get('task'));
    setHighlightMessageId(null);
    previewTriggerRef.current = null;
  }, [currentRouteKey,selectedId]);

  useEffect(() => {
    if (!askFile || route.name !== 'conversation' || selectedId !== 'ceo') return;
    const request = new AbortController();
    void uploadBotFile('ceo', askFile, request.signal)
      .then(attachment => {
        if (!request.signal.aborted) setAttachments(current => [...current, attachment]);
      })
      .catch(() => {
        if (!request.signal.aborted) setUploadNotice('附件未上传，请返回原页面重新点击「问AI」。');
      })
      .finally(() => {
        if (!request.signal.aborted) setAskFile(null);
      });
    return () => request.abort();
  }, [askFile, route.name, selectedId]);

  const removePending = useCallback((botId: string, pendingId: string) => {
    setPendingByBot((current) => {
      const list = current[botId];
      if (list === undefined) return current;
      const next = list.filter((item) => item.id !== pendingId);
      return { ...current, [botId]: next };
    });
  }, []);

  const markPending = useCallback((botId: string, pendingId: string, status: PendingMessage['status']) => {
    setPendingByBot((current) => {
      const list = current[botId];
      if (list === undefined) return current;
      return {
        ...current,
        [botId]: list.map((item) => (item.id === pendingId ? { ...item, status } : item))
      };
    });
  }, []);

  const addPending = useCallback(
    (botId: string, text: string, attachmentList: readonly MessageAttachmentDto[] = []): string => {
      const id = newPendingId();
      setPendingByBot((current) => ({
        ...current,
        [botId]: [
          ...(current[botId] ?? []),
          { id, text, status: 'sending', attachments: [...attachmentList] }
        ]
      }));
      return id;
    },
    []
  );

  const applyBotUpdate = useCallback(
    (updated: BotSummary): void => {
      setBots((current) =>
        current.some(bot => bot.id === updated.id)
          ? current.map(bot => bot.id === updated.id ? { ...bot, ...updated } : bot)
          : [...current, updated]
      );
    },
    [setBots]
  );

  const openNotification = useCallback(
    async (notification: Pick<NotificationDto, 'id' | 'botId' | 'taskId' | 'readAt'>, messageId?: string, requireRead = false): Promise<void> => {
      if (notification.taskId.startsWith('system:updates.')) window.location.hash='/settings?tab=updates';
      else if (notification.taskId === 'system:doctor') window.location.hash='/settings?tab=kernels';
      else openConversationTarget({botId: notification.botId, ...(messageId ? { messageId } : { taskId: notification.taskId })});
      if (notification.readAt !== null) return;
      const readAt = new Date().toISOString();
      setNotifications((current) =>
        current.map((entry) => (entry.id === notification.id ? { ...entry, readAt } : entry))
      );
      setBots((current) =>
        current.map((bot) =>
          bot.id === notification.botId
            ? { ...bot, unreadNotifications: Math.max(0, (bot.unreadNotifications ?? 0) - 1) }
            : bot
        )
      );
      try {
        await markNotificationRead(notification.id);
      } catch (error) {
        if (requireRead) {
          setNotifications(current => current.map(entry =>
            entry.id === notification.id && entry.readAt === readAt ? { ...entry, readAt: null } : entry));
          setBots(current => current.map(bot => bot.id === notification.botId
            ? { ...bot, unreadNotifications: (bot.unreadNotifications ?? 0) + 1 } : bot));
          throw error;
        }
      }
    },
    [openConversationTarget, setBots]
  );

  const maybeShowBrowserNotification = useCallback(
    (notification: NotificationDto): void => {
      if (typeof Notification === 'undefined' || Notification.permission !== 'granted') return;
      if (proactiveSettings?.browserNotify === false) return;
      if (proactiveSettings?.importantOnly !== false && notification.level === 'info') return;
      if (route.name === 'conversation' && selectedId === notification.botId) return;
      try {
        const popup = new Notification(notification.botName ? `${notification.botName} · ${notification.title}` : notification.title, { body: notification.body });
        popup.onclick = () => {
          window.focus();
          void openNotification(notification);
        };
      } catch {
        // Some browsers refuse Notification construction outside a user gesture.
      }
    },
    [openNotification, proactiveSettings, route.name, selectedId]
  );

  const handleEvent = useCallback(
    (event: ServerEvent) => {
      applyEvent(event);
      if (event.type === 'bot.status') {
        setBotStatus(event.botId, { status: event.status, runningTaskId: event.runningTaskId });
        // Idle is when a report-back child count becomes visible in the bot list.
        if (event.status === 'idle') reload();
      } else if (event.type === 'delegation.updated' || event.type === 'roster.changed') {
        reload();
      } else if (event.type === 'bot.updated') {
        applyBotUpdate(event.bot);
      } else if (event.type === 'memory.updated') {
        setBots((current) =>
          current.map((bot) =>
            bot.id === event.botId
              ? {
                  ...bot,
                  memoryCount: event.count,
                  memoryUpdatedAt: event.memory?.writtenAt ?? new Date().toISOString()
                }
              : bot
          )
        );
        setMemoryRevision((value) => value + 1);
      } else if (event.type === 'approval.requested') {
        setBotStatus(event.botId, { status: 'awaiting_approval' });
        reload();
      } else if (event.type === 'approval.decided') {
        reload();
      } else if (event.type === 'message.created' && event.message.role === 'user') {
        setPendingByBot((current) => {
          const list = current[event.botId];
          if (list === undefined) return current;
          const index = list.findIndex((item) => item.text === event.message.content);
          if (index === -1) return current;
          return { ...current, [event.botId]: list.filter((_, at) => at !== index) };
        });
      } else if (event.type === 'notification.created') {
        setNotifications((current) =>
          current.some((entry) => entry.id === event.notification.id)
            ? current
            : [event.notification, ...current].filter((entry, index) => index < 50 || entry.readAt === null)
        );
        setBots((current) =>
          current.map((bot) =>
            bot.id === event.notification.botId
              ? { ...bot, unreadNotifications: (bot.unreadNotifications ?? 0) + 1 }
              : bot
          )
        );
        maybeShowBrowserNotification(event.notification);
      } else if (event.type === 'watch.created' || event.type === 'watch.updated') {
        setWatchRevision((value) => value + 1);
        reload();
      }
    },
    [applyBotUpdate, applyEvent, maybeShowBrowserNotification, reload, setBots, setBotStatus]
  );

  const handleDecideApproval = useCallback(
    async (approvalId: string, decision: 'allow' | 'reject'): Promise<void> => {
      await decideApproval(approvalId, decision);
      timeline.reload();
      reload();
    },
    [timeline.reload, reload]
  );

  const handleEnableRoutine = useCallback(async (routineId: string): Promise<void> => {
    await updateRoutine(routineId, { enabled: true });
    timeline.reload();
    reload();
  }, [timeline.reload, reload]);

  const handleDismissRoutine = useCallback(async (routineId: string): Promise<void> => {
    await deleteRoutine(routineId);
    timeline.reload();
    reload();
  }, [timeline.reload, reload]);

  const markAllRead = useCallback(async (): Promise<void> => {
    const readAt = new Date().toISOString();
    setNotifications((current) => current.map((entry) => ({ ...entry, readAt })));
    setBots((current) => current.map((bot) => ({ ...bot, unreadNotifications: 0 })));
    try {
      await markAllNotificationsRead();
    } catch {
      setNotice('标记已读失败，可以再试一次');
    }
  }, [setBots]);

  const handleCancelWatch = useCallback(
    async (watchId: string): Promise<void> => {
      await cancelWatch(watchId);
      await timeline.reload();
      reload();
    },
    [reload, timeline.reload]
  );

  const addFiles = useCallback(
    async (files: readonly File[]): Promise<void> => {
      if (selectedBot === null || selectedBot.hired === false || files.length === 0 || uploading) return;
      const error = uploadError(files, attachments.length);
      if (error !== null) {
        setUploadNotice(error);
        return;
      }
      setUploadNotice(null);
      setUploading(true);
      const uploaded: MessageAttachmentDto[] = [];
      try {
        for (const file of files) {
          uploaded.push(await uploadBotFile(selectedBot.id, file));
        }
      } catch (cause) {
        setUploadNotice(
          cause instanceof Error ? `上传失败：${cause.message}` : '上传失败，可以再试一次'
        );
      } finally {
        setUploading(false);
      }
      if (uploaded.length > 0 && selectedBotIdRef.current === selectedBot.id) {
        setAttachments((current) => [...current, ...uploaded]);
      }
    },
    [attachments.length, selectedBot, uploading]
  );

  const removeAttachment = useCallback((path: string): void => {
    setAttachments((current) => current.filter((attachment) => attachment.path !== path));
  }, []);

  const handleDragOver = (event: DragEvent<HTMLDivElement>): void => {
    if (selectedBot === null) return;
    if (!Array.from(event.dataTransfer?.types ?? []).includes('Files')) return;
    event.preventDefault();
    setDragActive(true);
  };

  const handleDragLeave = (event: DragEvent<HTMLDivElement>): void => {
    const next = event.relatedTarget;
    if (next instanceof Node && event.currentTarget.contains(next)) return;
    setDragActive(false);
  };

  const handleDrop = (event: DragEvent<HTMLDivElement>): void => {
    event.preventDefault();
    setDragActive(false);
    if (selectedBot === null) return;
    const files = Array.from(event.dataTransfer?.files ?? []);
    if (files.length > 0) void addFiles(files);
  };

  const eventStatus = useEventStream(handleEvent);
  const running = selectedBot !== null && isBotRunning(selectedBot);
  const send = useCallback(
    async (
      botId: string,
      text: string,
      existingPendingId?: string,
      attachmentList: readonly MessageAttachmentDto[] = []
    ): Promise<void> => {
      const pendingId = existingPendingId ?? addPending(botId, text, attachmentList);
      if (existingPendingId !== undefined) markPending(botId, pendingId, 'sending');
      setSending(true);
      try {
        const result=await postMessage(botId, text, attachmentList, botId !== selectedId || running);
        removePending(botId, pendingId);
        setContinuation(null);
        setNotice(result.queued?"消息已进入待处理队列":null);
      } catch (cause) {
        if (cause instanceof ApiError && cause.status === 409) {
          removePending(botId, pendingId);
          setNotice('上一个任务还在进行');
          setComposerText(text);
          if (attachmentList.length > 0) setAttachments([...attachmentList]);
        } else {
          markPending(botId, pendingId, 'failed');
          setNotice('发送失败，可以点击消息旁的「重试」');
        }
      } finally {
        setSending(false);
      }
    },
    [addPending, markPending, removePending, running, selectedId]
  );

  function openInitialization(step: InitializationStep) {
    setInitializationFocus(step);
    if(step==='model'||step==='profile'||step==='weixin'){
      window.location.hash='/settings?tab='+({model:'models',profile:'account',weixin:'channels'}[step]);
    }else if(step==='holdings'||step==='watchlist'){
      navigate({name:'workspace',tool:step});
    }else if(step==='portrait'){
      const url=new URL(window.location.href);
      url.searchParams.set('interview','1');
      url.searchParams.set('from','workspace');
      url.hash='';
      window.open(url.toString(),'chives-style-interview');
    }else{
      const botId = step === 'watch' ? 'trader' : 'cio';
      if (!hiredBots.some(bot => bot.id === botId)) {
        navigate({name:'overview'});
        setNotice(step === 'watch' ? '请先聘用盯盘交易员。' : '请先聘用投研总监。');
        return;
      }
      openConversationTarget({botId});
      if(step==='watch')void send(botId,initializationPrompts.watch);
      else if(!initialization.briefingPending){
        void desk<{pending:boolean}>('initial-briefing','POST',{action:'start'})
          .then(result=>{
            initialization.setBriefingPending(result.pending);
            if(result.pending)void send(botId,initializationPrompts.briefing);
          })
          .catch(()=>setNotice('暂时无法打开盘前简报，请重试。'));
      }
    }
  }

  function askOperator(prompt: string, askFile: File) {
    openConversationTarget({botId: 'ceo', draft: prompt, askFile});
  }

  const handleSend = useCallback(
    (text: string): void => {
      if (selectedBot === null || selectedBot.hired === false || askFile !== null) return;
      if (text.trim() === '' && attachments.length === 0) return;
      const outgoing = [...attachments];
      setComposerText('');
      setAttachments([]);
      setUploadNotice(null);
      setNotice(null);
      void send(selectedBot.id, text, undefined, outgoing);
    },
    [askFile, attachments, selectedBot, send]
  );

  const handleSearchReopen = useCallback(async (group: SearchTaskGroup): Promise<void> => {
    await reopenTask(group.taskId);
    setSearch(null);
    setContinuation({ taskId: group.taskId, title: group.title });
    setComposerText('');
    setComposerFocusToken((value) => value + 1);
  }, []);

  const handleLocate = useCallback((messageId: string): void => {
    setSearch(null);
    setLocateTarget(messageId);
  }, []);

  const handleCancelContinuation = useCallback((): void => {
    if (continuation === null) return;
    const taskId = continuation.taskId;
    setContinuation(null);
    void cancelReopenTask(taskId).catch(() => {
      setNotice('取消延续失败，可以再试一次');
    });
  }, [continuation]);

  const handleRetry = useCallback(
    (pending: PendingMessage): void => {
      if (selectedBot === null) return;
      void send(selectedBot.id, pending.text, pending.id, pending.attachments ?? []);
    },
    [selectedBot, send]
  );

  const openDeliverable = useCallback((deliverable: DeliverableDto, trigger: HTMLElement): void => {
    previewTriggerRef.current = trigger;
    setPreview({ deliverable });
  }, []);

  const openAttachment = useCallback(
    (attachment: MessageAttachmentDto, botId: string, trigger: HTMLElement): void => {
      if (attachment.kind === 'image') {
        previewTriggerRef.current = trigger;
        setPreview({
          deliverable: {
            id: `upload-${botId}-${attachment.path}`,
            taskId: '',
            botId,
            path: attachment.path,
            kind: 'image',
            size: attachment.size,
            createdAt: new Date().toISOString()
          },
          workspaceFile: { botId, path: attachment.path }
        });
        return;
      }
      void revealBotPath(botId, attachment.path).catch(() => {
        setNotice('无法在访达中显示这个文件');
      });
    },
    []
  );

  const openWorkspaceMap = useCallback(
    (botId: string): void => {
      previewTriggerRef.current = null;
      setPreview({
        deliverable: {
          id: `workspace-map-${botId}`,
          taskId: '',
          botId,
          path: 'MAP.md',
          kind: 'markdown',
          size: 0,
          createdAt: new Date().toISOString()
        },
        workspaceFile: { botId, path: 'MAP.md' }
      });
    },
    []
  );

  const closePreview = useCallback((): void => {
    setPreview(null);
    const trigger = previewTriggerRef.current;
    previewTriggerRef.current = null;
    if (trigger !== null) {
      window.setTimeout(() => trigger.focus(), 0);
    }
  }, []);

  const handleRetryTask = useCallback(
    async (taskId: string): Promise<void> => {
      try {
        await retryTask(taskId);
        setNotice(null);
        timeline.reload();
      } catch (cause) {
        setNotice(
          cause instanceof ApiError && cause.status === 409
            ? '这个 Bot 还有任务在进行'
            : '重试失败，请稍后再试'
        );
      }
    },
    [timeline.reload]
  );

  const handleStop = useCallback(async (): Promise<void> => {
    if (selectedBot === null) return;
    try {
      await cancelBot(selectedBot.id);
      setNotice(null);
    } catch (cause) {
      if (cause instanceof ApiError && cause.status === 409) {
        setNotice('当前没有正在进行的任务');
      } else {
        setNotice('停止失败，请稍后再试');
      }
    }
  }, [selectedBot]);

  const currentPending = selectedBot === null ? [] : (pendingByBot[selectedBot.id] ?? []);
  const timelineMatchesBot = selectedBot !== null && timeline.state.botId === selectedBot.id;
  const failedTask = useMemo(() => {
    if (selectedBot === null) return null;
    return (
      Object.values(timeline.state.tasks)
        .filter(
          (task) =>
            task.botId === selectedBot.id &&
            (task.status === 'failed' || task.status === 'interrupted')
        )
        .sort((left, right) =>
          (right.endedAt ?? right.startedAt).localeCompare(left.endedAt ?? left.startedAt)
        )[0] ?? null
    );
  }, [selectedBot, timeline.state.tasks]);
  const unreadTotal = notifications.filter((notification) => notification.readAt === null).length;
  const serverUnavailable = serverError !== null;
  const latestFollowupMessage = timelineMatchesBot && timeline.state.status === 'ready'
    ? timeline.state.messages.findLast(message => message.role === 'user' || message.role === 'bot')
    : undefined;
  const followup = useFollowupSuggestion(
    route.name === 'conversation' && selectedBot && selectedBot.hired !== false &&
      !serverUnavailable && !running && !sending && !uploading && !askFile &&
      composerText === '' && attachments.length === 0 ? selectedBot.id : null,
    latestFollowupMessage?.id ?? null
  );
  const showConversation = route.name === 'conversation';
  const showWelcome =
    showConversation &&
    selectedBot !== null &&
    timelineMatchesBot &&
    timeline.state.status === 'ready' &&
    timeline.state.messages.length === 0 &&
    currentPending.length === 0;

  const showTimeline = showConversation && selectedBot !== null && !showWelcome;

  useEffect(() => {
    if (locateTaskId === null) return;
    if (!timelineMatchesBot || timeline.state.status !== 'ready') return;
    const message = timeline.state.messages.find((entry) => entry.taskId === locateTaskId);
    if (message !== undefined) {
      setLocateTarget(message.id);
      setLocateTaskId(null);
      return;
    }
    if (timeline.state.hasMore && !timeline.state.loadingOlder) {
      timeline.loadOlder();
    } else if (!timeline.state.hasMore) {
      setLocateTaskId(null);
      setNotice('这条通知对应的任务不在当前时间线里');
    }
  }, [locateTaskId, timelineMatchesBot, timeline]);

  useEffect(() => {
    if (locateTarget === null) return;
    if (!timelineMatchesBot || timeline.state.status !== 'ready') return;
    if (timeline.state.messages.some((message) => message.id === locateTarget)) {
      setHighlightMessageId(locateTarget);
      setLocateTarget(null);
      return;
    }
    if (timeline.state.hasMore && !timeline.state.loadingOlder) {
      timeline.loadOlder();
    } else if (!timeline.state.hasMore) {
      setNotice('这条消息暂时无法定位，请刷新会话后重试。');
      setLocateTarget(null);
    }
  }, [locateTarget, timelineMatchesBot, timeline]);

  useEffect(() => {
    if (highlightMessageId === null) return;
    const timer = window.setTimeout(() => setHighlightMessageId(null), 2400);
    return () => window.clearTimeout(timer);
  }, [highlightMessageId]);

  return (
    <div className="app" data-initialization-focus={initialization.steps.some(([id])=>id===initializationFocus)?initializationFocus:undefined}>
      <ServiceBanner serverError={serverError} eventStatus={eventStatus} onRetry={reload} />
      <Dock
        initialization={initialization.steps} onInitialize={openInitialization}
        searchOpen={search !== null} onSearch={() => setSearch('global')}
        bots={bots} notifications={notifications.slice(0, 50)} unreadCount={unreadTotal}
        onMarkAllRead={markAllRead} onOpenNotification={notification => void openNotification(notification)}
        watches={{
          revision: watchRevision,
          onEditWatch: (label, botId) => openConversationTarget({botId, draft: `修改盯盘「${label}」：`}),
          onLocateTask: (taskId, botId) => openConversationTarget({botId, taskId}),
          onCancelWatch: handleCancelWatch
        }}
      />
      <div className={`app__body${preview === null ? '' : ' app__body--preview'}`}>
        {route.name !== 'settings' && (
          <ResponsiveNavigation label="工作台导航" shortLabel="导航" closeLabel="关闭导航">
            {(close, phone) => <Sidebar
              bots={hiredBots} selectedId={selectedId} loading={loading}
              compact={preview !== null} phone={phone}
              activeTool={route.name === 'workspace' ? route.tool : null}
              onTool={tool => { close(); navigate({name: 'workspace', tool}); }}
              onMove={(a,b) => void moveDot(a,b)}
              allBotsActive={route.name === 'overview'}
              settingsActive={false}
              onSelect={botId => { close(); navigate({name: 'conversation', botId}); }}
              onShowAll={() => { close(); navigate({name: 'overview'}); }}
              onOpenSettings={() => { close(); navigate({name: 'settings'}); }}
              onHome={close}
            />}
          </ResponsiveNavigation>
        )}

        <main className="main">
          {orderError && <p role="alert">{orderError}</p>}
          {route.name==='workspace' && route.tool==='holdings' && <Holdings onAskExpert={askOperator}/>}
          {route.name==='workspace' && route.tool==='watchlist' && <Watchlist onConversation={()=>openConversationTarget({botId:'cio'})}/> }
          {route.name==='workspace' && route.tool==='portrait' && <section className="desk-settings desk-workspace-portrait"><div className="desk-content"><div className="desk-page">
            <header className="desk-header"><p>工作台</p><h2>{workbenchTools.portrait}</h2><p>{portraitDescription}</p></header>
            <StyleAssessment onAskExpert={askOperator} interviewReturn="workspace"/>
          </div></div></section>}
          {route.name==='workspace' && route.tool==='trends' && <Hotspots onAskExpert={askOperator} />}
          {route.name==='workspace' && route.tool==='market' && <MarketBoard onAskExpert={askOperator} messages={
            import.meta.env.DEV && window.location.hostname === '127.0.0.1' &&
              new URLSearchParams(window.location.search).get('demo') === 'bot-messages'
              ? <DashboardBotMessagesDemo/> : <DashboardBotMessages
            notifications={notifications} bots={bots} expanded={expandedNotifications} loading={loadingUnread}
            error={unreadLoadError} onLoadMore={() => void loadUnreadNotifications()}
            onOpen={notification => void openNotification(notification)}
          />} />}
          {route.name==='workspace' && route.tool!=='market' && route.tool!=='holdings' && route.tool!=='watchlist' && route.tool!=='portrait' && route.tool!=='trends' && <section className="workbench-placeholder"><h1>{workbenchTools[route.tool]}</h1><p>功能开发中</p></section>}
          {route.name === 'settings' ? (
            <Settings onAskExpert={askOperator} initializeModel={initializationFocus==='model'} onModelInitialized={()=>setInitializationFocus(null)}
              onOpenProfile={(botId) => navigate({ name: 'profile', botId, view: 'tools' })}
            />
          ) : null}

          {route.name === 'overview' ? (
            <BotsOverview
              bots={bots}
              loading={loading}
              error={serverError}
              onRetry={reload}
              onPortraitSaved={applyBotUpdate}
              onEmploymentSaved={states => setBots(list => list.map(bot => ({...bot, hired: states.get(bot.id) ?? bot.hired ?? true})))}
              onOpenProfile={(botId, view) => navigate({ name: 'profile', botId, view })}
            />
          ) : null}

          {route.name === 'profile' ? (
            selectedBot === null ? (
              loading ? (
                <TimelineSkeleton />
              ) : (
                <div className="main-error" role="status">
                  还没有这个 Bot 的资料。
                </div>
              )
            ) : (
              <BotProfile
                view={route.view}
                bot={selectedBot}
                onOpenConversation={(botId) =>
                  navigate({ name: 'conversation', botId })
                }
                onOpenDeliverable={openDeliverable}
                onOpenWorkspaceMap={openWorkspaceMap}
                activeDeliverableId={preview?.deliverable.id ?? null}
                memoryRevision={memoryRevision}
              />
            )
          ) : null}

          {showConversation ? (
            selectedBot === null ? (
              loading || serverError !== null ? (
                <TimelineSkeleton />
              ) : (
                <div className="main-error" role="status">
                  还没有可用的 Bot。
                </div>
              )
            ) : (
              <div
                className={`conversation${dragActive ? ' conversation--drag' : ''}`}
                onDragOver={handleDragOver}
                onDragLeave={handleDragLeave}
                onDrop={handleDrop}
              >
                {dragActive ? <div className="conversation__drop">松开以上传文件</div> : null}
                <div className="conversation__body">
                <div className="conversation__chat">
                {selectedBot.id==='cio'&&initialization.briefingPending&&
                  <form className="initial-briefing-confirmation" onSubmit={event=>{
                    event.preventDefault();
                    if(briefingBusy||!briefingReply.trim())return;
                    setBriefingBusy(true);
                    setBriefingError('');
                    void desk('initial-briefing','POST',{action:'confirm',reply:briefingReply})
                      .then(()=>{
                        initialization.setBriefingPending(false);
                        setBriefingReply('');
                        setNotice('盘前简报已启用，默认在 A 股交易日北京时间 08:30。');
                      })
                      .catch(()=>setBriefingError('暂时无法创建盘前简报，请重试。'))
                      .finally(()=>setBriefingBusy(false));
                  }}>
                    <strong>盘前简报</strong>
                    <p>默认在 A 股交易日北京时间 08:30，汇报持仓与关注、机会榜单精选、A股新闻及全球市场新闻。</p>
                    <label>你还想增加什么？
                      <input value={briefingReply} onChange={event=>setBriefingReply(event.target.value)}
                        placeholder="填写追加事项，或回复「没有」" maxLength={1000} required/>
                    </label>
                    <button type="submit" disabled={briefingBusy||!briefingReply.trim()}>提交并创建任务</button>
                    {briefingError&&<p role="alert">{briefingError}</p>}
                  </form>}

                {selectedBot.hired === false ? (
                  <div className="bots-overview__quiet" role="status">这位 Bot 待聘，历史记录可继续查看。
                    <button type="button" className="bots-overview__action" onClick={() => navigate({name:'overview'})}>去Bot市场聘用</button>
                  </div>
                ) : null}
                {selectedBot.status === 'error' && selectedBot.hired !== false ? (
                  <div className="main__bot-error" role="alert">
                    <span>这个 Bot 的运行环境没有启动成功。检查 dsh 是否可用后重试。</span>
                    <button
                      type="button"
                      className="main__bot-error-retry"
                      onClick={() => {
                        if (failedTask === null) reload();
                        else void handleRetryTask(failedTask.id);
                      }}
                    >
                      重试
                    </button>
                  </div>
                ) : null}
                {showWelcome ? (
                  <Welcome
                    value={composerText}
                    onChange={setComposerText}
                    onSend={handleSend}
                    onStop={() => void handleStop()}
                    running={running}
                    sending={sending}
                    notice={notice}
                    focusToken={composerFocusToken}
                    disabled={serverUnavailable || selectedBot.hired === false}
                    disabledReason={selectedBot.hired === false ? "这位 Bot 待聘，聘用后可以继续对话。" : "连不上 Chives 服务，恢复后才能发送。"}
                    botId={selectedBot.id}
                    botName={selectedBot.name}
                    botRole={selectedBot.role}
                    placeholder={`给 ${selectedBot.name} 发消息`}
                    attachments={attachments}
                    onAddFiles={(files) => void addFiles(files)}
                    onRemoveAttachment={removeAttachment}
                    uploading={uploading || askFile !== null}
                    suggesting={followup.loading}
                    suggestion={followup.text}
                    uploadNotice={uploadNotice}
                  />
                ) : null}
                {showTimeline ? (
                  <>
                    {(!timelineMatchesBot || timeline.state.status === 'loading') &&
                    currentPending.length === 0 ? (
                      <TimelineSkeleton />
                    ) : null}
                    {timelineMatchesBot && timeline.state.status === 'error' ? (
                      <MainError
                        message={timeline.state.error ?? '未知错误'}
                        onRetry={timeline.reload}
                      />
                    ) : null}
                    {timelineMatchesBot && timeline.state.status === 'ready' ? (
                      <Timeline
                        botId={selectedBot.id}
                        bots={bots}
                        messages={timeline.state.messages}
                        tasks={timeline.state.tasks}
                        toolEvents={timeline.state.toolEvents}
                        draft={timeline.state.draft}
                        pending={currentPending}
                        hasMore={timeline.state.hasMore}
                        loadingOlder={timeline.state.loadingOlder}
                        onLoadOlder={timeline.loadOlder}
                        onRetryPending={handleRetry}
                        onRetryTask={handleRetryTask}
                        onDecideApproval={handleDecideApproval}
                        onEnableRoutine={handleEnableRoutine}
                        onDismissRoutine={handleDismissRoutine}
                        onCancelWatch={handleCancelWatch}
                        activeDeliverableId={preview?.deliverable.id ?? null}
                        onOpenDeliverable={openDeliverable}
                        onOpenAttachment={(attachment, trigger) =>
                          openAttachment(attachment, selectedBot.id, trigger)
                        }
                        highlightMessageId={highlightMessageId}
                      />
                    ) : null}
                    {timelineMatchesBot && timeline.state.status === 'ready' ? (
                      <div className="main__composer">
                        {continuation === null ? null : (
                          <div className="main__continuation" role="status">
                            <span>接着：{continuation.title}</span>
                            <button
                              type="button"
                              className="main__continuation-cancel"
                              onClick={handleCancelContinuation}
                            >
                              取消
                            </button>
                          </div>
                        )}
                        <Composer
                          value={composerText}
                          onChange={setComposerText}
                          onSend={handleSend}
                          onStop={() => void handleStop()}
                          running={running}
                          sending={sending}
                          notice={notice}
                          focusToken={composerFocusToken}
                          disabled={serverUnavailable || selectedBot.hired === false}
                          disabledReason={selectedBot.hired === false ? "这位 Bot 待聘，聘用后可以继续对话。" : "连不上 Chives 服务，恢复后才能发送。"}
                          botId={selectedBot.id}
                          placeholder={`给 ${selectedBot.name} 发消息`}
                          attachments={attachments}
                          onAddFiles={(files) => void addFiles(files)}
                          onRemoveAttachment={removeAttachment}
                          uploading={uploading || askFile !== null}
                          suggesting={followup.loading}
                          suggestion={followup.text}
                          uploadNotice={uploadNotice}
                        />
                      </div>
                    ) : null}
                  </>
                ) : null}
                </div>
                </div>
              </div>
            )
          ) : null}
        </main>
        {showConversation && selectedBot && <BotWorkbench
          key={selectedBot.id} bot={selectedBot}
          runningTask={timelineMatchesBot && selectedBot.runningTaskId ? timeline.state.tasks[selectedBot.runningTaskId] : undefined}
          watchRevision={watchRevision}
          revision={JSON.stringify([
            selectedBot.runningTaskId, latestFollowupMessage?.id,
            notifications.filter(entry => entry.botId === selectedBot.id).map(entry => [entry.id, entry.readAt]),
          ])}
          previewOpen={preview !== null} onClosePreview={closePreview}
          onLocateTask={id => openConversationTarget({ botId: selectedBot.id, taskId: id })}
          onOpenActivity={entry => {
            if (entry.kind === 'notification') return openNotification({
              id: entry.id, botId: selectedBot.id, taskId: entry.taskId, readAt: entry.readAt,
            }, entry.messageId ?? undefined, true);
            openConversationTarget({ botId: selectedBot.id, ...(entry.messageId ? { messageId: entry.messageId } : { taskId: entry.taskId }) });
          }}
        />}
        {preview !== null ? (
          <DeliverablePreview
            deliverable={preview.deliverable}
            bots={bots}
            workspaceFile={preview.workspaceFile}
            onClose={closePreview}
          />
        ) : null}
      </div>
      {search === 'global' && <Suspense fallback={null}><GlobalSearch
        bots={bots} onLocate={openConversationTarget} onClose={() => setSearch(null)}
        currentBot={showConversation ? selectedBot : null} onTimeline={() => setSearch('timeline')}
      /></Suspense>}
      {search === 'timeline' && selectedBot !== null && showConversation ? (
        <SearchOverlay
          bot={selectedBot}
          onClose={() => setSearch(null)}
          onReopen={handleSearchReopen}
          onLocate={handleLocate}
          onOpenDeliverable={openDeliverable}
        />
      ) : null}
    </div>
  );
}
