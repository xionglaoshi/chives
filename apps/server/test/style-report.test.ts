import {it,expect} from 'vitest';
import {questionBank,buildStyleReport,styleAnswersSchema} from '../src/settings/style-report.js';

it('uses explicit answers, preserves missing dimensions, and respects hard spending limits',()=>{
  expect(questionBank).toHaveLength(72);
  const core=questionBank.filter(q=>q.initial);
  expect(core).toHaveLength(28);
  const data=Object.fromEntries(core.map(q=>[q.id,{choice:Math.min(3,q.options.length-1)}]));
  data['11']={choice:0};
  const r=buildStyleReport(data);
  expect(r.risk.grade).toBe(1);
  expect(r.dimensions).toHaveLength(8);
  expect(r.dimensions.every(d=>!d.comparison)).toBe(true);
  expect(buildStyleReport({}).risk.grade).toBeNull();
  expect(buildStyleReport({}).match.kind).toBe('insufficient');
  expect(styleAnswersSchema.safeParse({'28':{choice:99}}).success).toBe(false);
});
