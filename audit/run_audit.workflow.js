export const meta = {
  name: 'babylon-quant-audit',
  description: 'Run the 20-agent adversarial quant audit with RAM-safe concurrency (static fan-out, dynamic serialized)',
  phases: [
    { title: 'Static', detail: '15 code/logic auditors in parallel (zero data RAM)' },
    { title: 'Dynamic', detail: '5 probe auditors, max 2 concurrent (single-wallet/streaming)' },
    { title: 'Synthesize', detail: 'dedup + rank by blast radius → SUMMARY.md' },
  ],
}

// Each agent reads ground rules + its task file, writes audit/findings/NN_*.md.
// STATIC agents touch no data → safe to fan out. DYNAMIC agents run bounded probes →
// the pipeline() concurrency cap (min(16, cores-2)) plus the small dynamic set keeps the
// box from the OOM that crashed it. We further hard-limit dynamic concurrency to 2 below.

const GROUND = 'audit/00_GROUND_RULES.md'
const prompt = (nn, file) =>
  `You are adversarial quant auditor ${nn}. First read ${GROUND} in full (especially the ` +
  `RESOURCE SAFETY section — this box is an 8GB Mac and a prior run OOM-crashed it). Then read ` +
  `your task file audit/tasks/${file} and execute it. Obey every RAM rule: NEVER load ` +
  `other_repo_notes/fills_*.parquet (the 0.5-1GB monthlies); if you need fills use single ` +
  `data/follow/fills_his/<wallet>.parquet files with polars streaming; check vm_stat before any ` +
  `Python; default to static reasoning. Write your findings to audit/findings/${file.replace('.md','')}` +
  `.md in the format from the ground rules. Do not edit any source file. Return only the findings ` +
  `path and a one-line headline.`

const STATIC = [
  '01_universe_survivorship.md','02_lookahead_seam.md','03_follower_lag.md','04_neutralization_beta.md',
  '05_eligibility_selection.md','06_sortino_ranking.md','08_coverage_priceability.md',
  '09_disposition_mtm.md','10_cost_netting.md','13_capture_markout.md','14_capture_ingest.md',
  '16_capture_scorer_rederivability.md','17_reflexivity.md','18_gate_preregistration.md','19_execution_parity.md',
]
// Dynamic order: lightest/most-synthetic first. test-only probes (12,15) then single-wallet (11,20) then sweep (07).
const DYNAMIC = ['12_capture_stepper_parity.md','15_capture_store_restart.md','11_startposition_reconstruction.md',
  '20_engineering_ram_polars.md','07_bootstrap_ci.md']

phase('Static')
const staticResults = await parallel(STATIC.map(f => () =>
  agent(prompt(f.slice(0,2), f), { label: `audit:${f.slice(0,2)}`, phase: 'Static' })))

// Dynamic: hard cap of 2 concurrent regardless of the global slot cap.
phase('Dynamic')
const dynResults = []
for (let i = 0; i < DYNAMIC.length; i += 2) {
  const batch = DYNAMIC.slice(i, i + 2)
  const r = await parallel(batch.map(f => () =>
    agent(prompt(f.slice(0,2), f), { label: `audit:${f.slice(0,2)}`, phase: 'Dynamic' })))
  dynResults.push(...r)
}

phase('Synthesize')
const all = [...staticResults, ...dynResults].filter(Boolean).join('\n')
const summary = await agent(
  `Read every file in audit/findings/. Synthesize a single audit/SUMMARY.md: dedup overlapping ` +
  `findings, rank by blast radius (gate-false-GO first, then selection-power, then offline-estimate, ` +
  `then reporting), and for each CRITICAL/HIGH state whether it was confirmed by more than one agent. ` +
  `End with a short "what to fix before trusting the edge" list. The agent headlines were:\n${all}\n` +
  `Write the file and return its path.`,
  { label: 'audit:synthesize', phase: 'Synthesize' })
return { summary, agents: STATIC.length + DYNAMIC.length }
