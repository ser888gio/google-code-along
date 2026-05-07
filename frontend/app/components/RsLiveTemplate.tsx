"use client";

import { RsPartialData } from "../../lib/api";
import { RS_SECTIONS, Section } from "../generated/rsSchema";
import { useLocale } from "../i18n/LocaleContext";

// ─── Cards ────────────────────────────────────────────────────────────────────

function PlaceholderCard({ label, pulsing = false }: { label: string; pulsing?: boolean }) {
  const { t } = useLocale();
  return (
    <div
      className={`rounded border-2 border-dashed border-gray-200 px-3 py-2.5 ${
        pulsing ? "animate-shimmer" : "bg-gray-50"
      }`}
    >
      <div className="flex items-center gap-2">
        <span className="text-[11px] font-semibold uppercase tracking-wide text-gray-400">
          {label}
        </span>
        <span className="ml-auto text-[10px] italic text-gray-300">{t("rs.gathering")}</span>
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

function EditableCard({
  label,
  fieldKey,
  value,
  onChange,
  multiline = false,
}: {
  label: string;
  fieldKey: string;
  value: string;
  onChange: (key: string, value: string) => void;
  multiline?: boolean;
}) {
  const { t } = useLocale();
  return (
    <div className="rounded border border-blue-200 bg-white px-3 py-2.5 shadow-sm">
      <div className="mb-1.5 flex items-center gap-2">
        <span className="text-[11px] font-semibold uppercase tracking-wide text-[#1a3a2a]">
          {label}
        </span>
        <span className="ml-auto shrink-0 rounded bg-blue-50 px-1.5 py-0.5 text-[10px] font-bold text-blue-600">
          Direct
        </span>
      </div>
      {multiline ? (
        <textarea
          value={value}
          onChange={(e) => onChange(fieldKey, e.target.value)}
          placeholder={`${t("rs.badge.direct")} ${label.toLowerCase()}…`}
          rows={2}
          className="w-full resize-none text-sm leading-relaxed text-gray-700 outline-none placeholder-gray-300"
        />
      ) : (
        <input
          type="text"
          value={value}
          onChange={(e) => onChange(fieldKey, e.target.value)}
          placeholder={`${t("rs.badge.direct")} ${label.toLowerCase()}…`}
          className="w-full text-sm text-gray-700 outline-none placeholder-gray-300"
        />
      )}
    </div>
  );
}

// ─── Section group ────────────────────────────────────────────────────────────

function SectionGroup({
  section,
  fields,
  directFields,
  onDirectFieldChange,
  isExtracting = false,
}: {
  section: Section;
  fields: RsPartialData["fields"] | undefined;
  directFields: Record<string, string>;
  onDirectFieldChange: (key: string, value: string) => void;
  isExtracting?: boolean;
}) {
  const filledCount = section.fields.filter((f) => {
    if (f.directInput) {
      return (directFields[f.key] ?? "").trim() !== "";
    }
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
          if (f.directInput) {
            return (
              <EditableCard
                key={f.key}
                label={f.label}
                fieldKey={f.key}
                value={directFields[f.key] ?? ""}
                onChange={onDirectFieldChange}
                multiline={f.multiline}
              />
            );
          }

          const entry = fields?.[f.key];
          const isFilled =
            entry?.filled === true &&
            entry.value != null &&
            entry.value.trim() !== "";

          return isFilled ? (
            <FilledCard key={f.key} label={f.label} value={entry!.value!} />
          ) : (
            <PlaceholderCard key={f.key} label={f.label} pulsing={isExtracting} />
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
  const { t } = useLocale();
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
    completeness >= 80 ? t("rs.status.ready") :
    completeness >= 50 ? t("rs.status.getting_there") :
    t("rs.status.keep_chatting");

  return (
    <div className="shrink-0 border-b border-gray-200 bg-white px-5 py-4">
      <div className="mb-3 flex items-center justify-between">
        <div>
          <p className="text-sm font-bold text-gray-800">{t("rs.title")}</p>
          <p className="text-xs text-gray-400">{t("rs.subtitle")}</p>
        </div>
        <button
          onClick={onGenerateFull}
          disabled={!canGenerate}
          title={
            canGenerate
              ? t("rs.generate")
              : `${t("rs.reach_80")} ${completeness}%)`
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
          {canGenerate ? t("rs.generate") : `${completeness}% ${t("rs.keep_chatting_suffix")}`}
        </button>
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
  rsPartial,
  directFields,
  onGenerateFull,
  onDirectFieldChange,
  isExtracting = false,
}: {
  rsPartial: RsPartialData | null;
  directFields: Record<string, string>;
  onGenerateFull: () => void;
  onDirectFieldChange: (key: string, value: string) => void;
  isExtracting?: boolean;
}) {
  const { t } = useLocale();
  const completeness = rsPartial?.completeness ?? 0;

  return (
    <div className="flex h-full flex-col overflow-hidden">
      <CompletenessHeader completeness={completeness} onGenerateFull={onGenerateFull} />
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
            fields={rsPartial?.fields}
            directFields={directFields}
            onDirectFieldChange={onDirectFieldChange}
            isExtracting={isExtracting}
          />
        ))}
      </div>
    </div>
  );
}
