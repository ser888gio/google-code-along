"use client";

import { forwardRef, useCallback, useEffect, useRef } from "react";
import type { FieldSource, RsField } from "../../lib/api";
import { useLocale } from "../i18n/LocaleContext";

// Only the upload badge has an i18n key; these labels are not yet translated.
const SOURCE_LABELS: Partial<Record<FieldSource, string>> = {
	user_manual: "User",
	user_direct_chat: "Chat",
	user_accept_suggestion: "Accepted AI",
};

function sourceLabel(
	source: FieldSource | null,
	t: (key: string) => string,
): string | null {
	if (!source) return null;
	if (source === "user_upload") return t("rs.badge.upload");
	return SOURCE_LABELS[source] ?? null;
}

function readField(field: RsField | undefined) {
	return {
		value: field?.value ?? "",
		filled: field?.filled ?? false,
		source: field?.source ?? null,
		suggestion: field?.pendingSuggestion,
	};
}

function fieldBorderClass(
	hasSuggestion: boolean,
	filled: boolean,
	isExtracting: boolean,
): string {
	if (hasSuggestion) return "border-yellow-300";
	if (filled) return "border-gray-200";
	if (isExtracting) return "animate-shimmer border-dashed border-gray-200";
	return "border-dashed border-gray-200";
}

interface FieldCardProps {
	label: string;
	fieldKey: string;
	field: RsField | undefined;
	multiline?: boolean;
	isExtracting?: boolean;
	isRecentlyChanged?: boolean;
	onViewed?: () => void;
	onChange: (key: string, value: string) => void;
	onAcceptSuggestion: (key: string) => void;
	onDismissSuggestion: (key: string) => void;
}

const FieldCard = forwardRef<HTMLDivElement, FieldCardProps>(function FieldCard(
	{
		label,
		fieldKey,
		field,
		multiline = false,
		isExtracting = false,
		isRecentlyChanged = false,
		onViewed,
		onChange,
		onAcceptSuggestion,
		onDismissSuggestion,
	},
	ref,
) {
	const { t } = useLocale();
	const internalRef = useRef<HTMLDivElement>(null);

	const mergedRef = useCallback(
		(node: HTMLDivElement | null) => {
			(internalRef as React.MutableRefObject<HTMLDivElement | null>).current =
				node;
			if (typeof ref === "function") ref(node);
			else if (ref)
				(ref as React.MutableRefObject<HTMLDivElement | null>).current = node;
		},
		[ref],
	);

	useEffect(() => {
		if (!isRecentlyChanged || !onViewed) return;
		const el = internalRef.current;
		if (!el) return;
		const observer = new IntersectionObserver(
			([entry]) => {
				if (entry.isIntersecting) {
					onViewed();
					observer.disconnect();
				}
			},
			{ threshold: 0.5 },
		);
		observer.observe(el);
		return () => observer.disconnect();
	}, [isRecentlyChanged, onViewed]);
	const { value, filled, source, suggestion } = readField(field);

	const badgeLabel = filled ? sourceLabel(source, t) : null;
	const borderClass = fieldBorderClass(
		Boolean(suggestion),
		filled,
		isExtracting,
	);

	const recentClass = isRecentlyChanged
		? "ring-2 ring-green-400 ring-offset-1"
		: "";

	return (
		<div
			ref={mergedRef}
			className={`rounded border-2 bg-white px-3 py-2.5 shadow-sm ${borderClass} ${recentClass}`}
		>
			<div className="mb-1.5 flex items-center gap-2">
				<span className="text-[11px] font-semibold uppercase tracking-wide text-[#1a3a2a]">
					{label}
				</span>
				{badgeLabel && (
					<span className="ml-auto shrink-0 rounded bg-blue-50 px-1.5 py-0.5 text-[10px] font-bold text-blue-600">
						{badgeLabel}
					</span>
				)}
			</div>

			<FieldInput
				multiline={multiline}
				value={value}
				placeholder={filled ? undefined : t("rs.gathering")}
				onChange={(next) => onChange(fieldKey, next)}
			/>

			{suggestion && (
				<SuggestionBar
					value={suggestion.value}
					onAccept={() => onAcceptSuggestion(fieldKey)}
					onDismiss={() => onDismissSuggestion(fieldKey)}
				/>
			)}
		</div>
	);
});

function FieldInput({
	multiline,
	value,
	placeholder,
	onChange,
}: {
	multiline: boolean;
	value: string;
	placeholder: string | undefined;
	onChange: (value: string) => void;
}) {
	if (multiline)
		return (
			<textarea
				value={value}
				onChange={(e) => onChange(e.target.value)}
				placeholder={placeholder}
				rows={3}
				className="w-full resize-none text-sm leading-relaxed text-gray-700 outline-none placeholder-gray-300"
			/>
		);
	return (
		<input
			type="text"
			value={value}
			onChange={(e) => onChange(e.target.value)}
			placeholder={placeholder}
			className="w-full text-sm text-gray-700 outline-none placeholder-gray-300"
		/>
	);
}

function SuggestionBar({
	value,
	onAccept,
	onDismiss,
}: {
	value: string;
	onAccept: () => void;
	onDismiss: () => void;
}) {
	const { t } = useLocale();
	return (
		<div className="mt-2 flex items-start gap-2 rounded bg-yellow-50 px-2 py-1.5">
			<span className="min-w-0 flex-1 truncate text-[11px] text-yellow-800">
				{t("rs.suggestion.label")} {value}
			</span>
			<button
				type="button"
				onClick={onAccept}
				className="shrink-0 rounded bg-yellow-200 px-1.5 py-0.5 text-[10px] font-bold text-yellow-900 hover:bg-yellow-300"
			>
				{t("rs.suggestion.accept")}
			</button>
			<button
				type="button"
				onClick={onDismiss}
				className="shrink-0 rounded bg-gray-100 px-1.5 py-0.5 text-[10px] font-bold text-gray-600 hover:bg-gray-200"
			>
				{t("rs.suggestion.dismiss")}
			</button>
		</div>
	);
}

export default FieldCard;
