import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { useState } from 'react';
import { describe, expect, it, vi } from 'vitest';

import type { MessageAttachmentDto } from '@chives/server/protocol';
import { Composer } from '../src/components/Composer';

function Harness({
  onSend,
  onStop,
  running = false
}: {
  onSend: (text: string) => void;
  onStop: () => void;
  running?: boolean;
}) {
  const [value, setValue] = useState('');
  return (
    <Composer
      value={value}
      onChange={setValue}
      onSend={onSend}
      onStop={onStop}
      running={running}
      sending={false}
      notice={null}
    />
  );
}

describe('Composer', () => {
  it('sends on Enter and keeps Shift+Enter for a newline', () => {
    const onSend = vi.fn();
    render(<Harness onSend={onSend} onStop={() => {}} />);
    const input = screen.getByLabelText('给 Bot 发消息');

    fireEvent.change(input, { target: { value: '看下茅台' } });
    fireEvent.keyDown(input, { key: 'Enter', shiftKey: true });
    expect(onSend).not.toHaveBeenCalled();

    fireEvent.keyDown(input, { key: 'Enter' });
    expect(onSend).toHaveBeenCalledWith('看下茅台');
  });

  it('turns the send button into a stop button while a task is running', () => {
    const onStop = vi.fn();
    render(<Harness onSend={() => {}} onStop={onStop} running />);
    expect(screen.queryByRole('button', { name: '发送' })).toBeNull();
    const stop = screen.getByRole('button', { name: '停止当前任务' });
    expect(stop.querySelector('svg')).not.toBeNull();
    fireEvent.click(stop);
    expect(onStop).toHaveBeenCalledTimes(1);
  });

  it('disables the input and explains why while the server is unreachable', () => {
    const onSend = vi.fn();
    render(
      <Composer
        value="看下茅台"
        onChange={() => {}}
        onSend={onSend}
        onStop={() => {}}
        running={false}
        sending={false}
        notice={null}
        disabled
        disabledReason="连不上 Chives 服务，恢复后才能发送。"
      />
    );
    const input = screen.getByLabelText('给 Bot 发消息') as HTMLTextAreaElement;
    expect(input.disabled).toBe(true);
    fireEvent.keyDown(input, { key: 'Enter' });
    expect(onSend).not.toHaveBeenCalled();
    expect(screen.getByText('连不上 Chives 服务，恢复后才能发送。')).toBeTruthy();
  });

  it('shows the busy notice from a 409 unchanged', () => {
    render(
      <Composer
        value=""
        onChange={() => {}}
        onSend={() => {}}
        onStop={() => {}}
        running={false}
        sending={false}
        notice="上一个任务还在进行"
      />
    );
    expect(screen.getByRole('alert').textContent).toContain('上一个任务还在进行');
  });
});

describe('Composer uploads and shape', () => {
  const image: MessageAttachmentDto = {
    path: 'uploads/20261117/chart.png',
    name: 'chart.png',
    size: 2048,
    kind: 'image'
  };

  it('switches from the pill radius to 22px when the text has several lines', async () => {
    render(<Harness onSend={() => {}} onStop={() => {}} />);
    const input = screen.getByLabelText('给 Bot 发消息');
    const form = input.closest('form');
    expect(form?.className).not.toContain('composer__form--multiline');
    fireEvent.change(input, { target: { value: '第一行\n第二行' } });
    await waitFor(() => expect(form?.className).toContain('composer__form--multiline'));
  });

  it('passes picked files to onAddFiles from the plus button input', () => {
    const onAddFiles = vi.fn();
    const { container } = render(
      <Composer
        value=""
        onChange={() => {}}
        onSend={() => {}}
        onStop={() => {}}
        running={false}
        sending={false}
        notice={null}
        onAddFiles={onAddFiles}
      />
    );
    const input = container.querySelector('input[type="file"]') as HTMLInputElement;
    const file = new File(['png'], 'chart.png', { type: 'image/png' });
    fireEvent.change(input, { target: { files: [file] } });
    expect(onAddFiles).toHaveBeenCalledWith([file]);
    expect(screen.getByRole('button', { name: '上传文件' })).toBeTruthy();
  });

  it('forwards pasted image files', () => {
    const onAddFiles = vi.fn();
    render(
      <Composer
        value=""
        onChange={() => {}}
        onSend={() => {}}
        onStop={() => {}}
        running={false}
        sending={false}
        notice={null}
        onAddFiles={onAddFiles}
      />
    );
    const file = new File(['png'], 'pasted.png', { type: 'image/png' });
    fireEvent.paste(screen.getByLabelText('给 Bot 发消息'), {
      clipboardData: { files: [file] }
    });
    expect(onAddFiles).toHaveBeenCalledWith([file]);
  });

  it('shows pending attachments with a thumbnail and removes one by path', () => {
    const onRemoveAttachment = vi.fn();
    render(
      <Composer
        value=""
        onChange={() => {}}
        onSend={() => {}}
        onStop={() => {}}
        running={false}
        sending={false}
        notice={null}
        botId="expert"
        attachments={[image]}
        onRemoveAttachment={onRemoveAttachment}
      />
    );
    expect(screen.getByText('chart.png')).toBeTruthy();
    expect(screen.getByText('2.0 KB')).toBeTruthy();
    expect(
      document.querySelector('.composer__attachment-thumb')?.getAttribute('src')
    ).toBe('/api/bots/expert/files/content?path=uploads%2F20261117%2Fchart.png');
    fireEvent.click(screen.getByRole('button', { name: '移除 chart.png' }));
    expect(onRemoveAttachment).toHaveBeenCalledWith('uploads/20261117/chart.png');
  });

  it('renders the specific upload error above the input', () => {
    render(
      <Composer
        value=""
        onChange={() => {}}
        onSend={() => {}}
        onStop={() => {}}
        running={false}
        sending={false}
        notice={null}
        uploadNotice="不支持的文件类型：a.exe"
      />
    );
    const alert = screen.getByRole('alert');
    expect(alert.textContent).toContain('不支持的文件类型：a.exe');
    expect(alert.className).toContain('composer__notice--upload');
  });

  it('allows sending an attachment-only message', () => {
    const onSend = vi.fn();
    render(
      <Composer
        value=""
        onChange={() => {}}
        onSend={onSend}
        onStop={() => {}}
        running={false}
        sending={false}
        notice={null}
        attachments={[image]}
      />
    );
    const send = screen.getByRole('button', { name: '发送' }) as HTMLButtonElement;
    expect(send.disabled).toBe(false);
    fireEvent.click(send);
    expect(onSend).toHaveBeenCalledWith('');
  });
});
