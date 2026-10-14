"use client";

import type { ReactNode } from "react";
import type { FinalAnalysis, RsState, SrsData } from "../../lib/api";
import type { FinalizingStatus } from "../hooks/useChatSession";
import LanguageSwitcher from "../i18n/LanguageSwitcher";
import { useLocale } from "../i18n/LocaleContext";
import AnalysisPanel, { FinalizingOverlay } from "./AnalysisPanel";
import BpmnPanel from "./BpmnPanel";
import DataflowPanel from "./DataflowPanel";
import FirestoreSrsPanel from "./FirestoreSrsPanel";
import RsLiveTemplate from "./RsLiveTemplate";

const RS_TABS = [
	"Preview",
	"BPMN",
	"Data",
	"Database",
	"Analysis",
	"Summary",
] as const;
export type RsTab = (typeof RS_TABS)[number];
// Analysis is hidden from the tab bar but still opened programmatically on finalization.
const HIDDEN_TABS = new Set<RsTab>(["Database", "Analysis"]);

export default function RsDocumentPanel({
	activeTab,
	onTabChange,
	rsState,
	rsCompleteness,
	onFieldChange,
	onAcceptSuggestion,
	onDismissSuggestion,
	sessionId,
	onGenerateFull,
	isDownloadingRs,
	srsData,
	finalizingStatus,
	finalAnalysis,
	isExtracting,
	recentlyChangedKeys,
	clearChangedKey,
	clearAllChangedKeys,
	onNewConversation,
}: {
	activeTab: RsTab;
	onTabChange: (t: RsTab) => void;
	rsState: RsState;
	rsCompleteness: number;
	onFieldChange: (key: string, value: string) => void;
	onAcceptSuggestion: (key: string) => void;
	onDismissSuggestion: (key: string) => void;
	sessionId: string | null;
	onGenerateFull: () => void;
	isDownloadingRs: boolean;
	srsData: SrsData | null;
	finalizingStatus: FinalizingStatus;
	finalAnalysis: FinalAnalysis | null;
	isExtracting: boolean;
	recentlyChangedKeys: Set<string>;
	clearChangedKey: (key: string) => void;
	clearAllChangedKeys: () => void;
	onNewConversation: () => void;
}) {
	const { t } = useLocale();
	const TAB_LABELS: Record<string, string> = {
		Preview: t("tab.preview"),
		BPMN: t("tab.bpmn"),
		Data: t("tab.data"),
		Database: t("tab.database"),
		Analysis: t("tab.analysis"),
		Summary: t("tab.summary"),
	};

	const panels: Partial<Record<RsTab, ReactNode>> = {
		Preview: (
			<RsLiveTemplate
				state={rsState}
				completeness={rsCompleteness}
				onFieldChange={onFieldChange}
				onAcceptSuggestion={onAcceptSuggestion}
				onDismissSuggestion={onDismissSuggestion}
				isExtracting={isExtracting}
				recentlyChangedKeys={recentlyChangedKeys}
				clearChangedKey={clearChangedKey}
				clearAllChangedKeys={clearAllChangedKeys}
			/>
		),
		BPMN: <BpmnPanel sessionId={sessionId} />,
		Data: <DataflowPanel sessionId={sessionId} />,
		Database: <FirestoreSrsPanel data={srsData} />,
		Analysis: (
			<AnalysisTabContent
				finalizingStatus={finalizingStatus}
				finalAnalysis={finalAnalysis}
			/>
		),
		Summary: (
			<SummaryTabContent
				rsCompleteness={rsCompleteness}
				isDownloadingRs={isDownloadingRs}
				onGenerateFull={onGenerateFull}
			/>
		),
	};

	return (
		<div className="flex h-full flex-col">
			<div className="flex shrink-0 items-center gap-3 border-b border-gray-200 bg-white px-4">
				<span className="mr-4 hidden whitespace-nowrap border-r border-gray-200 py-3 pr-4 text-sm font-semibold text-gray-800 2xl:inline">
					{t("header.rs")}
				</span>
				<div className="flex min-w-0 flex-1 overflow-x-auto">
					{RS_TABS.filter((tab) => !HIDDEN_TABS.has(tab)).map((tab) => (
						<button
							type="button"
							key={tab}
							onClick={() => onTabChange(tab)}
							className={`relative whitespace-nowrap px-3 py-3 text-sm transition-colors ${
								activeTab === tab
									? "border-b-2 border-[#1a3a2a] bg-[#1a3a2a] text-white"
									: "text-gray-500 hover:text-gray-800"
							}`}
						>
							{TAB_LABELS[tab] ?? tab}
						</button>
					))}
				</div>
				<div className="hidden shrink-0 items-center gap-3 lg:flex">
					<button
						type="button"
						onClick={onNewConversation}
						aria-label={t("btn.new_conversation")}
						title={t("btn.new_conversation")}
						className="flex items-center gap-1.5 whitespace-nowrap rounded border border-[#4caf50] bg-[#4caf50] px-3 py-1.5 text-xs font-semibold text-white shadow-sm transition-opacity hover:opacity-90"
					>
						<span className="xl:hidden">+</span>
						<span className="hidden xl:inline">{t("btn.new_conversation")}</span>
					</button>
					<LanguageSwitcher />
				</div>
			</div>

			<div className="flex-1 overflow-hidden bg-gray-50">
				{panels[activeTab] ?? (
					<div className="flex h-full items-center justify-center text-sm text-gray-400">
						{TAB_LABELS[activeTab] ?? activeTab}
					</div>
				)}
			</div>
		</div>
	);
}

function AnalysisTabContent({
	finalizingStatus,
	finalAnalysis,
}: {
	finalizingStatus: FinalizingStatus;
	finalAnalysis: FinalAnalysis | null;
}) {
	const { t } = useLocale();
	if (finalizingStatus === "complete" && finalAnalysis)
		return <AnalysisPanel analysis={finalAnalysis} />;
	if (finalizingStatus === "finalizing") return <FinalizingOverlay />;
	return (
		<div className="flex h-full items-center justify-center text-sm text-gray-400">
			{t("analysis.pending")}
		</div>
	);
}

function SummaryTabContent({
	rsCompleteness,
	isDownloadingRs,
	onGenerateFull,
}: {
	rsCompleteness: number;
	isDownloadingRs: boolean;
	onGenerateFull: () => void;
}) {
	const { t } = useLocale();
	return (
		<div className="flex h-full flex-col items-center justify-center gap-3">
			{rsCompleteness < 80 && (
				<p className="text-xs text-gray-400">
					{rsCompleteness}% — {t("rs.reach_80")} 80%)
				</p>
			)}
			<button
				type="button"
				onClick={onGenerateFull}
				disabled={rsCompleteness < 80 || isDownloadingRs}
				className={`flex items-center gap-2 rounded px-5 py-2.5 text-sm font-semibold transition-opacity ${
					rsCompleteness >= 80 && !isDownloadingRs
						? "bg-[#4a6659] text-white hover:opacity-90"
						: "cursor-not-allowed bg-gray-200 text-gray-400"
				}`}
			>
				{isDownloadingRs ? (
					<svg
						aria-hidden="true"
						width="14"
						height="14"
						viewBox="0 0 14 14"
						fill="none"
						className="animate-spin"
					>
						<circle
							cx="7"
							cy="7"
							r="6"
							stroke="currentColor"
							strokeWidth="1.8"
							strokeDasharray="28"
							strokeDashoffset="10"
							strokeLinecap="round"
						/>
					</svg>
				) : (
					<svg
						aria-hidden="true"
						width="14"
						height="14"
						viewBox="0 0 14 14"
						fill="none"
					>
						<path
							d="M7 1v8M4 6l3 3 3-3"
							stroke="currentColor"
							strokeWidth="1.8"
							strokeLinecap="round"
							strokeLinejoin="round"
						/>
						<path
							d="M1 10v1a2 2 0 002 2h8a2 2 0 002-2v-1"
							stroke="currentColor"
							strokeWidth="1.8"
							strokeLinecap="round"
						/>
					</svg>
				)}
				{isDownloadingRs ? t("download.generating") : t("download.rs")}
			</button>
		</div>
	);
}
