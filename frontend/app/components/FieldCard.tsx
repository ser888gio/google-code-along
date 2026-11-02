"use client";

import {
	forwardRef,
	useCallback,
	useEffect,
	useLayoutEffect,
	useRef,
} from "react";
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

const HIGHLIGHT_VISIBLE_MS = 2500;

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
		// Clearing on first sight removed the ring before anyone could notice it on
		// fields already on screen, so it must stay visible for a moment first.
		let timer: ReturnType<typeof setTimeout> | undefined;
		const observer = new IntersectionObserver(
			([entry]) => {
				clearTimeout(timer);
				if (!entry.isIntersecting) return;
				timer = setTimeout(() => {
					onViewed();
					observer.disconnect();
				}, HIGHLIGHT_VISIBLE_MS);
			},
			{ threshold: 0.5 },
		);
		observer.observe(el);
		return () => {
			clearTimeout(timer);
			observer.disconnect();
		};
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
					<span className="ml-auto shrink-0 rounded bg-blue-50 px-1.5 py-0.5 text-[11px] font-bold text-blue-600">
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

/** Grow a textarea to fit its content, re-fitting when its width changes. */
function useAutoGrow(
	ref: React.RefObject<HTMLTextAreaElement | null>,
	value: string,
) {
	// biome-ignore lint/correctness/useExhaustiveDependencies: intentional — `value` re-triggers the fit when the text changes
	useLayoutEffect(() => {
		const el = ref.current;
		if (!el) return;
		const fit = () => {
			el.style.height = "auto";
			el.style.height = `${el.scrollHeight}px`;
		};
		fit();
		if (typeof ResizeObserver === "undefined") return;
		// Width changes (panel switch, rotation, hidden → shown) re-wrap the text.
		let lastWidth = el.clientWidth;
		const observer = new ResizeObserver(() => {
			if (el.clientWidth === lastWidth) return;
			lastWidth = el.clientWidth;
			fit();
		});
		observer.observe(el);
		return () => observer.disconnect();
	}, [ref, value]);
}

// Every field is an auto-growing textarea so long values are never clipped;
// single-line fields just start at one row and reject line breaks.
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
	const ref = useRef<HTMLTextAreaElement>(null);
	useAutoGrow(ref, value);
	return (
		<textarea
			ref={ref}
			value={value}
			onChange={(e) =>
				onChange(
					multiline ? e.target.value : e.target.value.replace(/\r?\n/g, " "),
				)
			}
			onKeyDown={(e) => {
				if (!multiline && e.key === "Enter") e.preventDefault();
			}}
			placeholder={placeholder}
			rows={multiline ? 3 : 1}
			className="block min-h-6 w-full resize-none overflow-hidden text-base leading-relaxed text-gray-700 outline-none placeholder-gray-300 lg:text-sm"
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
		<div className="mt-2 flex flex-wrap items-start gap-2 rounded bg-yellow-50 px-2 py-1.5">
			<span className="min-w-0 flex-1 basis-48 text-xs text-yellow-800 [overflow-wrap:anywhere]">
				{t("rs.suggestion.label")} {value}
			</span>
			<button
				type="button"
				onClick={onAccept}
				className="min-h-8 shrink-0 rounded bg-yellow-200 px-2.5 text-xs font-bold text-yellow-900 hover:bg-yellow-300 lg:min-h-6 lg:px-2"
			>
				{t("rs.suggestion.accept")}
			</button>
			<button
				type="button"
				onClick={onDismiss}
				className="min-h-8 shrink-0 rounded bg-gray-100 px-2.5 text-xs font-bold text-gray-600 hover:bg-gray-200 lg:min-h-6 lg:px-2"
			>
				{t("rs.suggestion.dismiss")}
			</button>
		</div>
	);
}

export default FieldCard;
