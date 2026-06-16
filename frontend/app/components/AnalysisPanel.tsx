"use client";

import type { FinalAnalysis } from "../../lib/api";
import { useLocale } from "../i18n/LocaleContext";

// ─── Finalizing spinner ───────────────────────────────────────────────────────

export function FinalizingOverlay() {
	const { t } = useLocale();
	return (
		<div className="flex h-full flex-col items-center justify-center gap-4 p-8">
			<svg
				aria-hidden="true"
				className="animate-spin text-[#4a6659]"
				width="36"
				height="36"
				viewBox="0 0 24 24"
				fill="none"
			>
				<circle
					cx="12"
					cy="12"
					r="10"
					stroke="currentColor"
					strokeWidth="2.5"
					strokeDasharray="31.4"
					strokeDashoffset="10"
				/>
			</svg>
			<p className="text-sm font-semibold text-[#1a3a2a]">
				{t("analysis.finalizing")}
			</p>
			<p className="max-w-xs text-center text-xs text-gray-400">
				{t("analysis.finalizing_desc")}
			</p>
		</div>
	);
}

// ─── Section card ─────────────────────────────────────────────────────────────

function SectionCard({
	title,
	accent,
	children,
}: {
	title: string;
	accent?: string; // optional top-border color class e.g. "border-t-[#4a6659]"
	children: React.ReactNode;
}) {
	return (
		<div
			className={`rounded border border-gray-200 bg-white shadow-sm ${accent ?? ""}`}
		>
			<div className="border-b border-gray-100 px-4 py-2.5">
				<span className="text-xs font-bold uppercase tracking-wider text-[#1a3a2a]">
					{title}
				</span>
			</div>
			<div className="px-4 py-3">{children}</div>
		</div>
	);
}

function Row({
	label,
	value,
}: { label: string; value: string | null | undefined }) {
	return (
		<div className="flex gap-2 py-1 text-sm">
			<span className="w-40 shrink-0 text-[11px] font-semibold uppercase tracking-wide text-gray-400">
				{label}
			</span>
			<span className="text-gray-700">{value ?? "—"}</span>
		</div>
	);
}

function Tag({
	label,
	variant = "neutral",
}: { label: string; variant?: "green" | "amber" | "blue" | "neutral" }) {
	const cls = {
		green: "bg-[#e8f5e9] text-[#2e7d32] border-[#c8e6c9]",
		amber: "bg-amber-50 text-amber-700 border-amber-200",
		blue: "bg-blue-50 text-blue-700 border-blue-200",
		neutral: "bg-gray-100 text-gray-600 border-gray-200",
	}[variant];
	return (
		<span
			className={`inline-block rounded border px-2 py-0.5 text-[11px] font-semibold ${cls}`}
		>
			{label}
		</span>
	);
}

function BulletList({ items }: { items: string[] }) {
	if (!items.length) return <span className="text-xs text-gray-400">—</span>;
	return (
		<ul className="space-y-1">
			{items.map((item) => (
				<li key={item} className="flex gap-2 text-sm text-gray-700">
					<span className="mt-1 h-1.5 w-1.5 shrink-0 rounded-full bg-[#4a6659]" />
					{item}
				</li>
			))}
		</ul>
	);
}

// ─── Priority tier badge ──────────────────────────────────────────────────────

function TierBadge({ tier, score }: { tier: string; score: number }) {
	const variant =
		tier === "strategic" ? "green" : tier === "tactical" ? "amber" : "neutral";

	return (
		<div className="flex items-center gap-3">
			<Tag label={tier.toUpperCase()} variant={variant} />
			<div className="flex flex-1 items-center gap-2">
				<div className="h-2 flex-1 overflow-hidden rounded-full bg-gray-100">
					<div
						className={`h-2 rounded-full transition-all ${
							tier === "strategic"
								? "bg-[#4caf50]"
								: tier === "tactical"
									? "bg-amber-400"
									: "bg-gray-400"
						}`}
						style={{ width: `${score}%` }}
					/>
				</div>
				<span className="w-8 text-right text-xs font-bold text-gray-600">
					{score}
				</span>
			</div>
		</div>
	);
}

// ─── Main component ───────────────────────────────────────────────────────────

export default function AnalysisPanel({
	analysis,
}: {
	analysis: FinalAnalysis;
}) {
	const { t } = useLocale();
	const {
		technology_recommendation,
		team_profile,
		priority_tier,
		risk_and_dependencies,
		use_case_form,
		_meta,
	} = analysis;

	return (
		<div className="flex h-full flex-col overflow-hidden">
			{/* Header strip */}
			<div className="shrink-0 border-b border-gray-200 bg-white px-5 py-3">
				<div className="flex items-center justify-between">
					<div>
						<p className="text-sm font-bold text-gray-800">
							{/* TODO: show use_case_title from use_case_form once field names are confirmed */}
							{use_case_form?.use_case_title ?? t("analysis.use_case")}
						</p>
						<p className="text-[11px] text-gray-400">
							{t("analysis.finalized")}{" "}
							{_meta?.finalized_at
								? new Date(_meta.finalized_at).toLocaleString()
								: "—"}
							{" · "}
							{t("analysis.completeness")}{" "}
							{_meta?.discovery_completeness ?? "—"}%
						</p>
					</div>
					{/* TODO: add download button for final_analysis.docx once backend generates it */}
					<button
						type="button"
						disabled
						title="Download coming soon"
						className="flex items-center gap-1.5 rounded bg-gray-100 px-3 py-1.5 text-xs font-semibold text-gray-400"
					>
						<svg
							aria-hidden="true"
							width="12"
							height="12"
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
						{t("analysis.download")}
					</button>
				</div>
			</div>

			<div className="flex-1 space-y-4 overflow-y-auto p-4">
				{/* 1 — Technology Recommendation */}
				<SectionCard
					title={t("analysis.tech_rec")}
					accent="border-t-2 border-t-[#4a6659]"
				>
					<div className="mb-2 flex flex-wrap gap-2">
						<Tag label={technology_recommendation.primary} variant="green" />
						{technology_recommendation.alternatives.map((a) => (
							<Tag key={a} label={a} variant="neutral" />
						))}
					</div>
					<p className="mb-3 text-sm leading-relaxed text-gray-700">
						{technology_recommendation.rationale}
					</p>
					{technology_recommendation.constraints.length > 0 && (
						<div>
							<p className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-gray-400">
								{t("analysis.constraints")}
							</p>
							<BulletList items={technology_recommendation.constraints} />
						</div>
					)}
				</SectionCard>

				{/* 2 — Team Profile */}
				<SectionCard title={t("analysis.team")}>
					<div className="mb-2">
						<Tag
							label={team_profile.recommended_team_type.toUpperCase()}
							variant={
								team_profile.recommended_team_type === "internal"
									? "green"
									: "blue"
							}
						/>
					</div>
					<p className="mb-3 text-sm leading-relaxed text-gray-700">
						{team_profile.rationale}
					</p>
					<div>
						<p className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-gray-400">
							{t("analysis.skills")}
						</p>
						<div className="flex flex-wrap gap-1.5">
							{team_profile.skills_required.map((s) => (
								<Tag key={s} label={s} variant="neutral" />
							))}
						</div>
					</div>
				</SectionCard>

				{/* 3 — Priority Tier */}
				<SectionCard title={t("analysis.priority")}>
					<div className="mb-3">
						<TierBadge tier={priority_tier.tier} score={priority_tier.score} />
					</div>
					<p className="mb-3 text-sm leading-relaxed text-gray-700">
						{priority_tier.scoring_rationale}
					</p>
					<div>
						<p className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-gray-400">
							{t("analysis.drivers")}
						</p>
						<BulletList items={priority_tier.priority_drivers} />
					</div>
				</SectionCard>

				{/* 4 — Risk & Dependencies */}
				<SectionCard title={t("analysis.risks")}>
					{risk_and_dependencies.risks.length > 0 && (
						<div className="mb-3">
							<p className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-gray-400">
								{t("analysis.risks_label")}
							</p>
							<BulletList items={risk_and_dependencies.risks} />
						</div>
					)}
					{risk_and_dependencies.dependencies.length > 0 && (
						<div className="mb-3">
							<p className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-gray-400">
								{t("analysis.deps")}
							</p>
							<BulletList items={risk_and_dependencies.dependencies} />
						</div>
					)}
					{risk_and_dependencies.open_questions.length > 0 && (
						<div>
							<p className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-gray-400">
								{t("analysis.open_q")}
							</p>
							<BulletList items={risk_and_dependencies.open_questions} />
						</div>
					)}
				</SectionCard>

				{/* 5 — Use Case Form fields */}
				{/* TODO: replace with full 22-field typed display once field names are confirmed.
                  Currently shows whatever keys the finalizer returns. */}
				<SectionCard title={t("analysis.form_fields")}>
					{Object.entries(use_case_form ?? {})
						.filter(([, v]) => v != null && String(v).trim())
						.map(([key, value]) => (
							<Row
								key={key}
								label={key.replace(/_/g, " ")}
								value={String(value)}
							/>
						))}
				</SectionCard>
			</div>
		</div>
	);
}
