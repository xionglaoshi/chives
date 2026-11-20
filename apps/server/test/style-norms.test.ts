import { expect, it } from 'vitest';
import { referencePosition } from '../src/settings/style-norms.js';

it('publishes only comparable samples and assigns ties their middle rank', () => {
  const counts = Array<number>(101).fill(0);
  counts[10] = 80;
  counts[50] = 10;
  counts[70] = 10;
  const reference = [{instrument: 'style-v2', form: 'core', dimensionId: 'riskAppetite',
    peerGroup: '测试样本', period: '测试期间', source: 'https://example.org/study', counts}] as const;
  const fixtures = [...reference];
  expect(referencePosition('riskAppetite', 50, 'core', fixtures)).toMatchObject({n:100, percentile:85, topPercent:15});
  expect(referencePosition('riskAppetite', 50, 'full', fixtures)).toBeNull();
  expect(referencePosition('concentration', 50, 'core', fixtures)).toBeNull();
  counts[10] = 79;
  expect(referencePosition('riskAppetite', 50, 'core', fixtures)).toBeNull();
});
