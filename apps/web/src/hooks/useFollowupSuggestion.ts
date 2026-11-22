import { useEffect, useRef, useState } from 'react';
import { suggestFollowup } from '../api/client';

interface Attempt {
  messageId: string;
  text: string | null;
  loading: boolean;
}

const empty = {text: null, loading: false};

export function useFollowupSuggestion(botId: string | null, messageId: string | null) {
  const [attempts, setAttempts] = useState<ReadonlyMap<string, Attempt>>(() => new Map());
  const started = useRef(new Map<string, string>());

  useEffect(() => {
    if (botId === null || messageId === null) return;
    const id = botId;
    const turn = messageId;
    let timer: number | undefined;

    function save(attempt: Attempt) {
      setAttempts(current => new Map(current).set(id, attempt));
    }

    function schedule() {
      window.clearTimeout(timer);
      if (document.hidden || started.current.get(id) === turn) return;
      timer = window.setTimeout(async () => {
        started.current.set(id, turn);
        save({messageId: turn, text: null, loading: true});
        const signal = AbortSignal.timeout(12000);
        let text: string | null = null;
        try {
          const {draft} = await suggestFollowup(id, signal);
          if (!signal.aborted) text = draft;
        } catch { /* This turn has already used its single attempt. */ }
        if (started.current.get(id) === turn) {
          save({messageId: turn, text, loading: false});
        }
      }, 30000);
    }

    schedule();
    document.addEventListener('visibilitychange', schedule);
    return () => {
      window.clearTimeout(timer);
      document.removeEventListener('visibilitychange', schedule);
    };
  }, [botId, messageId]);

  const attempt = botId === null ? undefined : attempts.get(botId);
  return attempt?.messageId === messageId ? attempt : empty;
}
