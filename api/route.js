const HIGH_RISK = ['security','production','incident','breach','rollback','migration','architecture decision','delete','payment','billing','credentials'];
const JUDGE = ['final review','independent review','approve release','release gate','judge','security review','production approval'];
const WORKER = ['code','function','debug','fix','refactor','implement','bug','error','python','javascript','typescript','api','endpoint','build','deploy','repo','pull request','commit','branch','database','sql','scrape','browser','tool','workflow','automation'];
const REASON = ['analyze','plan','reason','decide','architect','design','evaluate','compare','assess','strategize','research','investigate','optimize','complex','audit'];

export function classify(mission='') {
  const text = String(mission).toLowerCase().replace(/\s+/g,' ').trim();
  const words = text ? text.split(' ') : [];
  if (JUDGE.some(x => text.includes(x))) return {taskType:'judge', lane:'judge', model:'anthropic/claude-opus-5', maxTokens:1400};
  const risk = HIGH_RISK.some(x => text.includes(x));
  const reasoning = REASON.some(x => text.includes(x));
  const worker = WORKER.some(x => text.includes(x));
  if (risk || (reasoning && words.length >= 28)) return {taskType:'reasoning', lane:'reasoner', model:'openai/gpt-5.6-sol', maxTokens:1100};
  if (worker) return {taskType:'worker', lane:'worker', model:'google/gemini-3.6-flash', maxTokens:700};
  if (reasoning) return {taskType:'reasoning_light', lane:'worker', model:'google/gemini-3.6-flash', maxTokens:700};
  return {taskType:'default', lane:'flash', model:'google/gemini-3.5-flash-lite', maxTokens:320};
}

export default function handler(req,res){
  res.setHeader('Cache-Control','no-store');
  const mission = req.method === 'POST' ? String((req.body||{}).mission||'') : String(req.query?.mission||'');
  if (!mission.trim()) return res.status(400).json({ok:false,error:'mission required'});
  res.status(200).json({ok:true,router:'BARS Router V2',routing:'deterministic',gateway:'Vercel AI Gateway when configured',...classify(mission)});
}
