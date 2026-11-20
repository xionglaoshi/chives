import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import type { BotSummary } from '@chives/server/protocol';
import { AvatarEditDialog } from '../src/components/AvatarEditDialog';
import { makeBot } from './testUtils';

const bot = makeBot({ name: '投资专家', avatar: { emblem: 'crown', tone: 'gold' } });
const defaults = { name: '投资专家', avatar: { emblem: 'crown', tone: 'gold' } };

function renderDialog(onSave = vi.fn(async () => ({ ...bot }))) {
  const onSaved = vi.fn();
  const onClose = vi.fn();
  render(
    <AvatarEditDialog
      bot={bot}
      defaults={defaults}
      onClose={onClose}
      onSave={onSave as (patch: unknown) => Promise<BotSummary>}
      onSaved={onSaved}
    />
  );
  return { onSave, onSaved, onClose };
}

describe('AvatarEditDialog', () => {
  it('selects an icon and preserves legacy tone with the trimmed name', async () => {
    const { onSave, onSaved } = renderDialog();
    fireEvent.change(screen.getByLabelText('称呼'), { target: { value: '  小金子  ' } });
    fireEvent.click(screen.getByRole('radio', { name: '明灯' }));
    expect(screen.getByRole('radio', { name: '明灯' }).getAttribute('aria-checked')).toBe('true');
    expect(screen.queryByRole('radiogroup', { name: '选择头像底色' })).toBeNull();

    fireEvent.click(screen.getByRole('button', { name: '保存' }));
    await waitFor(() => {
      expect(onSave).toHaveBeenCalledWith({
        displayName: '小金子',
        avatar: { emblem: 'lamp', tone: 'gold' }
      });
    });
    expect(onSaved).toHaveBeenCalledWith(bot);
  });

  it('moves emblem selection with arrow keys and roving focus', () => {
    renderDialog();
    const crown = screen.getByRole('radio', { name: '王冠' });
    crown.focus();
    fireEvent.keyDown(crown, { key: 'ArrowRight' });
    expect(screen.getByRole('radio', { name: '天平' }).getAttribute('aria-checked')).toBe('true');
    expect(document.activeElement).toBe(screen.getByRole('radio', { name: '天平' }));

    fireEvent.keyDown(document.activeElement as HTMLElement, { key: 'ArrowDown' });
    expect(screen.getByRole('radio', { name: '羽笔' }).getAttribute('aria-checked')).toBe('true');
  });

  it('restores defaults through null overrides', async () => {
    const { onSave, onSaved } = renderDialog();
    fireEvent.click(screen.getByRole('button', { name: '恢复默认' }));
    await waitFor(() => {
      expect(onSave).toHaveBeenCalledWith({ displayName: null, avatar: null });
    });
    expect(onSaved).toHaveBeenCalled();
  });

  it('blocks an empty name and shows the server error', async () => {
    const failing = vi.fn(async () => {
      throw new Error('保存失败');
    });
    const { onSave, onSaved } = renderDialog(failing);
    const input = screen.getByLabelText('称呼');
    fireEvent.change(input, { target: { value: '   ' } });
    fireEvent.click(screen.getByRole('button', { name: '保存' }));
    expect((await screen.findByRole('alert')).textContent).toBe('称呼需要 1–12 个字符');
    expect(onSave).not.toHaveBeenCalled();

    fireEvent.change(input, { target: { value: '新名字' } });
    fireEvent.click(screen.getByRole('button', { name: '保存' }));
    expect((await screen.findByRole('alert')).textContent).toBe('保存失败');
    expect(onSaved).not.toHaveBeenCalled();
  });

  it('closes on Escape and on the cancel button', () => {
    const { onClose } = renderDialog();
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(onClose).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole('button', { name: '取消' }));
    expect(onClose).toHaveBeenCalledTimes(2);
  });
});
