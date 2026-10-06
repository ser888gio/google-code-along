"use client";

import { useEffect } from "react";
import { useLocale } from "../i18n/LocaleContext";

export default function ErrorToast({
	message,
	onDismiss,
}: { message: string; onDismiss: () => void }) {
	const { t } = useLocale();
	useEffect(() => {
		const timer = setTimeout(onDismiss, 6000);
		return () => clearTimeout(timer);
	}, [onDismiss]);

	return (
		<div className="fixed bottom-6 right-6 z-50 flex max-w-sm items-start gap-3 rounded-lg border border-red-300 bg-white px-4 py-3 shadow-lg">
			<svg
				aria-hidden="true"
				className="mt-0.5 shrink-0 text-red-500"
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
				<line x1="12" y1="8" x2="12" y2="12" />
				<line x1="12" y1="16" x2="12.01" y2="16" />
			</svg>
			<div className="flex-1">
				<p className="text-[11px] font-bold uppercase tracking-widest text-red-600">
					{t("error.something_wrong")}
				</p>
				<p className="mt-0.5 text-sm text-gray-700">{message}</p>
			</div>
			<button
				type="button"
				onClick={onDismiss}
				className="shrink-0 text-gray-400 hover:text-gray-600"
			>
				✕
			</button>
		</div>
	);
}
