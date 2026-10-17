"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { RsState } from "../../lib/api";
import { RS_SECTIONS, type Section } from "../generated/rsSchema";
import { useLocale } from "../i18n/LocaleContext";
import { translateFieldLabel } from "../lib/fieldLabels";
import FieldCard from "./FieldCard";

const SECTION_TITLE_KEYS: Record<string, string> = {
	"Identity & Current State": "rs.section.identity_current_state",
	"Target State": "rs.section.target_state",
	"Value & ROI": "rs.section.value_roi",
	"Priority & Risk": "rs.section.priority_risk",
	"Technical Context": "rs.section.technical_context",
	Additional: "rs.section.additional",
};

function translateSectionTitle(title: string, t: (key: string) => string) {
	const key = SECTION_TITLE_KEYS[title];
	return key ? t(key) : title;
}

// ─── Section group ────────────────────────────────────────────────────────────

function SectionGroup({
	section,
	state,
	isExtracting,
	recentlyChangedKeys,
	onFieldChange,
	onAcceptSuggestion,
	onDismissSuggestion,
	getFieldRef,
	onFieldViewed,
}: {
	section: Section;
	state: RsState;
	isExtracting: boolean;
	recentlyChangedKeys: Set<string>;
	onFieldChange: (key: string, value: string) => void;
	onAcceptSuggestion: (key: string) => void;
	onDismissSuggestion: (key: string) => void;
	getFieldRef: (key: string) => (el: HTMLDivElement | null) => void;
	onFieldViewed: (key: string) => void;
}) {
	const { t } = useLocale();
	const filledCount = section.fields.filter(
		(f) => state.fields[f.key]?.filled,
	).length;
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
				<span className="ml-auto text-[11px] text-gray-400">
					{filledCount}/{total}
				</span>
			</div>

			<div className="space-y-1.5 pl-2">
				{section.fields.map((f) => (
					<FieldCard
						key={f.key}
						ref={getFieldRef(f.key)}
						label={translateFieldLabel(f.label, t)}
						fieldKey={f.key}
						field={state.fields[f.key]}
						multiline={f.multiline}
						isExtracting={isExtracting}
						isRecentlyChanged={recentlyChangedKeys.has(f.key)}
						onViewed={() => onFieldViewed(f.key)}
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
		completeness >= 80
			? "bg-[#4caf50]"
			: completeness >= 50
				? "bg-orange-400"
				: "bg-red-400";

	const textColor =
		completeness >= 80
			? "text-[#2e7d32]"
			: completeness >= 50
				? "text-orange-600"
				: "text-red-500";

	const statusLabel =
		completeness >= 80
			? t("rs.status.ready")
			: completeness >= 50
				? t("rs.status.getting_there")
				: t("rs.status.keep_chatting");

	return (
		<div className="shrink-0 border-b border-gray-200 bg-white px-5 py-4">
			<div className="mb-3">
				<p className="text-sm font-bold text-gray-800">{t("rs.title")}</p>
				<p className="text-xs text-gray-400">{t("rs.subtitle")}</p>
			</div>
			<div>
				<div className="mb-1 flex justify-between gap-2 text-[11px]">
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
	recentlyChangedKeys,
	clearChangedKey,
	clearAllChangedKeys,
}: {
	state: RsState;
	completeness: number;
	onFieldChange: (key: string, value: string) => void;
	onAcceptSuggestion: (key: string) => void;
	onDismissSuggestion: (key: string) => void;
	isExtracting?: boolean;
	recentlyChangedKeys: Set<string>;
	clearChangedKey: (key: string) => void;
	clearAllChangedKeys: () => void;
}) {
	const { t } = useLocale();

	const fieldRefsMap = useRef<Map<string, HTMLDivElement>>(new Map());
	const getFieldRef = useCallback(
		(key: string) => (el: HTMLDivElement | null) => {
			if (el) fieldRefsMap.current.set(key, el);
			else fieldRefsMap.current.delete(key);
		},
		[],
	);

	const scrollContainerRef = useRef<HTMLDivElement>(null);
	const isProgrammaticScrollRef = useRef(false);
	const programmaticScrollTimerRef = useRef<ReturnType<
		typeof setTimeout
	> | null>(null);

	const [stepIndex, setStepIndex] = useState(0);
	const changedKeysArray = useMemo(
		() => [...recentlyChangedKeys],
		[recentlyChangedKeys],
	);
	const toastVisible = changedKeysArray.length > 0;

	// Reset step index when all changes are cleared
	useEffect(() => {
		if (recentlyChangedKeys.size === 0) setStepIndex(0);
	}, [recentlyChangedKeys.size]);

	const handleScroll = useCallback(() => {
		if (isProgrammaticScrollRef.current) return;
		clearAllChangedKeys();
	}, [clearAllChangedKeys]);

	const handleStep = useCallback(() => {
		if (!changedKeysArray.length) return;
		const clampedIndex = stepIndex % changedKeysArray.length;
		const targetKey = changedKeysArray[clampedIndex];
		const el = fieldRefsMap.current.get(targetKey);
		if (el) {
			isProgrammaticScrollRef.current = true;
			el.scrollIntoView({ behavior: "smooth", block: "center" });
			if (programmaticScrollTimerRef.current)
				clearTimeout(programmaticScrollTimerRef.current);
			programmaticScrollTimerRef.current = setTimeout(() => {
				isProgrammaticScrollRef.current = false;
			}, 800);
		}
		setStepIndex((prev) => (prev + 1) % changedKeysArray.length);
	}, [changedKeysArray, stepIndex]);

	return (
		<div className="relative flex h-full flex-col overflow-hidden">
			<CompletenessHeader completeness={completeness} />
			{isExtracting && (
				<div className="shrink-0 bg-amber-50 px-4 py-1.5 text-center text-[11px] text-amber-700 border-b border-amber-100">
					{t("rs.processing")}
				</div>
			)}
			<div
				ref={scrollContainerRef}
				onScroll={handleScroll}
				className={`flex-1 space-y-5 overflow-y-auto p-4 ${toastVisible ? "pb-20" : ""}`}
			>
				{RS_SECTIONS.map((section) => (
					<SectionGroup
						key={section.number}
						section={section}
						state={state}
						isExtracting={isExtracting}
						recentlyChangedKeys={recentlyChangedKeys}
						onFieldChange={onFieldChange}
						onAcceptSuggestion={onAcceptSuggestion}
						onDismissSuggestion={onDismissSuggestion}
						getFieldRef={getFieldRef}
						onFieldViewed={clearChangedKey}
					/>
				))}
			</div>

			{toastVisible && (
				<div className="pointer-events-none absolute bottom-4 left-0 right-0 flex justify-center">
					<div className="pointer-events-auto flex items-center gap-2 rounded-full bg-gray-900 py-1.5 pl-4 pr-1.5 shadow-lg">
						<span className="text-xs font-medium text-white">
							{changedKeysArray.length} {t("rs.toast.updated")} ·{" "}
							{(stepIndex % changedKeysArray.length) + 1}/
							{changedKeysArray.length}
						</span>
						<button
							type="button"
							onClick={handleStep}
							aria-label={t("rs.toast.next")}
							className="flex h-8 w-8 items-center justify-center rounded-full bg-white text-sm font-bold text-gray-900 hover:bg-gray-100"
						>
							↓
						</button>
					</div>
				</div>
			)}
		</div>
	);
}
