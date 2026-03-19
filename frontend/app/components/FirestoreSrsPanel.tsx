"use client";

import { SrsData } from "../../lib/api";

// ─── Field registry ───────────────────────────────────────────────────────────

interface FieldDef {
  key: keyof SrsData;
  label: string;
}

interface SectionDef {
  number: string;
  title: string;
  fields: FieldDef[];
}

const SECTIONS: SectionDef[] = [
  {
    number: "1",
    title: "Context & Business Problem",
    fields: [
      { key: "s1_context",          label: "1.1 Context" },
      { key: "s1_business_problem", label: "1.2 Business Problem" },
    ],
  },
  {
    number: "2",
    title: "Target State & Success",
    fields: [
      { key: "s2_target_state", label: "2.1 Target State" },
      { key: "s2_success",      label: "2.2 Success" },
    ],
  },
  {
    number: "3",
    title: "Scope & Boundaries",
    fields: [
      { key: "s3_scope_in_out", label: "3.1 Scope — In/Out" },
      { key: "s3_boundaries",   label: "3.2 Boundaries" },
    ],
  },
  {
    number: "4",
    title: "Data, Systems, Integrations & Access",
    fields: [
      { key: "s4_data_systems",        label: "4.1 Data & Systems" },
      { key: "s4_integrations_access", label: "4.2 Integrations & Access" },
    ],
  },
];

// ─── Field card ───────────────────────────────────────────────────────────────

function FieldCard({ label, value }: { label: string; value: string | null | undefined }) {
  const filled = value != null && value.trim() !== "";

  if (!filled) {
    return (
      <div className="rounded border-2 border-dashed border-gray-200 bg-gray-50 px-3 py-2.5">
        <div className="flex items-center gap-2">
          <span className="text-[11px] font-semibold uppercase tracking-wide text-gray-400">
            {label}
          </span>
          <span className="ml-auto text-[10px] italic text-gray-300">—</span>
        </div>
      </div>
    );
  }

  let displayValue = value!;
  if (label.startsWith("3 System")) {
    try { displayValue = JSON.stringify(JSON.parse(value!), null, 2); } catch { /* leave as-is */ }
  }

  return (
    <div className="animate-fadeIn rounded border border-gray-200 bg-white px-3 py-2.5 shadow-sm">
      <div className="mb-1.5 flex items-center gap-2">
        <span className="text-[11px] font-semibold uppercase tracking-wide text-[#1a3a2a]">
          {label}
        </span>
        <span className="ml-auto shrink-0 rounded bg-[#e8f5e9] px-1.5 py-0.5 text-[10px] font-bold text-[#2e7d32]">
          FS
        </span>
      </div>
      <p className="whitespace-pre-wrap break-words text-sm leading-relaxed text-gray-700">
        {displayValue}
      </p>
    </div>
  );
}

// ─── Section group ────────────────────────────────────────────────────────────

function SectionGroup({ section, data }: { section: SectionDef; data: SrsData | null }) {
  const filledCount = section.fields.filter((f) => {
    const v = data?.[f.key];
    return v != null && String(v).trim() !== "";
  }).length;

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
          {filledCount}/{section.fields.length}
        </span>
      </div>
      <div className="space-y-1.5 pl-2">
        {section.fields.map((f) => (
          <FieldCard key={f.key} label={f.label} value={data?.[f.key] as string | null} />
        ))}
      </div>
    </div>
  );
}

// ─── Header ───────────────────────────────────────────────────────────────────

function PanelHeader({ data }: { data: SrsData | null }) {
  const totalFields = SECTIONS.reduce((sum, s) => sum + s.fields.length, 0);
  const filledFields = SECTIONS.reduce(
    (sum, s) =>
      sum +
      s.fields.filter((f) => {
        const v = data?.[f.key];
        return v != null && String(v).trim() !== "";
      }).length,
    0
  );
  const pct = totalFields > 0 ? Math.round((filledFields / totalFields) * 100) : 0;
  const updatedAt = data?.updated_at ? new Date(data.updated_at).toLocaleTimeString() : null;

  return (
    <div className="shrink-0 border-b border-gray-200 bg-white px-5 py-4">
      <div className="mb-2 flex items-center justify-between">
        <div>
          <p className="text-sm font-bold text-gray-800">Firestore — SRS Data</p>
          <p className="text-xs text-gray-400">
            {updatedAt ? `Last saved at ${updatedAt}` : "Saved automatically after each turn"}
          </p>
        </div>
        <span className="rounded bg-[#e8f5e9] px-2 py-1 text-xs font-bold text-[#2e7d32]">
          {filledFields}/{totalFields} fields
        </span>
      </div>
      <div className="h-2 w-full overflow-hidden rounded-full bg-gray-100">
        <div
          className="h-2 rounded-full bg-[#4caf50] transition-all duration-700"
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}

// ─── Main component ───────────────────────────────────────────────────────────

export default function FirestoreSrsPanel({ data }: { data: SrsData | null }) {
  if (!data) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-2 text-center">
        <svg width="32" height="32" viewBox="0 0 32 32" fill="none" className="text-gray-300">
          <ellipse cx="16" cy="10" rx="12" ry="5" stroke="currentColor" strokeWidth="1.5" />
          <path d="M4 10v12c0 2.76 5.37 5 12 5s12-2.24 12-5V10" stroke="currentColor" strokeWidth="1.5" />
          <path d="M4 16c0 2.76 5.37 5 12 5s12-2.24 12-5" stroke="currentColor" strokeWidth="1.5" />
        </svg>
        <p className="text-sm font-semibold text-gray-400">No data yet</p>
        <p className="max-w-[200px] text-xs text-gray-300">
          Firestore will be updated automatically after the first AI response.
        </p>
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col overflow-hidden">
      <PanelHeader data={data} />
      <div className="flex-1 space-y-5 overflow-y-auto p-4">
        {SECTIONS.map((section) => (
          <SectionGroup key={section.number} section={section} data={data} />
        ))}
      </div>
    </div>
  );
}
