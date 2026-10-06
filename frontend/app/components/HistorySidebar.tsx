"use client";

import type { SessionSummary } from "../../lib/api";
import { useLocale } from "../i18n/LocaleContext";

export default function HistorySidebar({
	sessions,
	loading,
	currentSessionId,
	onClose,
	onNewConversation,
	onLoadSession,
}: {
	sessions: SessionSummary[];
	loading: boolean;
	currentSessionId: string | null;
	onClose: () => void;
	onNewConversation: () => void;
	onLoadSession: (id: string) => void;
}) {
	const { t } = useLocale();
	return (
		<div className="absolute inset-0 z-40 flex">
			<div className="flex w-72 flex-col border-r border-gray-200 bg-white shadow-xl">
				<div className="flex shrink-0 items-center justify-between border-b border-gray-200 px-4 py-3">
					<span className="text-sm font-bold text-gray-800">
						{t("sidebar.conversations")}
					</span>
					<button
						type="button"
						onClick={onClose}
						className="text-xs text-gray-400 hover:text-gray-600"
					>
						✕
					</button>
				</div>
				<div className="shrink-0 border-b border-gray-200 p-3">
					<button
						type="button"
						onClick={onNewConversation}
						className="w-full rounded border border-dashed border-gray-300 py-2 text-xs font-semibold text-gray-500 hover:border-[#4caf50] hover:text-[#4a6659] transition-colors"
					>
						{t("btn.new_conversation")}
					</button>
				</div>
				<div className="flex-1 overflow-y-auto">
					{loading ? (
						<p className="p-4 text-center text-xs text-gray-400">
							{t("sidebar.loading")}
						</p>
					) : sessions.length === 0 ? (
						<p className="p-4 text-center text-xs text-gray-400">
							{t("sidebar.no_conversations")}
						</p>
					) : (
						sessions.map((s) => (
							<button
								type="button"
								key={s.session_id}
								onClick={() => onLoadSession(s.session_id)}
								className={`w-full border-b border-gray-100 px-4 py-3 text-left hover:bg-gray-50 transition-colors ${s.session_id === currentSessionId ? "bg-[#f5fdf5]" : ""}`}
							>
								<p className="truncate text-xs font-medium text-gray-700">
									{s.preview ?? s.session_id}
								</p>
								{s.updated_at && (
									<p className="mt-0.5 text-[10px] text-gray-400">
										{new Date(s.updated_at).toLocaleString()}
									</p>
								)}
							</button>
						))
					)}
				</div>
			</div>
			<div
				className="flex-1 bg-black/20"
				role="button"
				tabIndex={0}
				aria-label="Close"
				onClick={onClose}
				onKeyDown={(e) =>
					e.key === "Enter" || e.key === " " ? onClose() : undefined
				}
			/>
		</div>
	);
}
