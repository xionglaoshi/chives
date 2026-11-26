import { appPath } from '../appPath';
import type { ReactElement } from 'react';

export interface LogoProps {
  size?: number;
  title?: string | undefined;
  className?: string | undefined;
}
export function Logo({size = 32, title, className}: LogoProps): ReactElement {
  return <img src={appPath('/chives.svg')} width={size} height={size} alt={title ?? 'Chives'} className={className} />;
}
