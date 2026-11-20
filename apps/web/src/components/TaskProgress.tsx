import { useState } from 'react';
import type { ReactElement } from 'react';

import type { TaskDto, ToolEventDto, ToolStatus } from '@chives/server/protocol';

import { useNow } from '../hooks/useNow';
import { formatDurationBetween, formatJson, truncateOutput } from '../utils/format';
import './TaskProgress.css';

const TOOL_LABELS: Record<ToolStatus, string> = {
  running: '进行',
  completed: '完成',
  failed: '失败'
};

const TOOL_GLYPHS: Record<ToolStatus, string> = {
  running: '●',
  completed: '✓',
  failed: '✕'
};

const TASK_LABELS: Record<TaskDto['status'], string> = {
  running: '进行中',
  done: '已完成',
  failed: '失败',
  cancelled: '已取消',
  interrupted: '已中断'
};

export interface TaskProgressProps {
  task: TaskDto;
  tools: ToolEventDto[];
}

function ToolRow({ tool, now }: { tool: ToolEventDto; now: number }): ReactElement {
  const [open, setOpen] = useState(false);
  const output = tool.output ?? '';
  const truncated = truncateOutput(output);
  const input = formatJson(tool.rawInput);
  const detailId = `tool-detail-${tool.id}`;

  return (
    <li className="task-step">
      <button
        type="button"
        className="task-step__header"
        aria-expanded={open}
        aria-controls={detailId}
        onClick={() => setOpen((value) => !value)}
      >
        <span
          className={`task-step__icon task-step__icon--${tool.status}`}
          role="img"
          aria-label={TOOL_LABELS[tool.status]}
          title={TOOL_LABELS[tool.status]}
        >
          {TOOL_GLYPHS[tool.status]}
        </span>
        <span className="task-step__body">
          <span className="task-step__title">{tool.title}</span>
          {tool.kind === '' ? null : <span className="task-step__kind"> · {tool.kind}</span>}
        </span>
        <span className="task-step__duration">
          {formatDurationBetween(tool.startedAt, tool.endedAt, now)}
        </span>
        <span className="task-step__chevron" aria-hidden="true">
          {open ? '▾' : '▸'}
        </span>
      </button>
      {open ? (
        <div className="task-step__detail" id={detailId}>
          <div className="task-step__detail-label">参数</div>
          <pre className="task-step__pre">{input === '' ? '无' : input}</pre>
          <div className="task-step__detail-label">输出</div>
          <pre className="task-step__pre">
            {output === '' ? '暂无输出' : truncated.text}
            {truncated.truncated ? '\n…（输出已截断）' : ''}
          </pre>
          {truncated.truncated ? (
            <div className="task-step__truncated">共 {output.length} 字，仅显示前 2000 字</div>
          ) : null}
        </div>
      ) : null}
    </li>
  );
}

export function ToolStepList({ tools, now }: { tools: ToolEventDto[]; now: number }): ReactElement {
  return (
    <ol className="task-progress__steps">
      {tools.length === 0 ? <li className="task-progress__empty">还没有工具步骤</li> : null}
      {tools.map((tool) => (
        <ToolRow key={tool.id} tool={tool} now={now} />
      ))}
    </ol>
  );
}

/** One collapsible "worked for …" row per task, with its tool steps inside. */
export function TaskProgress({ task, tools }: TaskProgressProps): ReactElement {
  const [open, setOpen] = useState(false);
  const running = task.status === 'running';
  const now = useNow(running);
  const duration = formatDurationBetween(task.startedAt, task.endedAt, now);
  const summary = running
    ? `工作中… · ${tools.length} 步 · ${duration}`
    : `工作了 ${duration} · ${tools.length} 步 · ${TASK_LABELS[task.status]}`;

  return (
    <section className={`task-progress${running ? ' task-progress--running' : ''}`} aria-label="工作过程">
      <button
        type="button"
        className="task-progress__toggle"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
      >
        <span className="task-progress__chevron" aria-hidden="true">
          {open ? '▾' : '▸'}
        </span>
        <span className="task-progress__summary">{summary}</span>
      </button>
      {open ? <ToolStepList tools={tools} now={now} /> : null}
    </section>
  );
}
