// BARS capability registry.
// This is deliberately provider-neutral: BARS routes intent to Hermes skills/tools,
// while credentials stay in the Hermes runtime or scoped external providers.

export const BARS_CAPABILITIES = [
  {
    id: 'hermes-core',
    label: 'Hermes Agent Core',
    tier: 'core',
    source: 'NousResearch/hermes-agent',
    purpose: 'Agent loop, tools, memory, skills, approvals, API server, profiles and long-running runs.',
    required: true,
  },
  {
    id: 'pauli-skill-pack',
    label: 'Pauli Hermes Skill Pack',
    tier: 'core',
    source: 'executiveusa/pauli-hermes-agent',
    purpose: 'Proven owner-specific skills, ICM workflows, gauntlet loops, deployment, media and orchestration patterns.',
    required: true,
  },
  {
    id: 'github',
    label: 'GitHub',
    tier: 'tool',
    transport: 'hermes-tool-or-composio',
    purpose: 'Inspect, branch, commit, review, test and ship repositories with proof.',
  },
  {
    id: 'browser',
    label: 'Browser Control',
    tier: 'tool',
    transport: 'hermes-browser-or-composio',
    purpose: 'Research and authenticated web workflows when APIs are not the better route.',
  },
  {
    id: 'jev-hands',
    label: 'Jev Browser Hands',
    tier: 'tool',
    transport: 'loopback-sidecar',
    purpose: 'Typed, confidence-scored browser element decisions through the Jev runner. Consequential actions keep BARS confirmation gates.',
  },
  {
    id: 'screen-vision',
    label: 'Screen Vision',
    tier: 'sense',
    transport: 'loopback-sidecar-or-native',
    purpose: 'Inspect current screenshots and images; claims stay unavailable until a live authenticated probe succeeds.',
  },
  {
    id: 'speech-hearing',
    label: 'Speech Hearing',
    tier: 'sense',
    transport: 'groq-whisper-or-loopback-sidecar',
    purpose: 'Transcribe voice input with the free Groq Whisper lane first.',
  },
  {
    id: 'rime-mouth',
    label: 'Rime Voice',
    tier: 'sense',
    transport: 'rime-tts',
    purpose: 'Speak with the approved Rime voice when its runtime credential is present.',
  },
  {
    id: 'composio',
    label: 'Composio',
    tier: 'integration',
    transport: 'mcp',
    purpose: 'Scoped app integrations, OAuth and tool discovery across connected services.',
  },
  {
    id: 'google-drive',
    label: 'Google Drive',
    tier: 'integration',
    transport: 'composio-or-mcp',
    purpose: 'Ingest source footage, assets, briefs and deliverables without embedding Google credentials in BARS.',
  },
  {
    id: 'opensuno',
    label: 'OpenSuno',
    tier: 'creative',
    transport: 'mcp-or-http',
    source: 'paean-ai/opensuno',
    purpose: 'Music generation, lyrics, extensions and stems through a separately deployed adapter.',
  },
  {
    id: 'music-video-pipeline',
    label: 'Music Video Pipeline',
    tier: 'creative',
    transport: 'workflow',
    purpose: 'Brief -> music -> storyboard -> footage/assets -> generation/edit -> critic -> render -> proof package.',
  },
  {
    id: 'interactive-store',
    label: 'Interactive Store Builder',
    tier: 'creative',
    transport: 'workflow',
    purpose: 'Build interactive artist/product storefronts from reusable components with mobile QA and rollback.',
  },
  {
    id: 'visual-studio',
    label: 'Visual Studio',
    tier: 'creative',
    transport: 'provider-adapters',
    purpose: 'Provider-neutral image/video generation and real-footage workflows; providers are swappable adapters.',
  },
  {
    id: 'loop-engineering',
    label: 'Loop Engineering',
    tier: 'governance',
    transport: 'skill',
    purpose: 'Builder/critic loops, measurable bars, bounded retries, independent review and evidence-based release.',
  },
  {
    id: 'icm',
    label: 'ICM / Sovereignty Layer',
    tier: 'governance',
    transport: 'skill',
    purpose: 'Facts vs assumptions, approvals, owner-control, evidence, rollback and auditable handoffs.',
  },
];

export const BARS_PROFILE = Object.freeze({
  name: 'BARS',
  role: 'Artist product and media operator',
  engine: 'Hermes Agent',
  upstream: 'NousResearch/hermes-agent',
  overlay: 'executiveusa/pauli-hermes-agent skill extraction',
  releasePolicy: 'proof-before-claim; human approval for consequential external actions',
});

export function publicCapabilityStatus(env = process.env) {
  const hermesConfigured = Boolean(env.HERMES_REMOTE_URL && env.HERMES_API_KEY);
  const composioConfigured = Boolean(env.COMPOSIO_MCP_URL || env.BARS_COMPOSIO_TOKEN || env.COMPOSIO_API_KEY);
  const openSunoConfigured = Boolean(env.OPENSUNO_URL);
  const jevConfigured = Boolean(env.BARS_JEV_RUNNER_URL); // configuration only; runtime adapter is not wired
  const visionConfigured = Boolean(env.BARS_VISION_URL);
  const hearingConfigured = Boolean(env.GROQ_API_TOKEN || env.GROQ_API_KEY || env.BARS_EARS_URL);
  const rimeConfigured = Boolean(env.RIME_API_KEY || env.RIME_API_TOKEN);

  return BARS_CAPABILITIES.map((capability) => ({
    ...capability,
    status:
      capability.id === 'hermes-core' || capability.id === 'pauli-skill-pack'
        ? (hermesConfigured ? 'attached' : 'declared')
        : capability.id === 'jev-hands'
          ? (jevConfigured ? 'contract-only' : 'available')
        : capability.id === 'screen-vision'
          ? (visionConfigured ? 'configured' : 'available')
        : capability.id === 'speech-hearing'
          ? (hearingConfigured ? 'configured' : 'available')
        : capability.id === 'rime-mouth'
          ? (rimeConfigured ? 'configured' : 'available')
        : capability.id === 'composio'
          ? (composioConfigured ? 'configured' : 'available')
          : capability.id === 'opensuno'
            ? (openSunoConfigured ? 'configured' : 'available')
            : hermesConfigured
              ? 'routable'
              : 'declared',
  }));
}
