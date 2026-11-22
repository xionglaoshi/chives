import { ResponsiveNavigation } from './ResponsiveNavigation';
import {CapabilitiesDesk} from './CapabilitiesDesk';
import {TaskManagement} from './TaskManagement';
import type {AskExpert} from './useExpertAttachment';
import {StyleAssessment} from './StyleAssessment';
import {settingsEnglish,groupNames} from './deskLanguage';
import { appPath } from '../appPath';
import { useEffect, useState } from 'react';
import type { ReactElement } from 'react';

import type {
  AppearanceSettingsDto,
  ChangeColorMode,
  DataLocationDto,
  ProactiveSettingsDto,
  RuntimeSettingsDto,
  SettingsTheme
} from '@chives/server/protocol';

import {
  fetchAppearance,
  fetchDataLocation,
  fetchProactiveSettings,
  fetchRuntimeSettings,
  revealDataLocation,
  saveAppearance,
  saveProactiveSettings,
} from '../api/client';
import { KernelManager } from './KernelManager';
import {ModelsDesk} from './ModelsDesk';
import {ChannelSettings} from './ChannelSettings';
import {Row,ProfileCard,UserHistory,DisplayPrefs,Behavior,Backup,Updates,HelpDesk} from './DeskPanels';
import {desk,applyDesk,type Preferences} from './deskApi';
import {SettingsNav,sections} from './SettingsNav';
import './SettingsDesk.css';
import { applyAppearance, DEFAULT_APPEARANCE, watchSystemTheme } from '../theme/appearance';
import { formatFileSize } from '../utils/deliverables';
import './Settings.css';

const ENGINE_NAMES: Record<number, string> = {
  8865: 'cn-watch（个股盯盘）',
  8866: 'market-watch（大盘与板块）',
  8867: 'chives-hub（信号中枢）'
};

function errorText(error: unknown): string {
  return error instanceof Error ? error.message : '未知错误';
}

function initialAppearance(): AppearanceSettingsDto {
  if (typeof document === 'undefined') return DEFAULT_APPEARANCE;
  const root = document.documentElement.dataset;
  const theme = root['themePreference'];
  const changeColor = root['changeColor'];
  const validTheme =
    theme === 'dark' || theme === 'light' || theme === 'system' ? theme : DEFAULT_APPEARANCE.theme;
  const validColor =
    changeColor === 'red-up' || changeColor === 'green-up'
      ? changeColor
      : DEFAULT_APPEARANCE.changeColor;
  return { theme: validTheme, changeColor: validColor };
}

export interface SettingsProps {
  onAskExpert: AskExpert;
  onOpenProfile: (botId: string) => void;
}

export function Settings({ onOpenProfile,onAskExpert }: SettingsProps): ReactElement {
  const fromHash=()=>window.location.hash.split('?tab=')[1]??'account';
  const [page,select]=useState(fromHash),[prefs,setPrefs]=useState<Preferences|null>(null),[deskError,deskErr]=useState('');
  useEffect(()=>{const update=()=>select(fromHash());window.addEventListener('hashchange',update);
    void desk<Preferences>('prefs').then(v=>{setPrefs(v);applyDesk(v);}).catch(e=>deskErr(e.message));
    return ()=>window.removeEventListener('hashchange',update);},[]);
  const go=(id:string)=>{window.location.hash='/settings?tab='+id;select(id);deskErr('');};
  const save=async(patch:Partial<Preferences>)=>{try{const v=await desk<Preferences>('prefs','PATCH',patch);setPrefs(v);applyDesk(v);deskErr('');}catch(e){deskErr(errorText(e));throw e;}};
  const group=sections.find(g=>g.items.some(item=>item[0]===page))??sections[0]!;
  const item=group.items.find(item=>item[0]===page)??group.items[0]!;
  const [proactive, setProactive] = useState<ProactiveSettingsDto | null>(null);
  const [proactiveError, setProactiveError] = useState<string | null>(null);

  const [runtime, setRuntime] = useState<RuntimeSettingsDto | null>(null);
  const [runtimeError, setRuntimeError] = useState<string | null>(null);
  const [appearance, setAppearance] = useState<AppearanceSettingsDto>(initialAppearance);
  const [appearanceError, setAppearanceError] = useState<string | null>(null);
  const [data, setData] = useState<DataLocationDto | null>(null);
  const [dataError, setDataError] = useState<string | null>(null);
  const [dataBusy, setDataBusy] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    const signal = controller.signal;
    // Requests this effect aborted itself (unmount, StrictMode re-run) are not errors worth showing.
    const report = (set: (message: string) => void) => (error: unknown) => {
      if (!signal.aborted) set(errorText(error));
    };
    void fetchProactiveSettings(signal)
      .then(setProactive)
      .catch(report(setProactiveError));
    void fetchRuntimeSettings(signal)
      .then(setRuntime)
      .catch(report(setRuntimeError));
    void fetchAppearance(signal)
      .then((value) => {
        setAppearance(value);
        applyAppearance(value);
      })
      .catch(report(setAppearanceError));
    void fetchDataLocation(signal)
      .then(setData)
      .catch(report(setDataError));
    return () => controller.abort();
  }, []);

  useEffect(() => {
    applyAppearance(appearance);
  }, [appearance]);

  useEffect(() => {
    if (appearance.theme !== 'system') return undefined;
    return watchSystemTheme(() => applyAppearance(appearance));
  }, [appearance]);

  const saveProactive = async (patch: Partial<ProactiveSettingsDto>): Promise<void> => {
    setProactiveError(null);
    try {
      setProactive(await saveProactiveSettings(patch));
    } catch (error) {
      setProactiveError(errorText(error));
    }
  };

  const toggleBrowserNotify = async (next: boolean): Promise<void> => {
    if (next && typeof Notification !== 'undefined' && Notification.permission !== 'granted') {
      const permission = await Notification.requestPermission();
      if (permission !== 'granted') {
        setProactiveError('浏览器没有授权通知，先在浏览器设置里允许');
        return;
      }
    }
    await saveProactive({ browserNotify: next });
  };

  const changeAppearance = async (patch: Partial<AppearanceSettingsDto>): Promise<void> => {
    const previous = appearance;
    const next = { ...appearance, ...patch };
    setAppearance(next);
    applyAppearance(next);
    setAppearanceError(null);
    try {
      setAppearance(await saveAppearance(patch));
    } catch (error) {
      setAppearance(previous);
      applyAppearance(previous);
      setAppearanceError(errorText(error));
    }
  };

  const handleRevealData = async (): Promise<void> => {
    setDataBusy(true);
    setDataError(null);
    try {
      await revealDataLocation();
    } catch (error) {
      setDataError(errorText(error));
    } finally {
      setDataBusy(false);
    }
  };

  const english=prefs?.locale==='en-US';
  return (
    <div className="desk-settings">
    <ResponsiveNavigation label={english ? 'Settings navigation' : '设置目录'} shortLabel={english ? 'Menu' : '目录'} closeLabel={english ? 'Close menu' : '关闭目录'}>
      {close => <SettingsNav page={page} english={english} go={id => { close(); go(id); }}/>}
    </ResponsiveNavigation>
    <section className="desk-content" key={page}><div className="desk-page"><header className="desk-header"><p>{english?groupNames[group.label]:group.label}</p><h2>{english?settingsEnglish[item[0]!]![0]:item[1]}</h2><p>{english?settingsEnglish[item[0]!]![1]:item[2]}</p></header>
    {deskError&&<p role="alert">{deskError}</p>}
    {page==='account'&&prefs&&<ProfileCard p={prefs} save={save}/>}
    {page==='history'&&<UserHistory/>}
    {page==='channels'&&<ChannelSettings/>}
    {page==='capabilities'&&<CapabilitiesDesk onOpenProfile={onOpenProfile}/>}
    {page==='models'&&<ModelsDesk/>}
    {page==='help'&&<HelpDesk/>}
    {page==='updates'&&prefs&&<Updates auto={prefs.autoUpdateOnCheck} save={save}/>}
    {(page==='chat'||page==='permissions')&&prefs&&<Behavior p={prefs} save={save} page={page}/>}
    {page==='permissions'&&<>
      <Row title="允许Bot开启自动分析" hint="行情、盯盘或定时任务可自动调用模型，每日不限次数。关闭后仍可手动发起分析。">
        <input id="settings-auto-analysis" aria-label="允许Bot开启自动分析" type="checkbox" role="switch"
          checked={proactive?.autoAnalysis ?? false} disabled={proactive === null}
          onChange={event=>void saveProactive({autoAnalysis:event.currentTarget.checked})}/>
      </Row>
      {proactiveError&&<p role="alert">{proactiveError}</p>}
    </>}
    {page==='backup'&&<Backup/>}
    {page==='risk'&&<StyleAssessment onAskExpert={onAskExpert}/>}
        {page==='messages'&&<section className="settings__section" aria-labelledby="settings-proactive">
          <h2 className="settings__section-title" id="settings-proactive">
            主动消息
          </h2>
          {proactiveError === null ? null : (
            <div className="settings__status settings__status--error" role="alert">
              {proactiveError}
            </div>
          )}

          <div className="settings__row">
            <span className="settings__row-text">
              <span className="settings__row-label">允许 Bot 主动发消息</span>
              <span className="settings__row-hint">盘前简报、盯盘提醒等。关掉后只在你提问时回复。</span>
            </span>
            <input
              type="checkbox"
              role="switch"
              aria-label="允许 Bot 主动发消息"
              checked={proactive?.enabled ?? false}
              disabled={proactive === null}
              onChange={event => void saveProactive({ enabled: event.currentTarget.checked })}
            />
          </div>



          <div className="settings__row">
            <span className="settings__row-text">
              <span className="settings__row-label">浏览器通知</span>
              <span className="settings__row-hint">页面打开时用系统通知弹窗；需要浏览器授权。</span>
            </span>
            <input
              type="checkbox"
              role="switch"
              aria-label="浏览器通知"
              checked={proactive?.browserNotify ?? false}
              disabled={proactive === null}
              onChange={event => void toggleBrowserNotify(event.currentTarget.checked)}
            />
          </div>

          <div className="settings__row">
            <span className="settings__row-text">
              <span className="settings__row-label">系统通知</span>
              <span className="settings__row-hint">页面没打开时，在 macOS 通知中心提醒你（默认开）。</span>
            </span>
            <input
              type="checkbox"
              role="switch"
              aria-label="系统通知"
              checked={proactive?.systemNotify ?? false}
              disabled={proactive === null}
              onChange={event => void saveProactive({ systemNotify: event.currentTarget.checked })}
            />
          </div>

          <div className="settings__row">
            <span className="settings__row-text">
              <span className="settings__row-label">只通知重要及以上</span>
              <span className="settings__row-hint">普通消息只进铃铛列表，不弹窗（默认开）。</span>
            </span>
            <input
              type="checkbox"
              role="switch"
              aria-label="只通知重要及以上"
              checked={proactive?.importantOnly ?? false}
              disabled={proactive === null}
              onChange={event => void saveProactive({ importantOnly: event.currentTarget.checked })}
            />
          </div>

        </section>}

    {page==='tasks'&&<TaskManagement proactive={proactive} error={proactiveError}
      onObserve={observeOnly=>saveProactive({observeOnly})} onOpenProfile={onOpenProfile}/>}
        {page==='kernels'&&<><KernelManager/><section className="settings__section" aria-labelledby="settings-runtime">
          <h2 className="settings__section-title" id="settings-runtime">
            模型与运行环境
          </h2>
          {runtimeError === null ? null : (
            <div className="settings__status settings__status--error" role="alert">
              {runtimeError}
            </div>
          )}

          <div className="settings__row settings__row--stack">
            <div className="settings__row-text">
              <span className="settings__row-label">Bot 进程</span>
              <div className="settings__chips">
                {(runtime?.bots ?? []).map((bot) => (
                  <span className={`settings__chip settings__chip--${bot.process}`} key={bot.id}>
                    {bot.name} ·{' '}
                    {bot.process === 'running' ? '运行中' : bot.process === 'error' ? '出错' : '未启动'}
                  </span>
                ))}
                {runtime !== null && runtime.bots.length === 0 ? (
                  <span className="settings__row-hint">没有可用的 Bot</span>
                ) : null}
              </div>
            </div>
          </div>

          <div className="settings__row settings__row--stack">
            <div className="settings__row-text">
              <span className="settings__row-label">数据引擎</span>
              <div className="settings__chips">
                {(runtime?.engines ?? []).map((engine) => (
                  <span
                    className={`settings__chip settings__chip--${engine.healthy ? 'running' : 'not_started'}`}
                    key={engine.port}
                  >
                    {ENGINE_NAMES[engine.port] ?? engine.port} · {engine.healthy ? '正常' : '未运行'}
                  </span>
                ))}
              </div>
              {runtime !== null && runtime.engines.some((engine) => !engine.healthy) ? (
                <span className="settings__row-hint">
                  有引擎未运行。在仓库根目录运行 <code>scripts/chives.sh start --engines</code>{' '}
                  后刷新。
                </span>
              ) : null}
            </div>
          </div>

        </section></>}
        {page==='appearance'&&<section className="settings__section" aria-labelledby="settings-appearance">
          <h2 className="settings__section-title" id="settings-appearance">
            外观与数据
          </h2>
          {appearanceError === null ? null : (
            <div className="settings__status settings__status--error" role="alert">
              {appearanceError}
            </div>
          )}

          <div className="settings__row">
            <span className="settings__row-text">主题</span>
            <div className="settings__segmented" role="group" aria-label="主题">
              {(
                [
                  ['dark', '深色'],
                  ['light', '浅色'],
                  ['system', '跟随系统']
                ] as ReadonlyArray<[SettingsTheme, string]>
              ).map(([value, label]) => (
                <button
                  type="button"
                  key={value}
                  className="settings__segment"
                  aria-pressed={appearance.theme === value}
                  onClick={() => void changeAppearance({ theme: value })}
                >
                  {label}
                </button>
              ))}
            </div>
          </div>

          <div className="settings__row">
            <span className="settings__row-text">
              <span className="settings__row-label">涨跌颜色</span>
              <span className="settings__row-hint">同时始终显示 ▲▼ 符号</span>
            </span>
            <div className="settings__segmented" role="group" aria-label="涨跌颜色">
              {(
                [
                  ['red-up', '红涨绿跌'],
                  ['green-up', '绿涨红跌']
                ] as ReadonlyArray<[ChangeColorMode, string]>
              ).map(([value, label]) => (
                <button
                  type="button"
                  key={value}
                  className="settings__segment"
                  aria-pressed={appearance.changeColor === value}
                  onClick={() => void changeAppearance({ changeColor: value })}
                >
                  {label}
                </button>
              ))}
            </div>
          </div>

          {prefs&&<DisplayPrefs p={prefs} save={save}/>}
        </section>}
        {page==='backup'&&<section className="settings__section">
          <div className="settings__row">
            <div className="settings__row-text">
              <span className="settings__row-label">数据位置</span>
              <span className="settings__path">{data?.path ?? '读取中…'}</span>
              <span className="settings__row-hint">
                {data === null ? '' : `占用 ${formatFileSize(data.bytes)}`}
              </span>
            </div>
            <div className="settings__actions">
              <button
                type="button"
                className="settings__button"
                disabled={dataBusy}
                onClick={() => void handleRevealData()}
              >
                在访达中显示
              </button>
              {import.meta.env.BASE_URL === '/chives/' && (
                <form method="post" action={appPath('/logout')}>
                  <button type="submit" className="settings__button">退出登录</button>
                </form>
              )}
            </div>
          </div>
          {dataError === null ? null : (
            <div className="settings__status settings__status--error" role="alert">
              {dataError}
            </div>
          )}

          <p className="settings__note">
            所有对话、记忆和文件都只保存在这台电脑上。Chives 不连接真实券商。
          </p>
        </section>}
      </div></section>
    </div>
  );
}
