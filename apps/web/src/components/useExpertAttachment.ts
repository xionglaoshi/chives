import {useEffect,useRef,useState} from 'react';
import {uploadBotFile} from '../api/client';

export type AskExpert=(prompt:string,attachment:Awaited<ReturnType<typeof uploadBotFile>>)=>void;

export function useExpertAttachment(open:AskExpert){
  const transfer=useRef<AbortController|null>(null);
  const [asking,setAsking]=useState<string|null>(null),[askError,setAskError]=useState('');
  useEffect(()=>()=>transfer.current?.abort(),[]);
  async function attach(id:string,file:File,prompt:string){
    if(transfer.current)return;
    const ctrl=new AbortController();
    transfer.current=ctrl;setAsking(id);setAskError('');
    try{
      const attachment=await uploadBotFile('expert',file,ctrl.signal);
      if(!ctrl.signal.aborted)open(prompt+'\n\n请在对话中直接写出完整解读，附件仅供参考，无需另做文档。',attachment);
    }catch{if(!ctrl.signal.aborted)setAskError('附件上传失败，请再点一次“问AI”。');}
    finally{transfer.current=null;if(!ctrl.signal.aborted)setAsking(null);}
  }
  return {asking,askError,attach};
}
