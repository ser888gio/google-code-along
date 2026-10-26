"use client";

import { useEffect } from "react";
import { useLocale } from "../i18n/LocaleContext";

export type ToastTone = "error" | "success";

const TONE_STYLES: Record<
	ToastTone,
	{ border: string; icon: string; title: string; titleKey: string }
> = {
	error: {
		border: "border-red-300",
		icon: "text-red-500",
		title: "text-red-600",
		titleKey: "error.something_wrong",
	},
	success: {
		border: "border-[#4caf50]",
		icon: "text-[#4caf50]",
		title: "text-[#1a3a2a]",
		titleKey: "notice.done",
	},
};

export default function Toast({
	tone,
	message,
	onDismiss,
}: { tone: ToastTone; message: string; onDismiss: () => void }) {
	const { t } = useLocale();
	useEffect(() => {
		const timer = setTimeout(onDismiss, 6000);
		return () => clearTimeout(timer);
	}, [onDismiss]);

	const style = TONE_STYLES[tone];
	return (
		<div
			role={tone === "error" ? "alert" : "status"}
			className={`fixed bottom-6 left-6 right-6 z-50 flex items-start gap-3 rounded-lg border bg-white px-4 py-3 shadow-lg sm:left-auto sm:max-w-sm ${style.border}`}
		>
			<svg
				aria-hidden="true"
				className={`mt-0.5 shrink-0 ${style.icon}`}
				width="18"
				height="18"
				viewBox="0 0 24 24"
				fill="none"
				stroke="currentColor"
				strokeWidth="2"
				strokeLinecap="round"
				strokeLinejoin="round"
			>
				<circle cx="12" cy="12" r="10" />
				{tone === "error" ? (
					<>
						<line x1="12" y1="8" x2="12" y2="12" />
						<line x1="12" y1="16" x2="12.01" y2="16" />
					</>
				) : (
					<path d="M8 12.5l2.5 2.5L16 9.5" />
				)}
			</svg>
			<div className="flex-1">
				<p
					className={`text-[11px] font-bold uppercase tracking-widest ${style.title}`}
				>
					{t(style.titleKey)}
				</p>
				<p className="mt-0.5 text-sm text-gray-700">{message}</p>
			</div>
			<button
				type="button"
				onClick={onDismiss}
				aria-label={t("btn.close")}
				className="shrink-0 text-gray-400 hover:text-gray-600"
			>
				✕
			</button>
		</div>
	);
}
