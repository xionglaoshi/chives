import { useEffect, useState } from 'react';
import { suggestFollowup } from '../api/client';

export function useFollowupSuggestion(botId: string | null) {
  const [state, setState] = useState<{botId: string; text: string | null; loading: boolean} | null>(null);

  useEffect(() => {
    setState(null);
    if (botId === null) return;
    let timer: number | undefined;
    let request: AbortController | undefined;
    function schedule() {
      window.clearTimeout(timer);
      request?.abort();
      setState(null);
      if (document.hidden || botId === null) return;
      const id = botId;
      timer = window.setTimeout(async () => {
        const controller = new AbortController();
        request = controller;
        setState({botId: id, text: null, loading: true});
        let text: string | null = null;
        try {
          const signal = AbortSignal.any([controller.signal, AbortSignal.timeout(12000)]);
          ({draft: text} = await suggestFollowup(id, signal));
          if (signal.aborted) text = null;
        } catch { /* An unavailable suggestion does not interrupt the conversation. */ }
        if (!controller.signal.aborted) setState({botId: id, text, loading: false});
      }, 30000);
    }
    schedule();
    document.addEventListener('visibilitychange', schedule);
    return () => {
      window.clearTimeout(timer);
      request?.abort();
      document.removeEventListener('visibilitychange', schedule);
    };
  }, [botId]);

  return state && state.botId === botId ? state : {text: null, loading: false};
}
