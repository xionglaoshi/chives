export interface ImportedModel {
  apiKey:string;
  model:string;
  baseURL:string;
  api:string;
  displayName:string;
}

// Input comes exclusively from the file the user picked in the browser.
export function readModelFile(text:string):ImportedModel[] {
  let config:Record<string,unknown>;
  if(text.trimStart().startsWith('{')){
    config=JSON.parse(text);
    if(!config||Array.isArray(config)||typeof config!=='object')throw Error();
  }else{
    config={};
    for(const line of text.split(/\r?\n/)){
      const pair=/^(?:export\s+)?([A-Z][A-Z_0-9]*)\s*=\s*(.*?)\s*$/.exec(line);
      if(pair)config[pair[1]!]=pair[2]!.replace(/^(['"])(.*)\1$/,'$2');
    }
  }
  const fields=config.env && typeof config.env==='object'?config.env as Record<string,unknown>:config;
  const val=(obj:Record<string,unknown>,name:string)=>typeof obj[name]==='string'?(obj[name] as string).trim():'';
  if(val(config,'apiKey')&&val(config,'baseURL')){
    return [{apiKey:val(config,'apiKey'),model:val(config,'model'),baseURL:val(config,'baseURL'),api:val(config,'api')||'openai-completions',displayName:val(config,'displayName')}];
  }
  const defs=[
    ['OPENAI','OpenAI','https://api.openai.com/v1','openai-responses'],
    ['ANTHROPIC','Anthropic','https://api.anthropic.com/v1','anthropic-messages'],
    ['DEEPSEEK','DeepSeek','https://api.deepseek.com/v1','openai-completions'],
  ] as const;
  const result:ImportedModel[]=[];
  for(const [prefix,label,base,api] of defs){
    const apiKey=val(fields,prefix+'_API_KEY');
    if(apiKey)result.push({apiKey,baseURL:val(fields,prefix+'_BASE_URL')||base,model:val(fields,prefix+'_MODEL'),api,displayName:label});
  }
  if(!result.length)throw Error('找不到支持的 API Key');
  return result;
}
