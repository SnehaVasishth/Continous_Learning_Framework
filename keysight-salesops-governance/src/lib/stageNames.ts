// Canonical pipeline-stage display names. Single source of truth for any
// surface in the Governance app that renders a stage key (intake, extract,
// decide, execute, communicate, learning) to the operator.
//
// These names must match the SalesOps Dashboard STAGE_DEFS (frontend/src/
// pages/Dashboard.tsx) so an operator switching between the two apps sees
// identical language.
//
// Underlying stage keys are unchanged. Only the rendered text is centralised
// here. Add a new entry when the backend introduces a new stage; never inline
// a literal stage label elsewhere.

export const STAGE_DISPLAY: Record<string, string> = {
  intake: "Intake & Classification",
  extract: "Extraction & Enrichment",
  reconcile: "Reconcile",
  decide: "Decision & Confidence Scoring",
  execute: "Workflow Execution",
  communicate: "Communication & Close-out",
  learning: "Continuous Learning",
  // Auxiliary surfaces that appear in feedback logs but are not pipeline
  // stages. Keep them here so call sites have one map to consult.
  hitl: "HITL resolution",
  suggest_fix: "Suggest fix",
};

// Ordered list of the six canonical pipeline stage keys, matching the
// Dashboard funnel ordering. Use this when rendering filter pills or rows
// so the operator sees the same left-to-right sequence everywhere.
export const PIPELINE_STAGE_KEYS: string[] = [
  "intake",
  "extract",
  "decide",
  "execute",
  "communicate",
  "learning",
];

export function stageDisplay(key: string): string {
  return STAGE_DISPLAY[key] || key;
}
