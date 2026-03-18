"use client";

import { RsPartialData, RsSectionKey } from "../../lib/api";

// ─── Section metadata ─────────────────────────────────────────────────────────

const RS_SECTIONS: { key: RsSectionKey; label: string; number: string }[] = [
  { key: "executive_summary",           label: "Executive Summary",           number: "1" },
  { key: "current_state",               label: "Current State (As-Is)",       number: "2" },
  { key: "desired_future_state",        label: "Desired Future State (To-Be)", number: "3" },
  { key: "scope",                       label: "Scope",                       number: "4" },
  { key: "functional_requirements",     label: "Functional Requirements",     number: "5" },
  { key: "non_functional_requirements", label: "Non-Functional Requirements", number: "6" },
  { key: "assumptions_and_constraints", label: "Assumptions & Constraints",   number: "7" },
  { key: "open_questions",              label: "Open Questions",              number: "8" },
];

// ─── Section cards ────────────────────────────────────────────────────────────

function PlaceholderCard({ label, number }: { label: string; number: string }) {
  return (
    <div className="rounded-lg border-2 border-dashed border-gray-200 bg-gray-50 p-4">
      <div className="mb-2 flex items-center gap-2">
        <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded border border-gray-200 bg-white text-[10px] font-bold text-gray-400">
          {number}
        </span>
        <span className="text-[11px] font-semibold uppercase tracking-wide text-gray-400">
          {label}
        </span>
      </div>
      <p className="text-sm italic text-gray-400">Gathering information…</p>
    </div>
  );
}

function FilledCard({
  label,
  number,
  content,
}: {
  label: string;
  number: string;
  content: string;
}) {
  return (
    <div className="animate-fadeIn rounded-lg border border-gray-200 bg-white p-4 shadow-sm">
      <div className="mb-2 flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded border border-[#c8e6c9] bg-[#e8f5e9] text-[10px] font-bold text-[#2e7d32]">
            {number}
          </span>
          <span className="text-[11px] font-semibold uppercase tracking-wide text-[#1a3a2a]">
            {label}
          </span>
        </div>
        <span className="shrink-0 rounded bg-[#e8f5e9] px-1.5 py-0.5 text-[10px] font-bold text-[#2e7d32]">
          AI
        </span>
      </div>
      <p className="whitespace-pre-wrap text-sm leading-relaxed text-gray-700">{content}</p>
    </div>
  );
}

// ─── Completeness header ──────────────────────────────────────────────────────

function CompletenessHeader({
  completeness,
  onGenerateFull,
}: {
  completeness: number;
  onGenerateFull: () => void;
}) {
  const canGenerate = completeness >= 80;

  const barColor =
    completeness >= 80 ? "bg-[#4caf50]" :
    completeness >= 50 ? "bg-orange-400" :
    "bg-red-400";

  const textColor =
    completeness >= 80 ? "text-[#2e7d32]" :
    completeness >= 50 ? "text-orange-600" :
    "text-red-500";

  const label =
    completeness >= 80 ? "Ready to generate" :
    completeness >= 50 ? "Getting there…" :
    "Keep chatting";

  return (
    <div className="shrink-0 border-b border-gray-200 bg-white px-5 py-4">
      <div className="mb-3 flex items-center justify-between">
        <div>
          <p className="text-sm font-bold text-gray-800">Requirements Specification</p>
          <p className="text-xs text-gray-400">Filling automatically as you chat</p>
        </div>
        <button
          onClick={onGenerateFull}
          disabled={!canGenerate}
          title={canGenerate ? "Generate the full document" : `Reach 80% completeness to generate (currently ${completeness}%)`}
          className={`flex items-center gap-1.5 rounded px-3 py-2 text-xs font-semibold transition-all ${
            canGenerate
              ? "bg-[#4a6659] text-white hover:opacity-90"
              : "cursor-not-allowed bg-gray-100 text-gray-400"
          }`}
        >
          <svg width="12" height="12" viewBox="0 0 12 12" fill="none">
            <path
              d="M1 9l3-3 2 2 4-5"
              stroke="currentColor"
              strokeWidth="1.5"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
          {canGenerate ? "Generate Full Document" : `${completeness}% — keep chatting`}
        </button>
      </div>

      {/* Progress bar */}
      <div>
        <div className="mb-1 flex justify-between text-[10px]">
          <span className={`font-semibold ${textColor}`}>{completeness}% — {label}</span>
          <span className="text-gray-400">80% to generate</span>
        </div>
        <div className="h-2 w-full overflow-hidden rounded-full bg-gray-100">
          <div
            className={`h-2 rounded-full transition-all duration-700 ${barColor}`}
            style={{ width: `${completeness}%` }}
          />
        </div>
      </div>
    </div>
  );
}

// ─── Main component ───────────────────────────────────────────────────────────

export default function RsLiveTemplate({
  rsPartial,
  onGenerateFull,
}: {
  rsPartial: RsPartialData | null;
  onGenerateFull: () => void;
}) {
  const completeness = rsPartial?.completeness ?? 0;

  return (
    <div className="flex h-full flex-col overflow-hidden">
      {/* Header with completeness bar + generate button */}
      <CompletenessHeader completeness={completeness} onGenerateFull={onGenerateFull} />

      {/* Section cards */}
      <div className="flex-1 space-y-3 overflow-y-auto p-4">
        {RS_SECTIONS.map(({ key, label, number }) => {
          const section = rsPartial?.sections[key];
          const isFilled =
            section?.filled === true &&
            section.content != null &&
            section.content.trim() !== "";

          return isFilled ? (
            <FilledCard key={key} label={label} number={number} content={section!.content!} />
          ) : (
            <PlaceholderCard key={key} label={label} number={number} />
          );
        })}
      </div>
    </div>
  );
}
