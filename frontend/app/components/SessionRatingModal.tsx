"use client";

import type { SessionRating } from "../../lib/api";
import { useLocale } from "../i18n/LocaleContext";

const SESSION_RATINGS = [
	1, 2, 3, 4, 5,
] as const satisfies readonly SessionRating[];

export default function SessionRatingModal({
	open,
	rating,
	comment,
	submitting,
	onClose,
	onRatingChange,
	onCommentChange,
	onSubmit,
}: {
	open: boolean;
	rating: SessionRating | null;
	comment: string;
	submitting: boolean;
	onClose: () => void;
	onRatingChange: (rating: SessionRating) => void;
	onCommentChange: (comment: string) => void;
	onSubmit: (e: React.FormEvent<HTMLFormElement>) => void;
}) {
	const { t } = useLocale();
	if (!open) return null;

	return (
		<div
			className="fixed inset-0 z-50 flex items-center justify-center bg-black/40"
			role="button"
			tabIndex={0}
			aria-label="Close"
			onClick={() => !submitting && onClose()}
			onKeyDown={(e) => {
				if ((e.key === "Enter" || e.key === " ") && !submitting) onClose();
			}}
		>
			<form
				onSubmit={onSubmit}
				className="w-90 rounded-lg border border-gray-200 bg-white p-5 shadow-xl"
				onClick={(e) => e.stopPropagation()}
				onKeyDown={(e) => e.stopPropagation()}
			>
				<div className="mb-4 flex items-start justify-between gap-4">
					<div>
						<h2 className="text-sm font-semibold text-gray-800">
							{t("modal.rate_session")}
						</h2>
						<p className="mt-1 text-xs text-gray-500">{t("modal.rate_desc")}</p>
					</div>
					<button
						type="button"
						disabled={submitting}
						onClick={onClose}
						className="text-xs text-gray-400 hover:text-gray-600 disabled:opacity-50"
					>
						x
					</button>
				</div>
				<div className="grid grid-cols-5 gap-2">
					{SESSION_RATINGS.map((option) => (
						<button
							key={option}
							type="button"
							onClick={() => onRatingChange(option)}
							className={`h-10 rounded border text-sm font-semibold transition-colors ${
								rating === option
									? "border-[#4a6659] bg-[#edf5ef] text-[#1a3a2a]"
									: "border-gray-200 text-gray-500 hover:border-gray-300"
							}`}
						>
							{option}
						</button>
					))}
				</div>
				<textarea
					value={comment}
					onChange={(e) => onCommentChange(e.target.value)}
					placeholder={t("feedback.optional_comment")}
					rows={3}
					className="mt-3 min-h-24 w-full resize-y rounded border border-gray-200 px-3 py-2 text-sm text-gray-700 outline-none focus:border-[#4a6659] focus:ring-1 focus:ring-[#4a6659]"
				/>
				<div className="mt-4 flex justify-end gap-2">
					<button
						type="button"
						disabled={submitting}
						onClick={onClose}
						className="rounded border border-gray-200 px-3 py-2 text-xs font-semibold text-gray-600 hover:bg-gray-50 disabled:opacity-50"
					>
						{t("btn.cancel")}
					</button>
					<button
						type="submit"
						disabled={!rating || submitting}
						className="rounded bg-[#4a6659] px-3 py-2 text-xs font-semibold text-white transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
					>
						{submitting ? t("modal.saving") : t("modal.end_chat")}
					</button>
				</div>
			</form>
		</div>
	);
}
