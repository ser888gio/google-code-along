"use client";

import { RsState } from "../../lib/api";
import { RS_SECTIONS, Section } from "../generated/rsSchema";
import { useLocale } from "../i18n/LocaleContext";
import FieldCard from "./FieldCard";

const SECTION_TITLE_KEYS: Record<string, string> = {
  "Identity & Current State": "rs.section.identity_current_state",
  "Target State": "rs.section.target_state",
  "Value & ROI": "rs.section.value_roi",
  "Priority & Risk": "rs.section.priority_risk",
  "Technical Context": "rs.section.technical_context",
  "Additional": "rs.section.additional",
};

const FIELD_LABEL_KEYS: Record<string, string> = {
  "Use Case Title (EN)": "rs.field.use_case_title",
  "Customer Department": "rs.field.customer_department",
  "Requestor": "rs.field.requestor",
  "Product Owner": "rs.field.product_owner",
  "Process Description / As-Is": "rs.field.process_description_as_is",
  "Process Context": "rs.field.process_context",
  "Trigger": "rs.field.trigger",
  "Purpose / To-Be": "rs.field.purpose_to_be",
  "Saved Time (hours/year)": "rs.field.saved_time_hours_per_year",
  "Cost Saving": "rs.field.cost_saving",
  "Revenue Increase": "rs.field.revenue_increase",
  "Impacted Users": "rs.field.impacted_users",
  "Added Value": "rs.field.added_value",
  "Time Criticality": "rs.field.time_criticality",
  "Strategic Impact": "rs.field.strategic_impact",
  "Risk Avoidance": "rs.field.risk_avoidance",
  "Systems & Tools Involved": "rs.field.systems_and_tools",
  "Types of Documents Involved": "rs.field.document_types",
  "Data Security Classification": "rs.field.data_security_classification",
  "Solution Type": "rs.field.solution_type",
  "Comments": "rs.field.comments",
  "Attachments (GCS paths)": "rs.field.attachments",
};

function translateSectionTitle(title: string, t: (key: string) => string) {
  const key = SECTION_TITLE_KEYS[title];
  return key ? t(key) : title;
}

function translateFieldLabel(label: string, t: (key: string) => string) {
  const key = FIELD_LABEL_KEYS[label];
  return key ? t(key) : label;
}

// ─── Section group ────────────────────────────────────────────────────────────

function SectionGroup({
  section,
  state,
  isExtracting,
  onFieldChange,
  onAcceptSuggestion,
  onDismissSuggestion,
}: {
  section: Section;
  state: RsState;
  isExtracting: boolean;
  onFieldChange: (key: string, value: string) => void;
  onAcceptSuggestion: (key: string) => void;
  onDismissSuggestion: (key: string) => void;
}) {
  const { t } = useLocale();
  const filledCount = section.fields.filter((f) => state.fields[f.key]?.filled).length;
  const total = section.fields.length;

  return (
    <div>
      <div className="mb-2 flex items-center gap-2">
        <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded bg-[#1a3a2a] text-[11px] font-bold text-white">
          {section.number}
        </span>
        <span className="text-xs font-bold uppercase tracking-wide text-[#1a3a2a]">
          {translateSectionTitle(section.title, t)}
        </span>
        <span className="ml-auto text-[10px] text-gray-400">
          {filledCount}/{total}
        </span>
      </div>

      <div className="space-y-1.5 pl-2">
        {section.fields.map((f) => (
          <FieldCard
            key={f.key}
            label={translateFieldLabel(f.label, t)}
            fieldKey={f.key}
            field={state.fields[f.key]}
            multiline={f.multiline}
            isExtracting={isExtracting}
            onChange={onFieldChange}
            onAcceptSuggestion={onAcceptSuggestion}
            onDismissSuggestion={onDismissSuggestion}
          />
        ))}
      </div>
    </div>
  );
}

// ─── Completeness header ──────────────────────────────────────────────────────

function CompletenessHeader({ completeness }: { completeness: number }) {
  const { t } = useLocale();

  const barColor =
    completeness >= 80 ? "bg-[#4caf50]" :
    completeness >= 50 ? "bg-orange-400" :
    "bg-red-400";

  const textColor =
    completeness >= 80 ? "text-[#2e7d32]" :
    completeness >= 50 ? "text-orange-600" :
    "text-red-500";

  const statusLabel =
    completeness >= 80 ? t("rs.status.ready") :
    completeness >= 50 ? t("rs.status.getting_there") :
    t("rs.status.keep_chatting");

  return (
    <div className="shrink-0 border-b border-gray-200 bg-white px-5 py-4">
      <div className="mb-3">
        <p className="text-sm font-bold text-gray-800">{t("rs.title")}</p>
        <p className="text-xs text-gray-400">{t("rs.subtitle")}</p>
      </div>
      <div>
        <div className="mb-1 flex justify-between text-[10px]">
          <span className={`font-semibold ${textColor}`}>
            {completeness}% — {statusLabel}
          </span>
          <span className="text-gray-400">{t("rs.to_generate")}</span>
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
  state,
  completeness,
  onFieldChange,
  onAcceptSuggestion,
  onDismissSuggestion,
  isExtracting = false,
}: {
  state: RsState;
  completeness: number;
  onFieldChange: (key: string, value: string) => void;
  onAcceptSuggestion: (key: string) => void;
  onDismissSuggestion: (key: string) => void;
  isExtracting?: boolean;
}) {
  const { t } = useLocale();

  return (
    <div className="flex h-full flex-col overflow-hidden">
      <CompletenessHeader completeness={completeness} />
      {isExtracting && (
        <div className="shrink-0 bg-amber-50 px-4 py-1.5 text-center text-[11px] text-amber-700 border-b border-amber-100">
          {t("rs.processing")}
        </div>
      )}
      <div className="flex-1 space-y-5 overflow-y-auto p-4">
        {RS_SECTIONS.map((section) => (
          <SectionGroup
            key={section.number}
            section={section}
            state={state}
            isExtracting={isExtracting}
            onFieldChange={onFieldChange}
            onAcceptSuggestion={onAcceptSuggestion}
            onDismissSuggestion={onDismissSuggestion}
          />
        ))}
      </div>
    </div>
  );
}
