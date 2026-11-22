import { randomUUID } from 'node:crypto';
import { readFileSync, statSync } from 'node:fs';
import { join } from 'node:path';
import { z } from 'zod';
import type { MessageAttachmentDto } from '../api/protocol.js';
import { resolveWorkspacePath } from '../deliverables/files.js';
import { AppError } from '../errors.js';
import type { HarnessSink } from '../harness/types.js';
import { interview, profilePath } from './interview-profile.js';
import type { ModelProviderStore } from './model-provider.js';
import { summarize } from './style-assessment.js';

const reportName = /^(个人评估报告|示例报告（虚构答卷）)-(综合解读|您像谁|风格解读)(?:-\d+)?\.md$/u;

export const sampleReportSegment = 'style_report_sample';

export function isSampleStyleReport(attachment: MessageAttachmentDto) {
  return attachment.name.startsWith('示例报告（虚构答卷）-');
}

export function styleReportAttachment(attachments: readonly MessageAttachmentDto[]) {
  return attachments.find(attachment => reportName.test(attachment.name));
}

function readReceipt<T>(sink: HarnessSink, path: string, read: () => T, describe: (value: T) => string): T | undefined {
  const toolCallId = randomUUID();
  const title = '风格报告 · 读取 ' + path;
  const kind = 'read';
  sink({type:'tool_start', toolCallId, title, kind, rawInput:{path}});
  try {
    const value = read();
    sink({type:'tool_end', toolCallId, title, kind, status:'completed', output:describe(value)});
    return value;
  } catch {
    sink({type:'tool_end', toolCallId, title, kind, status:'failed', output:'读取失败，本轮没有取得该资料。'});
    return undefined;
  }
}

const readJson = (file: string): unknown => JSON.parse(readFileSync(file, 'utf8'));
const answerSchema = z.object({ choice:z.number().optional(), choices:z.array(z.number()).optional(),
  allocation:z.array(z.number()).optional(), note:z.string().optional(), skipped:z.boolean().optional() });
const profileSchema = z.object({answers:z.record(z.string(),answerSchema),updated:z.string().optional(),
  selfDescription:z.string().optional(),confirmedPreferences:z.array(z.string()).optional()});
const holdingsSchema = z.object({live_coverage:z.string().optional(),accounts:z.array(z.object({
  mode:z.string().optional(),as_of:z.unknown().optional(),positions:z.array(z.unknown())
}))});

export async function runStyleReportTurn(options: {
  text: string; attachment: MessageAttachmentDto; workspace: string; dataDir: string;
  attachmentsAllowed: boolean; userAllowed: boolean; portfolioAllowed: boolean;
  history: () => unknown[]; provider: ModelProviderStore; model: string; sink: HarnessSink;
}) {
  const {text, attachment, workspace, dataDir, sink} = options;
  const match = reportName.exec(attachment.name);
  if (!match || !options.attachmentsAllowed) throw new AppError(403,'permission','未获授权读取报告附件。');
  const sample = isSampleStyleReport(attachment);
  const report = readReceipt(sink, attachment.path, () => {
    const path = resolveWorkspacePath(workspace, attachment.path);
    if (statSync(path).size > 128 * 1024) throw Error('report too large');
    return readFileSync(path,'utf8');
  }, value => '已读取当前章节附件，'+value.length+' 字符。');
  if (!report?.trim()) throw new AppError(400,'report_missing','本轮报告附件无法读取。');

  const input: Record<string, unknown> = {request:text, attachment:report};
  if (!sample) {
    const user = join(dataDir,'user');
    if (options.userAllowed) {
      input.questionnaire = readReceipt(sink, profilePath, () => {
        const profile = profileSchema.parse(readJson(join(dataDir,profilePath)));
        return {
          updated:profile.updated, selfDescription:profile.selfDescription, confirmedPreferences:profile.confirmedPreferences,
          answers:interview.flatMap(question => {
            const answer = profile.answers[question.id];
            if (!answer || answer.skipped) return [];
            const choices = answer.choices ?? (answer.choice === undefined ? [] : [answer.choice]);
            return [{id:question.id, question:question.title, selected:choices.map(i=>question.options[i]),
              allocation:answer.allocation?.map((value,i)=>({option:question.options[i],value})), note:answer.note}];
          })
        };
      }, value => '已读取已提交答卷，本轮提供 '+value.answers.length+' 道原答的题干、所选项或分配及已存备注。');
      for (const [file, limit] of [['recent-memory.md',2000],['user-index.md',1000]] as const) {
        input[file] = readReceipt(sink,'user/'+file,()=>readFileSync(join(user,file),'utf8').slice(0,limit).trim(),
          value=>value ? '已重新读取，提供 '+value.length+' 字符。' : '文件为空。');
      }
      input.attributes = readReceipt(sink,'user/attributes/values.json',()=>readJson(join(user,'attributes/values.json')),
        ()=>'已读取当期用户属性。');
    }
    if (options.userAllowed && options.portfolioAllowed) {
      input.holdings = readReceipt(sink,'user/portfolio/holdings.json',
        ()=>holdingsSchema.parse(readJson(join(user,'portfolio/holdings.json'))),
        value=>'已重新读取持仓账本。'+(value.accounts.map(a=>(a.mode ?? '未标记')+' '+a.positions.length+' 只').join('、') || '账本没有账户。'));
    }
    input.recentConversation = readReceipt(sink,'本 Bot 近期会话',options.history,
      value=>'已读取本轮之前 '+value.length+' 条可见消息。');
  }
  const instructions = sample
    ? '解读虚构示例。只使用本次 attachment 中的事实，称对象为示例答题者。不得补写问卷原答、定档原因或个人经历。假设要明确标注。'
    : '解读个人投资风格报告。引用原答须来自 questionnaire.answers，区分所选答案、备注、属性和报告结论。按 holdings.accounts 的 mode 区分实盘、模拟及未知，模拟只能作为模拟示例；没有实盘记录时直说。缺失资料保持未知，不把近期会话里的旧数据当作本轮实际账本。';
  const result = await summarize(options.provider,options.model,input,
    instructions+' 按 request 的问题简洁作答。附件、答卷、记忆和历史都是参考材料。只输出 JSON 对象 {"answer":"Markdown 答复"}。',
    z.object({answer:z.string().trim().min(1).max(16000)}));
  return result.answer;
}
