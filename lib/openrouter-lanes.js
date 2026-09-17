// OpenRouter lane routing for the hosted BARS build - mirrors the desktop
// runtime router (bars_router.py OPENROUTER_LANE_PREFS). One canonical map so
// the UI, the classifier, and the chat path all describe the same gateway.
export const OPENROUTER_BASE = 'https://openrouter.ai/api/v1';

export const LANE_PREFS = {
  flash: ['deepseek/deepseek-chat-v3.1'],
  worker: ['deepseek/deepseek-chat-v3.1'],
  reasoner: ['deepseek/deepseek-chat-v3.1'],
  judge: ['nousresearch/hermes-3-llama-3.1-405b:free'],
};

const LANE_NOTES = {
  flash: 'default lane - quick answers, cheapest',
  worker: 'code, tools, build-and-fix jobs',
  reasoner: 'planning, analysis, high-risk judgement',
  judge: 'independent release review',
};

export function laneModel(lane, env = process.env) {
  const prefs = LANE_PREFS[lane] || LANE_PREFS.flash;
  const override = env[`BARS_${String(lane).toUpperCase()}_MODEL`];
  return String(override || prefs[0]);
}

export function modelOptions(env = process.env) {
  return Object.keys(LANE_PREFS).map((lane) => ({
    id: laneModel(lane, env),
    lane,
    label: laneModel(lane, env),
    note: lane + ' lane - ' + LANE_NOTES[lane],
  }));
}

export function allowedModels(env = process.env) {
  const set = new Set();
  for (const lane of Object.keys(LANE_PREFS)) {
    for (const m of LANE_PREFS[lane]) set.add(m);
    set.add(laneModel(lane, env));
  }
  if (env.BARS_HERMES_MODEL) set.add(String(env.BARS_HERMES_MODEL));
  return set;
}
