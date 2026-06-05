import { useState } from "react";

type Kind = "up" | "down" | "note";

const ICON: Record<Kind, string> = { up: "👍", down: "👎", note: "💬" };
const TITLE: Record<Kind, string> = {
  up: "Stage looks right",
  down: "Something's wrong with this stage",
  note: "Add a note for the continuous-learning loop",
};
const TONE: Record<Kind, string> = {
  up: "hover:text-emerald-700",
  down: "hover:text-rose-700",
  note: "hover:text-zbrain",
};
const PLACEHOLDER: Record<Kind, string> = {
  up: "Optional: what was particularly good?",
  down: "What did the agent get wrong? Be specific.",
  note: "Free-text observation.",
};

export function StageFeedback({
  pipelineId,
  stage,
  snapshot,
}: {
  pipelineId: number;
  stage: string;
  snapshot: any;
}) {
  const [open, setOpen] = useState<Kind | null>(null);
  const [note, setNote] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [justSubmitted, setJustSubmitted] = useState<Kind | null>(null);

  const post = async (kind: Kind, text: string) => {
    await fetch("/api/feedback", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        pipeline_id: pipelineId,
        stage,
        kind: `${stage}_${kind}`,
        note: text || null,
        data: snapshot ? { stage_snapshot: snapshot } : {},
      }),
    });
  };

  const onClick = async (kind: Kind) => {
    if (kind === "up") {
      setSubmitting(true);
      try {
        await post(kind, "");
        setJustSubmitted(kind);
        setTimeout(() => setJustSubmitted(null), 1600);
      } finally {
        setSubmitting(false);
      }
      return;
    }
    setOpen(open === kind ? null : kind);
    setNote("");
  };

  const submitNote = async () => {
    if (!open) return;
    setSubmitting(true);
    try {
      await post(open, note);
      setJustSubmitted(open);
      setOpen(null);
      setNote("");
      setTimeout(() => setJustSubmitted(null), 1600);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="mt-2">
      <div className="flex items-center justify-end gap-0.5 text-[11px]">
        {justSubmitted ? (
          <span className="text-emerald-700">✓ feedback recorded</span>
        ) : (
          (["up", "down", "note"] as Kind[]).map((k) => (
            <button
              key={k}
              onClick={() => onClick(k)}
              disabled={submitting}
              title={TITLE[k]}
              className={`px-1.5 py-0.5 rounded text-zbrain-muted/70 ${TONE[k]} hover:bg-zbrain-50 transition-colors ${
                open === k ? "bg-zbrain-50 text-zbrain-ink" : ""
              }`}
            >
              {ICON[k]}
            </button>
          ))
        )}
      </div>
      {open && (
        <div className="mt-2 flex items-start gap-2">
          <textarea
            value={note}
            onChange={(e) => setNote(e.target.value)}
            placeholder={PLACEHOLDER[open]}
            autoFocus
            className="flex-1 text-xs border border-zbrain-divider rounded-md px-2 py-1.5 min-h-[52px] focus:border-zbrain"
          />
          <div className="flex flex-col gap-1">
            <button
              onClick={submitNote}
              disabled={submitting}
              className="btn-primary text-[10px] px-2 py-1 whitespace-nowrap"
            >
              {submitting ? "…" : "Submit"}
            </button>
            <button
              onClick={() => {
                setOpen(null);
                setNote("");
              }}
              className="text-[10px] text-zbrain-muted hover:text-zbrain-ink px-2 py-1"
            >
              Cancel
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
