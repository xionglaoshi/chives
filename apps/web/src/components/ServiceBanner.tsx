import { useEffect, useState } from 'react';
import type { ReactElement } from 'react';

import type { EventStreamStatus } from '../hooks/useEventStream';
import './ServiceBanner.css';

export interface ServiceBannerProps {
  serverError: string | null;
  eventStatus: EventStreamStatus;
  onRetry: () => void;
  /** Matches the bot-list retry interval so the countdown is honest. */
  retrySeconds?: number;
}

export function ServiceBanner({
  serverError,
  eventStatus,
  onRetry,
  retrySeconds = 3
}: ServiceBannerProps): ReactElement | null {
  const [countdown, setCountdown] = useState(retrySeconds);

  useEffect(() => {
    if (serverError === null) return;
    setCountdown(retrySeconds);
    const timer = setInterval(() => {
      setCountdown((value) => (value <= 1 ? retrySeconds : value - 1));
    }, 1000);
    return () => clearInterval(timer);
  }, [serverError, retrySeconds]);

  if (serverError !== null) {
    return (
      <div className="service-banner" role="status" aria-live="polite">
        <span>
          连不上 Chives 服务，{countdown} 秒后自动重试…已加载的时间线仍可阅读，恢复后才能发送消息。
        </span>
        <button type="button" className="service-banner__retry" onClick={onRetry}>
          立即重试
        </button>
      </div>
    );
  }
  if (eventStatus === 'reconnecting') {
    return (
      <div className="service-banner" role="status" aria-live="polite">
        实时连接已断开，正在重连…
      </div>
    );
  }
  return null;
}
