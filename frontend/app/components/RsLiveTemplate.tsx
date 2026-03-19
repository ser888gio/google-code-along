"use client";

import { RsPartialData } from "../../lib/api";

// ─── Subsection registry ──────────────────────────────────────────────────────

type SubsectionKey = string;

interface Subsection {
  key: SubsectionKey;
  number: string;
  label: string;
}

interface Chapter {
  number: string;
  title: string;
  subsections: Subsection[];
}

const CHAPTERS: Chapter[] = [
  {
    number: "1",
    title: "Context & Business Problem",
    subsections: [
      { key: "1_context",          number: "1.1", label: "Context" },
      { key: "1_business_problem", number: "1.2", label: "Business Problem" },
    ],
  },
  {
    number: "2",
    title: "Target State & Success",
    subsections: [
      { key: "2_target_state",   number: "2.1", label: "Target State" },
      { key: "2_success",        number: "2.2", label: "Success" },
    ],
  },
  {
    number: "3",
    title: "Scope & Boundaries",
    subsections: [
      { key: "3_scope_in_out",  number: "3.1", label: "Scope — In/Out" },
      { key: "3_boundaries",    number: "3.2", label: "Boundaries" },
    ],
  },
  {
    number: "4",
    title: "Data, Systems, Integrations & Access",
    subsections: [
      { key: "4_data_systems",       number: "4.1", label: "Data & Systems" },
      { key: "4_integrations_access", number: "4.2", label: "Integrations & Access" },
    ],
  },
];

// ─── Cards ────────────────────────────────────────────────────────────────────

function PlaceholderCard({ number, label }: { number: string; label: string }) {
  return (
    <div className="rounded border-2 border-dashed border-gray-200 bg-gray-50 px-3 py-2.5">
      <div className="flex items-center gap-2">
        <span className="shrink-0 rounded border border-gray-200 bg-white px-1.5 py-0.5 text-[10px] font-bold text-gray-400">
          {number}
        </span>
        <span className="text-[11px] font-semibold uppercase tracking-wide text-gray-400">
          {label}
        </span>
        <span className="ml-auto text-[10px] italic text-gray-300">Gathering…</span>
      </div>
    </div>
  );
}

function FilledCard({
  number,
  label,
  content,
}: {
  number: string;
  label: string;
  content: string;
}) {
  return (
    <div className="animate-fadeIn rounded border border-gray-200 bg-white px-3 py-2.5 shadow-sm">
      <div className="mb-1.5 flex items-center gap-2">
        <span className="shrink-0 rounded border border-[#c8e6c9] bg-[#e8f5e9] px-1.5 py-0.5 text-[10px] font-bold text-[#2e7d32]">
          {number}
        </span>
        <span className="text-[11px] font-semibold uppercase tracking-wide text-[#1a3a2a]">
          {label}
        </span>
        <span className="ml-auto shrink-0 rounded bg-[#e8f5e9] px-1.5 py-0.5 text-[10px] font-bold text-[#2e7d32]">
          AI
        </span>
      </div>
      <p className="whitespace-pre-wrap text-sm leading-relaxed text-gray-700">{content}</p>
    </div>
  );
}

// ─── Chapter group ────────────────────────────────────────────────────────────

function ChapterGroup({
  chapter,
  sections,
}: {
  chapter: Chapter;
  sections: RsPartialData["sections"] | undefined;
}) {
  const filledCount = chapter.subsections.filter((s) => {
    const sec = sections?.[s.key];
    return sec?.filled === true && sec.content != null && sec.content.trim() !== "";
  }).length;
  const total = chapter.subsections.length;

  return (
    <div>
      {/* Chapter header */}
      <div className="mb-2 flex items-center gap-2">
        <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded bg-[#1a3a2a] text-[11px] font-bold text-white">
          {chapter.number}
        </span>
        <span className="text-xs font-bold uppercase tracking-wide text-[#1a3a2a]">
          {chapter.title}
        </span>
        <span className="ml-auto text-[10px] text-gray-400">
          {filledCount}/{total}
        </span>
      </div>

      {/* Subsection cards */}
      <div className="space-y-1.5 pl-2">
        {chapter.subsections.map((sub) => {
          const sec = sections?.[sub.key];
          const isFilled =
            sec?.filled === true &&
            sec.content != null &&
            sec.content.trim() !== "";

          return isFilled ? (
            <FilledCard
              key={sub.key}
              number={sub.number}
              label={sub.label}
              content={sec!.content!}
            />
          ) : (
            <PlaceholderCard key={sub.key} number={sub.number} label={sub.label} />
          );
        })}
      </div>
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

  const statusLabel =
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
          title={
            canGenerate
              ? "Generate the full document"
              : `Reach 80% completeness to generate (currently ${completeness}%)`
          }
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

      <div>
        <div className="mb-1 flex justify-between text-[10px]">
          <span className={`font-semibold ${textColor}`}>
            {completeness}% — {statusLabel}
          </span>
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
      <CompletenessHeader completeness={completeness} onGenerateFull={onGenerateFull} />

      <div className="flex-1 space-y-5 overflow-y-auto p-4">
        {CHAPTERS.map((chapter) => (
          <ChapterGroup
            key={chapter.number}
            chapter={chapter}
            sections={rsPartial?.sections}
          />
        ))}
      </div>
    </div>
  );
}
