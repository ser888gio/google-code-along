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
    title: "Introduction",
    fields: [
      { key: "s1_1_purpose",                 label: "1.1 Purpose" },
      { key: "s1_2_project_scope",           label: "1.2 Project Scope" },
      { key: "s1_3_requester",               label: "1.3 Requester" },
      { key: "s1_4_product_owner",           label: "1.4 Product Owner" },
      { key: "s1_5_sponsor",                 label: "1.5 Sponsor" },
      { key: "s1_6_delivery_responsibility", label: "1.6 Delivery Responsibility" },
    ],
  },
  {
    number: "2",
    title: "Overall Description",
    fields: [
      { key: "s2_1_product_perspective",      label: "2.1 Product Perspective" },
      { key: "s2_2_product_features",         label: "2.2 Product Features" },
      { key: "s2_3_user_classes",             label: "2.3 User Classes and Characteristics" },
      { key: "s2_4_operating_environment",    label: "2.4 Operating Environment" },
      { key: "s2_5_design_constraints",       label: "2.5 Design and Implementation Constraints" },
      { key: "s2_6_user_documentation",       label: "2.6 User Documentation" },
      { key: "s2_7_assumptions_dependencies", label: "2.7 Assumptions and Dependencies" },
    ],
  },
  {
    number: "3",
    title: "System Features",
    fields: [
      { key: "s3_system_features", label: "3 System Features" },
    ],
  },
  {
    number: "4",
    title: "External Interface Requirements",
    fields: [
      { key: "s4_1_user_interfaces",           label: "4.1 User Interfaces" },
      { key: "s4_2_hardware_interfaces",       label: "4.2 Hardware Interfaces" },
      { key: "s4_3_software_interfaces",       label: "4.3 Software Interfaces" },
      { key: "s4_4_communications_interfaces", label: "4.4 Communications Interfaces" },
    ],
  },
  {
    number: "5",
    title: "Other Nonfunctional Requirements",
    fields: [
      { key: "s5_1_performance",        label: "5.1 Performance Requirements" },
      { key: "s5_2_safety",             label: "5.2 Safety Requirements" },
      { key: "s5_3_security",           label: "5.3 Security Requirements" },
      { key: "s5_4_quality_attributes", label: "5.4 Software Quality Attributes" },
    ],
  },
  {
    number: "6",
    title: "Other Requirements",
    fields: [
      { key: "s6_other_requirements", label: "6 Other Requirements" },
    ],
  },
  {
    number: "A",
    title: "Appendices",
    fields: [
      { key: "appendix_a_glossary",        label: "Appendix A: Glossary" },
      { key: "appendix_b_analysis_models", label: "Appendix B: Analysis Models" },
      { key: "appendix_c_issues_list",     label: "Appendix C: Issues List" },
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
