import { existsSync, lstatSync, realpathSync } from 'node:fs';
import { dirname, isAbsolute, relative, resolve, sep } from 'node:path';

const workspaceTools = new Set(['read','read_image','write','edit']);
const conversationTools = new Set(['todo_write','ask_user_question']);

export const name = 'chives-staff-boundary';
export const inject = ['tools'];

/** Business MCPs are registered by the owner; raw host interpreters cannot act as the owner. */
export function checkCall(exec, workspace, readOnly = false, attachmentsRead = true) {
  const tool = exec.name;
  if (tool.startsWith('mcp__') || conversationTools.has(tool)) return;
  const denied = '请使用已登记的 Chives 业务工具。人事和系统管理由用户操作。';
  if (readOnly && (tool === 'write' || tool === 'edit')) return '业务文件由承接岗位交付。';
  if (!workspaceTools.has(tool) || !workspace) return denied;
  const input = exec.arguments?.file_path;
  if (typeof input !== 'string' || !input || input.includes('\0') || input.startsWith('~')) return denied;
  const target = resolve(workspace, input);
  const local = relative(workspace, target);
  if (!local || isAbsolute(local) || local.split(sep).some(part => part.startsWith('.'))) return denied;
  if (!attachmentsRead && ['uploads','attachments'].includes(local.split(sep)[0])) return '客户已关闭附件读取。';
  // Resolve each existing ancestor. A dangling symlink must also fail closed.
  for (let part = target; ; part = dirname(part)) {
    try {
      if (lstatSync(part).isSymbolicLink() || realpathSync(part) !== part) return denied;
    } catch (error) {
      if (error.code !== 'ENOENT' || existsSync(part)) return denied;
    }
    if (part === workspace) break;
  }
}

export function apply(ctx, config) {
  ctx.tools.guard(exec => checkCall(exec, config.workspace, config.readOnly, config.attachmentsRead));
}
