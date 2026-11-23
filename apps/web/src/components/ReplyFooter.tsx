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
      <span title="根据回复正文估算，每 100,000 Tokens 折算 1 韭菜币">
        消耗约{tokens.toLocaleString('zh-CN')} Tokens、{(tokens / 100000).toFixed(2)}韭菜币
      </span>
      <button type="button" title="复制 Markdown 原文" onClick={() => void copy()}>
        <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.3" aria-hidden="true">
          <rect x="5.5" y="5.5" width="7.5" height="7.5" rx="1.5"/>
          <path d="M10.5 3.5a1 1 0 0 0-1-1h-6a1 1 0 0 0-1 1v6a1 1 0 0 0 1 1"/>
        </svg>
        复制
      </button>
      {canSpeak && (
        <button type="button" onClick={read}>
          <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.3"
            strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            {speaking ? <rect x="4" y="4" width="8" height="8" rx="1"/> : <>
              <path d="M2.5 6h2l3-2.5v9l-3-2.5h-2z"/>
              <path d="M10 5.5a3.6 3.6 0 0 1 0 5m2-6.5a5.8 5.8 0 0 1 0 8"/>
            </>}
          </svg>
          {speaking ? '停止朗读' : '朗读'}
        </button>
      )}
      {notice && <span role="status">{notice}</span>}
    </footer>
  );
}
