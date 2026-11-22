import type { ReasoningEffort } from '@chives/server/protocol';

export const effortNames: Record<ReasoningEffort,string> = {
  minimal:'极低', low:'低', medium:'中', high:'高', xhigh:'很高', max:'最高'
};
