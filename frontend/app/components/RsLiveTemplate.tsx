"use client";

import { RsPartialData } from "../../lib/api";

// ─── Field schema (mirrors FIELD_SCHEMA in backend/agent/discovery_agent.py) ──

interface FieldDef {
  key: string;
  label: string;
  required: boolean;
}

interface Section {
  number: number;
  title: string;
  fields: FieldDef[];
}

const SECTIONS: Section[] = [
  {
    number: 1,
    title: "Identity & Current State",
    fields: [
      { key: "use_case_title",  label: "Use Case Title",             required: true },
      { key: "department",      label: "Customer Department",         required: true },
      { key: "requestor",       label: "Requestor",                   required: true },
      { key: "product_owner",   label: "Product Owner",               required: true },
      { key: "process_as_is",   label: "Process Description / As-Is", required: true },
      { key: "process_context", label: "Process Context",             required: true },
      { key: "trigger",         label: "Trigger",                     required: true },
    ],
  },
  {
    number: 2,
    title: "Target State",
    fields: [
      { key: "purpose_to_be", label: "Purpose / To-Be", required: true },
    ],
  },
  {
    number: 3,
    title: "Value & ROI",
    fields: [
      { key: "saved_time_hours_per_year", label: "Saved Time (hours/year)", required: false },
      { key: "cost_saving",               label: "Cost Saving",              required: false },
      { key: "revenue_increase",          label: "Revenue Increase",         required: false },
      { key: "impacted_users",            label: "Impacted Users",           required: true  },
      { key: "add_value",                 label: "Added Value",              required: true  },
    ],
  },
  {
    number: 4,
    title: "Priority & Risk",
    fields: [
      { key: "time_criticality",  label: "Time Criticality",  required: true  },
      { key: "strategic_impact",  label: "Strategic Impact",  required: true  },
      { key: "risk_avoidance",    label: "Risk Avoidance",    required: false },
    ],
  },
  {
    number: 5,
    title: "Technical Context",
    fields: [
      { key: "systems_and_tools",            label: "Systems & Tools Involved",       required: true },
      { key: "document_types",               label: "Types of Documents Involved",    required: true },
      { key: "data_security_classification", label: "Data Security Classification",   required: true },
      { key: "solution_type",                label: "Solution Type",                  required: true },
    ],
  },
  {
    number: 6,
    title: "Additional",
    fields: [
      { key: "comments",    label: "Comments",    required: false },
      { key: "attachments", label: "Attachments", required: false },
    ],
  },
];

// ─── Cards ────────────────────────────────────────────────────────────────────

function PlaceholderCard({ label }: { label: string }) {
  return (
    <div className="rounded border-2 border-dashed border-gray-200 bg-gray-50 px-3 py-2.5">
      <div className="flex items-center gap-2">
        <span className="text-[11px] font-semibold uppercase tracking-wide text-gray-400">
          {label}
        </span>
        <span className="ml-auto text-[10px] italic text-gray-300">Gathering…</span>
      </div>
    </div>
  );
}

function FilledCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="animate-fadeIn rounded border border-gray-200 bg-white px-3 py-2.5 shadow-sm">
      <div className="mb-1.5 flex items-center gap-2">
        <span className="text-[11px] font-semibold uppercase tracking-wide text-[#1a3a2a]">
          {label}
        </span>
        <span className="ml-auto shrink-0 rounded bg-[#e8f5e9] px-1.5 py-0.5 text-[10px] font-bold text-[#2e7d32]">
          AI
        </span>
      </div>
      <p className="whitespace-pre-wrap text-sm leading-relaxed text-gray-700">{value}</p>
    </div>
  );
}

// ─── Section group ────────────────────────────────────────────────────────────

function SectionGroup({
  section,
  fields,
}: {
  section: Section;
  fields: RsPartialData["fields"] | undefined;
}) {
  const filledCount = section.fields.filter((f) => {
    const entry = fields?.[f.key];
    return entry?.filled === true && entry.value != null && entry.value.trim() !== "";
  }).length;
  const total = section.fields.length;

  return (
    <div>
      <div className="mb-2 flex items-center gap-2">
        <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded bg-[#1a3a2a] text-[11px] font-bold text-white">
          {section.number}
        </span>
        <span className="text-xs font-bold uppercase tracking-wide text-[#1a3a2a]">
          {section.title}
        </span>
        <span className="ml-auto text-[10px] text-gray-400">
          {filledCount}/{total}
        </span>
      </div>

      <div className="space-y-1.5 pl-2">
        {section.fields.map((f) => {
          const entry = fields?.[f.key];
          const isFilled =
            entry?.filled === true &&
            entry.value != null &&
            entry.value.trim() !== "";

          return isFilled ? (
            <FilledCard key={f.key} label={f.label} value={entry!.value!} />
          ) : (
            <PlaceholderCard key={f.key} label={f.label} />
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
  isExtracting = false,
}: {
  rsPartial: RsPartialData | null;
  onGenerateFull: () => void;
  isExtracting?: boolean;
}) {
  const completeness = rsPartial?.completeness ?? 0;

  return (
    <div className="flex h-full flex-col overflow-hidden">
      <CompletenessHeader completeness={completeness} onGenerateFull={onGenerateFull} />
      {isExtracting && (
        <div className="shrink-0 bg-amber-50 px-4 py-1.5 text-center text-[11px] text-amber-700 border-b border-amber-100">
          Processing…
        </div>
      )}

      <div className="flex-1 space-y-5 overflow-y-auto p-4">
        {SECTIONS.map((section) => (
          <SectionGroup
            key={section.number}
            section={section}
            fields={rsPartial?.fields}
          />
        ))}
      </div>
    </div>
  );
}
