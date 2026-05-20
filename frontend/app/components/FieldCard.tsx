"use client";

import { useLocale } from "../i18n/LocaleContext";
import { RsField } from "../../lib/api";

interface FieldCardProps {
  label: string;
  fieldKey: string;
  field: RsField | undefined;
  multiline?: boolean;
  isExtracting?: boolean;
  onChange: (key: string, value: string) => void;
  onAcceptSuggestion: (key: string) => void;
  onDismissSuggestion: (key: string) => void;
}

export default function FieldCard({
  label,
  fieldKey,
  field,
  multiline = false,
  isExtracting = false,
  onChange,
  onAcceptSuggestion,
  onDismissSuggestion,
}: FieldCardProps) {
  const { t } = useLocale();
  const value = field?.value ?? "";
  const filled = field?.filled ?? false;
  const source = field?.source ?? null;
  const suggestion = field?.pendingSuggestion;

  const badge =
    filled && source === "ai" ? (
      <span className="ml-auto shrink-0 rounded bg-[#e8f5e9] px-1.5 py-0.5 text-[10px] font-bold text-[#2e7d32]">
        AI
      </span>
    ) : filled && source === "user" ? (
      <span className="ml-auto shrink-0 rounded bg-blue-50 px-1.5 py-0.5 text-[10px] font-bold text-blue-600">
        {t("rs.badge.direct")}
      </span>
    ) : filled && source === "upload" ? (
      <span className="ml-auto shrink-0 rounded bg-purple-50 px-1.5 py-0.5 text-[10px] font-bold text-purple-600">
        {t("rs.badge.upload") ?? "↑"}
      </span>
    ) : null;

  const borderClass = suggestion
    ? "border-yellow-300"
    : filled
    ? "border-gray-200"
    : isExtracting
    ? "animate-shimmer border-dashed border-gray-200"
    : "border-dashed border-gray-200";

  return (
    <div className={`rounded border-2 bg-white px-3 py-2.5 shadow-sm ${borderClass}`}>
      <div className="mb-1.5 flex items-center gap-2">
        <span className="text-[11px] font-semibold uppercase tracking-wide text-[#1a3a2a]">
          {label}
        </span>
        {badge}
      </div>

      {multiline ? (
        <textarea
          value={value}
          onChange={(e) => onChange(fieldKey, e.target.value)}
          placeholder={filled ? undefined : t("rs.gathering")}
          rows={3}
          className="w-full resize-none text-sm leading-relaxed text-gray-700 outline-none placeholder-gray-300"
        />
      ) : (
        <input
          type="text"
          value={value}
          onChange={(e) => onChange(fieldKey, e.target.value)}
          placeholder={filled ? undefined : t("rs.gathering")}
          className="w-full text-sm text-gray-700 outline-none placeholder-gray-300"
        />
      )}

      {suggestion && (
        <div className="mt-2 flex items-start gap-2 rounded bg-yellow-50 px-2 py-1.5">
          <span className="min-w-0 flex-1 truncate text-[11px] text-yellow-800">
            {t("rs.suggestion.label") ?? "AI suggests:"} {suggestion.value}
          </span>
          <button
            onClick={() => onAcceptSuggestion(fieldKey)}
            className="shrink-0 rounded bg-yellow-200 px-1.5 py-0.5 text-[10px] font-bold text-yellow-900 hover:bg-yellow-300"
          >
            {t("rs.suggestion.accept") ?? "Accept"}
          </button>
          <button
            onClick={() => onDismissSuggestion(fieldKey)}
            className="shrink-0 rounded bg-gray-100 px-1.5 py-0.5 text-[10px] font-bold text-gray-600 hover:bg-gray-200"
          >
            {t("rs.suggestion.dismiss") ?? "Dismiss"}
          </button>
        </div>
      )}
    </div>
  );
}
