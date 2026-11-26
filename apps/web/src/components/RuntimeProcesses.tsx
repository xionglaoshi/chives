import { useId } from 'react';
import type { RuntimeSettingsDto } from '@chives/server/protocol';
import { BotAvatar } from '../brand/BotAvatar';
import { DeskIcon } from './SettingsNav';

const systems: Record<string, string> = {
  core: 'kernels', doctor: 'permissions', sync: 'appearance', updates: 'updates',
};
const engines: Record<number, [name: string, icon: string, description: string]> = {
  8865: ['Chives 雷达', 'risk', '接收 Bot 盯盘计划，跟踪个股报价，触价后唤醒负责的 Bot。'],
  8866: ['Chives 罗盘', 'history', '监测指数、市场宽度和情绪，产生大盘告警。'],
  8867: ['Chives 信号枢纽', 'tasks', '整理个股和大盘告警，维护信号卡、作战卡和复盘数据。'],
  8868: ['Chives 数据站', 'backup', '统一提供行情与投研数据，供 Bot、工作台和引擎调用。'],
  8869: ['Chives 策略台', 'capabilities', '调度策略计算，向工作台和 Bot 提供策略结果和事件。'],
};

function ProcessCard({ name, description, state, icon, emblem, bot = false }: {
  name: string; description: string; state: string; icon?: string | undefined; emblem?: string; bot?: boolean;
}) {
  const id = useId();
  const label = state === 'running' ? (bot ? '工作中' : '正常')
    : state === 'inactive' ? '未激活' : state === 'error' ? '错误' : '未启动';
  return <div className="runtime-card">
    <button type="button" className="runtime-card__face" aria-describedby={id}
      onClick={event => event.currentTarget.focus()}>
      <span className="runtime-card__icon" aria-hidden="true">
        {emblem ? <BotAvatar emblem={emblem} tone="neutral" size={20}/> : <DeskIcon id={icon ?? 'kernels'}/>}
      </span>
      <span className="runtime-card__content">
        <span className="runtime-card__name">{name}</span>
        <span className={`runtime-card__state runtime-card__state--${state}`}>{label}</span>
      </span>
    </button>
    <span className="runtime-card__tooltip" role="tooltip" id={id}>{description}</span>
  </div>;
}

export function RuntimeProcesses({ runtime, error }: { runtime: RuntimeSettingsDto | null; error: string | null }) {
  return <section className="settings__section runtime-processes" aria-labelledby="settings-runtime">
    <h2 className="settings__section-title" id="settings-runtime">运行环境</h2>
    {error && <p role="alert" className="settings__status settings__status--error">{error}</p>}
    {!runtime && !error && <p role="status">正在读取进程状态…</p>}
    {runtime && <>
      <section aria-labelledby="runtime-system">
        <h3 id="runtime-system">系统进程</h3>
        <div className="runtime-processes__grid">{(runtime.systems ?? []).map(item =>
          <ProcessCard key={item.id} name={item.name} description={item.description} state={item.process} icon={systems[item.id]}/>)}</div>
      </section>
      <section aria-labelledby="runtime-engines">
        <h3 id="runtime-engines">引擎进程</h3>
        <div className="runtime-processes__grid">{runtime.engines.map(item => {
          const [name, icon, description] = engines[item.port] ?? [String(item.port), 'kernels', '后台引擎'];
          return <ProcessCard key={item.port} name={name} description={description} icon={icon}
            state={item.process ?? (item.healthy ? 'running' : 'not_started')}/>;
        })}</div>
      </section>
      <section aria-labelledby="runtime-bots">
        <h3 id="runtime-bots">Bot进程</h3>
        <div className="runtime-processes__grid">{runtime.bots.map(bot =>
          <ProcessCard key={bot.id} name={bot.name} description={bot.role} state={bot.process} emblem={bot.emblem} bot/>)}</div>
      </section>
    </>}
  </section>;
}
