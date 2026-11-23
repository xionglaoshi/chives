import { useEffect, useRef, useState, type RefObject } from 'react';
import type { MessageDto } from '@chives/server/protocol';
import { formatTime } from '../utils/format';

// ACP usage describes the context window. This is only an estimate of visible output.
function estimateReplyTokens(text: string): number {
  const wide = text.match(/[\p{Script=Han}\p{Script=Hiragana}\p{Script=Katakana}\p{Script=Hangul}]/gu)?.length ?? 0;
  return Math.ceil(wide + (Array.from(text).length - wide) / 4);
}

let stopActiveSpeech: (() => void) | undefined;

export function ReplyFooter({ message, content }: {message: MessageDto; content: RefObject<HTMLDivElement>}) {
  const [notice, setNotice] = useState('');
  const [speaking, setSpeaking] = useState(false);
  const speech = useRef<SpeechSynthesisUtterance | null>(null);
  const canSpeak = typeof window !== 'undefined' && 'speechSynthesis' in window && 'SpeechSynthesisUtterance' in window;
  const tokens = estimateReplyTokens(message.content);

  useEffect(() => () => {
    if (speech.current) stopActiveSpeech?.();
  }, []);

  async function copy() {
    try {
      await navigator.clipboard.writeText(message.content);
      setNotice('已复制');
    } catch {
      setNotice('复制失败');
    }
  }

  function read() {
    const engine = window.speechSynthesis;
    if (speech.current) {
      stopActiveSpeech?.();
      return;
    }
    const text = content.current?.innerText.trim();
    if (!text) return;
    const chunks = text.match(/[\s\S]{1,180}(?:[。！？；\n]|$)|[\s\S]{1,180}/gu) ?? [];
    stopActiveSpeech?.();
    const finish = () => {
      if (stopActiveSpeech === stop) stopActiveSpeech = undefined;
      speech.current = null;
      setSpeaking(false);
    };
    const stop = () => { finish(); engine.cancel(); };
    stopActiveSpeech = stop;
    setSpeaking(true);
    setNotice('');
    const next = (index: number) => {
      const chunk = chunks[index];
      if (!chunk) { finish(); return; }
      const utterance = new SpeechSynthesisUtterance(chunk);
      utterance.lang = document.documentElement.lang.startsWith('zh') ? 'zh-CN' : document.documentElement.lang || 'zh-CN';
      speech.current = utterance;
      utterance.onend = () => { if (speech.current === utterance) next(index + 1); };
      utterance.onerror = event => {
        if (speech.current !== utterance) return;
        finish();
        if (event.error !== 'canceled' && event.error !== 'interrupted') setNotice('朗读失败');
      };
      engine.speak(utterance);
    };
    next(0);
  }

  return (
    <footer className="timeline__reply-footer">
      <time dateTime={message.createdAt}>{formatTime(message.createdAt)}</time>
      <span title="根据可见回复文本估算">约 {tokens.toLocaleString('zh-CN')} Token</span>
      <span title="每 100,000 个估算 Token 折算 1 模拟信用点">模拟 {(tokens / 100000).toFixed(2)} 信用点</span>
      <button type="button" onClick={() => void copy()}>复制 Markdown</button>
      {canSpeak && <button type="button" onClick={read}>{speaking ? '停止朗读' : '朗读回复'}</button>}
      {notice && <span role="status">{notice}</span>}
    </footer>
  );
}
