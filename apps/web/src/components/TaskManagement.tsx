import { useEffect, useRef, useState } from 'react';
import type { ManagedTaskDto } from '@chives/server/protocol';
import { fetchManagedTasks, changeManagedTask } from '../api/client';
import { BotAvatar } from '../brand/BotAvatar';
import './TaskManagement.css';

type Condition = Record<string, unknown>;
type WatchTask = Extract<ManagedTaskDto, { kind: 'watch' }>;
type RoutineTask = Extract<ManagedTaskDto, { kind: 'routine' }>;

const stockTypes = {
  price_cross: '触及价格', price_in_range: '价格区间', pct_change: '涨跌幅',
  open_pct: '开盘涨跌幅', volume_ratio: '量比',
};
const marketTypes = { index_pct: '指数涨跌幅', regime: '大盘强弱' };
const indexes = {
  '000001.SH': '上证指数', '399001.SZ': '深证成指', '399006.SZ': '创业板指',
  '000300.SH': '沪深300', '000852.SH': '中证1000', '000688.SH': '科创50',
};
const regimes = { strong: '强势', neutral: '中性', weak: '弱势' };
const defaults: Record<string, Condition> = {
  price_cross: { direction: 'down', level: 1 }, price_in_range: { lo: 1, hi: 2 },
  pct_change: { direction: 'down', threshold_pct: 1 }, open_pct: { op: '<=', value: 0 },
  volume_ratio: { op: '>=', value: 1 }, index_pct: { code: '000300.SH', op: '<=', value: 0 },
  regime: { values: ['neutral'] },
};

function Options({ items }: { items: Record<string, string> }) {
  return <>{Object.entries(items).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</>;
}

function ConditionGroup({ name, items, change, market = false, required = false }: {
  name: string; items: Condition[]; change: (items: Condition[]) => void; market?: boolean; required?: boolean;
}) {
  const types = market ? marketTypes : stockTypes;
  return <fieldset>
    <legend>{name}</legend>
    {items.map((item, index) => {
      const type = String(item.type);
      const replace = (next: Condition) => change(items.map((entry, i) => i === index ? next : entry));
      const set = (key: string, value: unknown) => replace({ ...item, [key]: value });
      const number = (key: string, label: string) => <label>{label}
        <input required type="number" step="any" value={typeof item[key] === 'number' ? String(item[key]) : ''}
          onChange={event => set(key, event.currentTarget.value === '' ? '' : Number(event.currentTarget.value))}/>
      </label>;
      return <div className="task-editor__condition" key={index}>
        <label>条件类型<select value={type} onChange={event => {
          const next = event.currentTarget.value;
          replace({type: next, ...defaults[next]});
        }}><Options items={types}/></select></label>
        {(type === 'price_cross' || type === 'pct_change') && <>
          <label>方向<select value={String(item.direction)} onChange={event => set('direction', event.currentTarget.value)}>
            <Options items={type === 'price_cross' ? {down:'跌破',up:'站上'} : {down:'下跌',up:'上涨'}}/>
          </select></label>
          {type === 'price_cross' ? number('level', '价格（元）') : number('threshold_pct', '幅度（%）')}
        </>}
        {type === 'price_in_range' && <>{number('lo', '最低价（元）')}{number('hi', '最高价（元）')}</>}
        {type === 'index_pct' && <label>指数<select value={String(item.code)} onChange={event => set('code', event.currentTarget.value)}><Options items={indexes}/></select></label>}
        {['index_pct','open_pct','volume_ratio'].includes(type) && <>
          <label>比较<select value={String(item.op)} onChange={event => set('op', event.currentTarget.value)}>
            <Options items={{'>=':'大于或等于','<=':'小于或等于'}}/>
          </select></label>
          {number('value', type === 'volume_ratio' ? '量比' : '涨跌幅（%）')}
        </>}
        {type === 'regime' && Object.entries(regimes).map(([value, label]) => {
          const values = Array.isArray(item.values) ? item.values : [];
          return <label className="task-editor__check" key={value}><input type="checkbox" checked={values.includes(value)}
            onChange={event => set('values', event.currentTarget.checked ? [...values, value] : values.filter(entry => entry !== value))}/>{label}</label>;
        })}
        <button type="button" aria-label={`移除第 ${index + 1} 条${name}`} disabled={required && items.length === 1}
          onClick={() => change(items.filter((_, i) => i !== index))}>移除</button>
      </div>;
    })}
    {items.length < 6 && <button type="button" onClick={() => {
      const type = market ? 'index_pct' : 'price_cross';
      change([...items, { type, ...defaults[type] }]);
    }}>添加{name}</button>}
  </fieldset>;
}

function RoutineFields({ task }: { task: RoutineTask }) {
  const [mode, setMode] = useState(task.schedule.every_minutes !== undefined ? 'interval' : task.schedule.once_at ? 'once' : 'cron');
  const [cron, setCron] = useState(task.schedule.cron ?? '0 9 * * 1-5');
  const simple = /^(\d{1,2}) (\d{1,2}) \* \* (\*|1-5|0|1|2|3|4|5|6)$/.exec(cron);
  const time = simple ? `${simple[2]!.padStart(2,'0')}:${simple[1]!.padStart(2,'0')}` : '';
  const onceShanghai = task.schedule.once_at ? new Date(Date.parse(task.schedule.once_at) + 8 * 3600_000).toISOString().slice(0, 19) : '';
  return <>
    <label>执行时间<select name="mode" value={mode} onChange={event => setMode(event.currentTarget.value)}>
      <Options items={{ cron: '按日程', interval: '按间隔', once: '只执行一次' }}/>
    </select></label>
    {mode === 'cron' && <>
      {simple && <>
        <label>执行时刻<input type="time" required value={time} onChange={event => {
          const [hour, minute] = event.currentTarget.value.split(':');
          if (hour && minute) setCron(`${Number(minute)} ${Number(hour)} * * ${simple[3]}`);
        }}/></label>
        <label>重复日期<select value={simple[3]} onChange={event => setCron(`${simple[1]} ${simple[2]} * * ${event.currentTarget.value}`)}>
          <Options items={{'*':'每天','1-5':'工作日','1':'每周一','2':'每周二','3':'每周三','4':'每周四','5':'每周五','6':'每周六','0':'每周日'}}/>
        </select></label>
      </>}
      <details open={!simple}><summary>定时表达式</summary>
        <input aria-label="定时表达式" name="cron" required value={cron} onChange={event => setCron(event.currentTarget.value)}/>
      </details>
      <label>时区<select name="tz" defaultValue={task.schedule.tz ?? 'Asia/Shanghai'}>
        <Options items={{ 'Asia/Shanghai': '北京时间', UTC: 'UTC' }}/></select></label>
    </>}
    {mode === 'interval' && <label>间隔分钟<input name="interval" type="number" min={5} required defaultValue={task.schedule.every_minutes ?? 60}/></label>}
    {mode === 'once' && <label>执行时间（北京时间）<input type="datetime-local" step={1} required name="once" defaultValue={onceShanghai}/></label>}
    <label className="task-editor__check"><input type="checkbox" defaultChecked={task.tradingDaysOnly} name="trading"/>仅交易日执行</label>
    <label>任务指令<textarea name="prompt" rows={5} maxLength={4000} required defaultValue={task.prompt}/></label>
  </>;
}

function readRoutine(form: FormData): Record<string, unknown> {
  const mode = form.get('mode');
  const schedule = mode === 'interval' ? { every_minutes: Number(form.get('interval')) }
    : mode === 'once' ? { once_at: `${form.get('once')}+08:00` } : { cron: form.get('cron'), tz: form.get('tz') };
  return { title: form.get('title'), schedule, tradingDaysOnly: form.has('trading'), prompt: form.get('prompt') };
}

function WatchFields({ task, rules, setRules }: { task: WatchTask; rules: WatchTask['rules']; setRules: (rules: WatchTask['rules']) => void }) {
  return <>
    <label>证券代码<input name="code" defaultValue={task.code} required/></label>
    <ConditionGroup name="触发条件" items={rules.when} change={when => setRules({...rules, when})} required/>
    <label>触发方式<select value={rules.match} onChange={event => setRules({...rules, match:event.currentTarget.value === 'all' ? 'all' : 'any'})}>
      <Options items={{ any: '任一触发条件满足', all: '所有触发条件满足' }}/>
    </select></label>
    <ConditionGroup name="大盘前置条件" items={rules.market} change={market => setRules({...rules, market})} market/>
    <ConditionGroup name="放弃条件" items={rules.giveUp} change={giveUp => setRules({...rules, giveUp})}/>
    <label>重新设置有效期（天）<input name="expires" type="number" min={1} max={30} placeholder="留空保留原到期时间"/></label>
    <label className="task-editor__check"><input type="checkbox" name="repeat" defaultChecked={task.repeat}/>允许重复触发</label>
    <label>备注<textarea name="note" rows={2} maxLength={200} defaultValue={task.note}/></label>
  </>;
}

function TaskEditor({ task, close, save, busy, error }: {
  task: ManagedTaskDto; close: () => void; save: (patch?: Record<string, unknown>) => void; busy: boolean; error: string;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [rules, setRules] = useState<WatchTask['rules']>(task.kind === 'watch'
    ? task.rules : { when: [], giveUp: [], market: [], match: 'any' });
  useEffect(() => { const element = dialog.current; element?.showModal(); return () => element?.close(); }, []);
  if(task.kind==='archive')return <dialog ref={dialog} className="task-editor" aria-labelledby="archive-title" onCancel={close}>
    <h3 id="archive-title">{task.botName} · {task.title}</h3><p>{task.conditionText}</p>
    <p>检查持仓、关注和各岗位对话，更新用户属性、近期事项、长期档案与岗位记忆。</p>
    <p>已整理至 {task.through??'尚无完成记录'} · {task.state}</p><button onClick={close}>完成</button>
  </dialog>;
  return <dialog ref={dialog} className="task-editor" aria-labelledby="task-editor-title"
    onCancel={event => { event.preventDefault(); if (!busy) close(); }}>
    <form onSubmit={event => {
      event.preventDefault();
      const form = new FormData(event.currentTarget);
      const expires = form.get('expires');
      save(task.kind === 'routine' ? readRoutine(form) : task.kind==='technical' ? {title:form.get('title')} : {
        label: form.get('title'), code: form.get('code'), ...rules, repeat: form.has('repeat'), note: form.get('note'),
        ...(expires ? { expiresInDays: Number(expires) } : {}),
      });
    }}>
      <header><h3 id="task-editor-title">编辑任务</h3><p>{task.botName}：{task.title}</p></header>
      <div className="task-editor__fields">
        <label>任务名称<input name="title" required defaultValue={task.title} maxLength={task.kind === 'routine' ? 60 : 40}/></label>
        {task.kind === 'routine' ? <RoutineFields task={task}/> : task.kind==='technical' ? <section>
          <p>{task.code} · {task.sources.join('、')}</p><p>{task.conditionText} · {task.state}</p>
          <p>比较均线、成交量、动量与趋势指标，有新信号时在盯盘交易员会话汇报。</p><p>{task.pending}</p>
        </section> : <WatchFields task={task} rules={rules} setRules={setRules}/>}
        {error && <p role="alert">{error}</p>}
        {confirmDelete && <p role="alert">确定删除「{task.title}」？</p>}
      </div>
      <footer>
        <button type="button" className="task-editor__delete" disabled={busy} onClick={() => confirmDelete ? save() : setConfirmDelete(true)}>
          {confirmDelete ? '确认删除' : '删除任务'}
        </button>
        <button type="button" disabled={busy} onClick={confirmDelete ? () => setConfirmDelete(false) : close}>取消</button>
        {!confirmDelete && <button type="submit" disabled={busy}>{busy ? '保存中…' : '保存'}</button>}
      </footer>
    </form>
  </dialog>;
}

export function TaskManagement() {
  const focusedBot = new URLSearchParams(window.location.hash.split('?')[1]).get('bot');
  const firstHighlighted = useRef<HTMLLIElement>(null);
  const [rows, setRows] = useState<ManagedTaskDto[] | null>(null);
  const [editing, setEditing] = useState<ManagedTaskDto | null>(null);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState('');
  useEffect(() => {
    const controller = new AbortController();
    void fetchManagedTasks(controller.signal).then(setRows).catch(error => {
      if (!controller.signal.aborted) setError(String(error.message));
    });
    return () => controller.abort();
  }, []);

  useEffect(() => {
    if (!rows) return;
    const params = new URLSearchParams(window.location.hash.split('?')[1]);
    const id = params.get('task');
    if (!id) return;
    const target = rows.find(task => task.id === id && task.kind === params.get('kind'));
    if (target) setEditing(target);
    else setError('这条任务已结束或不存在。');
    if (params.has('task')) window.history.replaceState(null, '', '#/settings?tab=tasks');
  }, [rows]);

  const firstMatch = focusedBot ? rows?.find(task => task.botId === focusedBot) : undefined;
  useEffect(() => {
    if (firstMatch) firstHighlighted.current?.scrollIntoView({ block: 'nearest' });
  }, [firstMatch?.id, focusedBot]);

  async function change(task: ManagedTaskDto, patch?: Record<string, unknown>) {
    setPending(true); setError('');
    try {
      await changeManagedTask(task, patch);
      setEditing(null);
      setRows(await fetchManagedTasks());
    } catch (error) { setError(error instanceof Error ? error.message : '任务保存失败。'); }
    finally { setPending(false); }
  }

  return <div className="routine-manager">
    {!editing && error && <p role="alert">{error} <button disabled={pending} onClick={() => {
      setError(''); void fetchManagedTasks().then(setRows).catch(error => setError(String(error.message)));
    }}>重试读取</button></p>}
    {!rows && !error && <p role="status">正在读取任务…</p>}
    {focusedBot && rows && <p className="routine-manager__highlight-note" role="status">
      {firstMatch ? `已高亮${firstMatch.botName}的任务` : '该 Bot 暂无任务'}
      {' · '}<a href="#/settings?tab=tasks">清除定位</a>
    </p>}
    {rows && (rows.length ? <ul aria-label="所有任务" className="routine-manager__list">{rows.map(task => {
      const title = `${task.botName}：${task.title}`;
      const condition = task.kind === 'routine' ? task.scheduleText + (task.tradingDaysOnly ? ' · 仅交易日' : '')
        : task.kind==='archive' ? task.conditionText : task.kind==='technical' ? [task.code,task.sources.join('、'),task.conditionText,task.enabled?task.state:'已暂停'].join(' · ')
        : [task.conditionText, task.giveUpText, task.repeat ? '可重复触发' : '仅触发一次'].filter(Boolean).join(' · ');
      return <li key={`${task.kind}:${task.id}`}
        className={task.botId === focusedBot ? 'routine-manager__highlighted' : undefined}
        ref={task === firstMatch ? firstHighlighted : undefined}>
        <BotAvatar emblem={task.botAvatar?.emblem ?? 'crown'} tone={task.botAvatar?.tone ?? 'gold'} name={task.botName} size={23}/>
        <div className="routine-manager__task"><strong>{title}</strong>
          <div className="routine-manager__meta">{condition}{!task.canEnable && ' · Bot 未在岗'}</div></div>
        <div className="routine-manager__controls">
          <input type="checkbox" role="switch" aria-label={`启用 ${title}`} checked={task.enabled}
            title={task.kind==='archive' ? '出厂任务，始终启用' : !task.canEnable && !task.enabled ? '请先聘用对应 Bot' : undefined}
            disabled={pending || task.kind==='archive' || (!task.canEnable && !task.enabled)} onChange={event => void change(task, {enabled:event.currentTarget.checked})}/>
          <button type="button" className="routine-manager__edit" aria-label={`编辑 ${title}`} title="编辑任务"
            disabled={pending} onClick={() => {setError('');setEditing(task);}}>
            <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" aria-hidden="true"><path d="m5 15-1 5 5-1L20 8l-4-4L5 15Zm9-9 4 4"/></svg>
          </button>
        </div>
      </li>;
    })}</ul> : <p>还没有任务。</p>)}
    {editing && <TaskEditor key={`${editing.kind}:${editing.id}`} task={editing} busy={pending} error={error}
      close={() => {setEditing(null);setError('');}} save={patch => void change(editing, patch)}/>}
  </div>;
}
