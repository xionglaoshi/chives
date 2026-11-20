import { AppError } from '../errors.js';
import type { Store } from '../store/index.js';

export const preferenceKey = 'workbench.preferences.v1';
export const defaults = {
  name:'', avatar:'', email:'', phone:'', locale:'zh-CN', timezone:'Asia/Shanghai',
  density:'comfortable', fontSize:'standard', showProcess:true, showTools:true, busyMode:'queue',
  autoUpdateOnCheck:false, attachmentsRead:true, workspaceWrite:true, databaseRead:true, memoryWrite:true, portfolioAccess:true,
};
export type Preferences = typeof defaults;
const choices: Record<string, string[]> = {
  locale:['zh-CN','en-US'], timezone:['Asia/Shanghai','Asia/Hong_Kong','Asia/Tokyo','America/New_York','Europe/London','UTC'],
  density:['comfortable','compact'], fontSize:['small','standard','large'], busyMode:['queue','interrupt'],
};
export function parsePreferences(patch:Record<string,unknown>, current:Preferences):Preferences {
  const out={...current};
  for (const [key,value] of Object.entries(patch)) {
    const fail=()=>new AppError(400,'invalid_preference','设置值无效：'+key);
    if (!Object.hasOwn(defaults,key) || typeof value!==typeof defaults[key as keyof Preferences]) throw fail();
    if (typeof value==='string') {
      if (choices[key] && !choices[key]!.includes(value)) throw fail();
      if (key==='avatar') {
        if (value && (!/^data:image\/(png|jpeg|webp);base64,[a-zA-Z0-9+/]+=*$/.test(value)||value.length>260000)) throw fail();
      } else if (value.length>200 || /[\x00-\x1f]/.test(value)) throw fail();
      if (key==='email' && value && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value)) throw fail();
    }
    Object.assign(out,{[key]:value});
  }
  return out;
}
export function preferences(store:Store) {
  return {...defaults,...store.settings.get<Partial<Preferences>>(preferenceKey)};
}
