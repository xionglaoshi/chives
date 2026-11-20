import {appPath} from '../appPath';

export type Preferences = {
 name:string;avatar:string;email:string;phone:string;locale:string;timezone:string;density:string;fontSize:string;
 showProcess:boolean;showTools:boolean;busyMode:string;attachmentsRead:boolean;workspaceWrite:boolean;databaseRead:boolean;memoryWrite:boolean;portfolioAccess:boolean;autoUpdateOnCheck:boolean;
};
export async function desk<T>(section:string,method='GET',body?:unknown):Promise<T>{
 const res=await fetch(appPath('/api/settings/desk/'+section),{method,headers:{'Content-Type':'application/json','X-Chives-Kernel-Manager':'local'},...(body===undefined?{}:{body:JSON.stringify(body)})});
 const value=await res.json();
 if(!res.ok)throw Error(value.error?.message??'操作失败，请重试');
 return value as T;
}
export function applyDesk(p:Preferences){
 const el=document.documentElement;
 for(const k of ['fontSize','density','timezone','locale','busyMode','showTools','showProcess'] as const)el.dataset[k]=String(p[k]);
 el.lang=p.locale;
}
