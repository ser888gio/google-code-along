"use client";

import { useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { FeedbackVote } from "../../lib/api";
import type { Message } from "../hooks/useMessages";
import { useLocale } from "../i18n/LocaleContext";

export default function MessageBubble({
	msg,
	sessionId,
	onFeedback,
	onFeedbackComment,
	onChoiceSelect,
	textareaRef,
}: {
	msg: Message;
	sessionId: string | null;
	onFeedback: (localId: string, vote: FeedbackVote) => Promise<void>;
	onFeedbackComment: (localId: string, comment: string) => Promise<void>;
	onChoiceSelect?: (msgId: string, choice: string) => void;
	textareaRef?: React.RefObject<HTMLTextAreaElement | null>;
}) {
	const { t } = useLocale();
	const isUser = msg.role === "user";
	const [commentOpen, setCommentOpen] = useState(false);
	const [localComment, setLocalComment] = useState<string | null>(null);
	const comment = localComment ?? msg.feedback?.comment ?? "";

	if (isUser) {
		return (
			<div className="rounded border border-gray-200 bg-[#f5fdf5] px-4 py-3">
				<div className="mb-1 text-[11px] font-bold uppercase tracking-widest text-gray-500">
					{t("label.you")}
				</div>
				<div className="flex items-start gap-2">
					<svg
						aria-hidden="true"
						className="mt-0.5 shrink-0 text-gray-400"
						width="14"
						height="16"
						viewBox="0 0 14 16"
						fill="none"
					>
						<rect
							x="1"
							y="1"
							width="12"
							height="14"
							rx="1"
							stroke="currentColor"
							strokeWidth="1.5"
						/>
						<path
							d="M3 5h8M3 8h8M3 11h5"
							stroke="currentColor"
							strokeWidth="1.5"
							strokeLinecap="round"
						/>
					</svg>
					<span className="text-base text-gray-700">{msg.text}</span>
				</div>
			</div>
		);
	}

	const isThinking = msg.streaming && !msg.text;
	const canSendFeedback = Boolean(sessionId && msg.messageId && !msg.streaming);
	const feedbackPending = Boolean(msg.feedback?.pending);
	const activeVote = msg.feedback?.vote;

	async function handleVote(vote: FeedbackVote) {
		if (!canSendFeedback || feedbackPending) return;
		setCommentOpen(true);
		await onFeedback(msg.id, vote);
	}

	async function handleCommentSubmit(e: React.FormEvent<HTMLFormElement>) {
		e.preventDefault();
		if (!canSendFeedback || !activeVote || feedbackPending) return;
		await onFeedbackComment(msg.id, comment);
		setLocalComment(null);
	}

	return (
		<div className="rounded border border-gray-200 bg-white px-4 py-3">
			<div className="mb-1 text-[11px] font-bold uppercase tracking-widest text-gray-500">
				{t("label.ai_consultant")}
			</div>
			{isThinking ? (
				<p className="text-base italic text-gray-400">
					{t("thinking")}
					<span className="inline-flex gap-0.5 ml-0.5 align-middle">
						<span className="animate-[blink_1.2s_step-end_infinite] [animation-delay:0s]">
							.
						</span>
						<span className="animate-[blink_1.2s_step-end_infinite] [animation-delay:0.4s]">
							.
						</span>
						<span className="animate-[blink_1.2s_step-end_infinite] [animation-delay:0.8s]">
							.
						</span>
					</span>
				</p>
			) : (
				<>
					<div className="text-base text-gray-800 [&_p]:my-1 [&_p:first-child]:mt-0 [&_p:last-child]:mb-0 [&_ol]:my-1 [&_ol]:list-decimal [&_ol]:pl-5 [&_ul]:my-1 [&_ul]:list-disc [&_ul]:pl-5 [&_li]:my-0.5 [&_strong]:font-semibold [&_em]:italic [&_code]:rounded [&_code]:bg-gray-100 [&_code]:px-1 [&_code]:py-0.5 [&_code]:text-[0.85em] [&_a]:text-[#4a6659] [&_a]:underline [&_h1]:mt-2 [&_h1]:mb-1 [&_h1]:text-lg [&_h1]:font-bold [&_h2]:mt-2 [&_h2]:mb-1 [&_h2]:text-base [&_h2]:font-bold [&_h3]:mt-2 [&_h3]:mb-1 [&_h3]:text-base [&_h3]:font-semibold">
						<ReactMarkdown remarkPlugins={[remarkGfm]}>
							{msg.text}
						</ReactMarkdown>
						{msg.streaming && (
							<span className="ml-0.5 inline-block h-4 w-1.5 animate-[blink_1s_step-end_infinite] bg-gray-400 align-middle" />
						)}
					</div>
					{msg.choices &&
						msg.choices.length > 0 &&
						!msg.streaming &&
						onChoiceSelect && (
							<div className="mt-3 flex flex-wrap gap-2">
								{msg.choices.map((choice) => (
									<button
										key={choice}
										type="button"
										onClick={() => onChoiceSelect(msg.id, choice)}
										className="rounded border border-[#4a6659] px-3 py-1.5 text-sm text-[#1a3a2a] transition-colors hover:bg-[#edf5ef]"
									>
										{choice}
									</button>
								))}
								<button
									type="button"
									onClick={() => {
										onChoiceSelect(msg.id, "");
										textareaRef?.current?.focus();
									}}
									className="rounded border border-gray-300 px-3 py-1.5 text-sm text-gray-500 transition-colors hover:border-gray-400 hover:text-gray-700"
								>
									{t("btn.other")}
								</button>
							</div>
						)}
				</>
			)}
			{canSendFeedback && !isThinking && (
				<div className="mt-3 border-t border-gray-100 pt-2">
					<div className="flex items-center gap-1.5">
						<button
							type="button"
							aria-label={t("feedback.helpful")}
							title={t("feedback.helpful")}
							disabled={feedbackPending}
							onClick={() => void handleVote("up")}
							className={`flex h-7 w-7 items-center justify-center rounded border transition-colors ${
								activeVote === "up"
									? "border-[#4a6659] bg-[#edf5ef] text-[#1a3a2a]"
									: "border-gray-200 text-gray-400 hover:border-gray-300 hover:text-gray-700"
							} ${feedbackPending ? "opacity-60" : ""}`}
						>
							<svg
								aria-hidden="true"
								width="15"
								height="15"
								viewBox="0 0 24 24"
								fill="none"
								stroke="currentColor"
								strokeWidth="1.8"
								strokeLinecap="round"
								strokeLinejoin="round"
							>
								<path d="M7 10v10" />
								<path d="M15 5.5 14 10h5.5a2 2 0 0 1 2 2.3l-1.1 6a2 2 0 0 1-2 1.7H7V10l5-7a2 2 0 0 1 3 2.5Z" />
								<path d="M3 10h4v10H3z" />
							</svg>
						</button>
						<button
							type="button"
							aria-label={t("feedback.unhelpful")}
							title={t("feedback.unhelpful")}
							disabled={feedbackPending}
							onClick={() => void handleVote("down")}
							className={`flex h-7 w-7 items-center justify-center rounded border transition-colors ${
								activeVote === "down"
									? "border-red-300 bg-red-50 text-red-700"
									: "border-gray-200 text-gray-400 hover:border-gray-300 hover:text-gray-700"
							} ${feedbackPending ? "opacity-60" : ""}`}
						>
							<svg
								aria-hidden="true"
								width="15"
								height="15"
								viewBox="0 0 24 24"
								fill="none"
								stroke="currentColor"
								strokeWidth="1.8"
								strokeLinecap="round"
								strokeLinejoin="round"
							>
								<path d="M17 14V4" />
								<path d="M9 18.5 10 14H4.5a2 2 0 0 1-2-2.3l1.1-6a2 2 0 0 1 2-1.7H17v10l-5 7a2 2 0 0 1-3-2.5Z" />
								<path d="M21 14h-4V4h4z" />
							</svg>
						</button>
						{activeVote && (
							<button
								type="button"
								onClick={() => setCommentOpen((open) => !open)}
								className="ml-1 text-xs text-gray-500 hover:text-gray-800"
							>
								{commentOpen ? t("btn.hide_comment") : t("btn.add_comment")}
							</button>
						)}
					</div>
					{commentOpen && activeVote && (
						<form onSubmit={handleCommentSubmit} className="mt-2 flex gap-2">
							<textarea
								value={comment}
								onChange={(e) => setLocalComment(e.target.value)}
								placeholder={t("feedback.optional_comment")}
								rows={2}
								className="min-h-16 flex-1 resize-y rounded border border-gray-200 px-3 py-2 text-sm text-gray-700 outline-none focus:border-[#4a6659] focus:ring-1 focus:ring-[#4a6659]"
							/>
							<button
								type="submit"
								disabled={feedbackPending}
								className="h-8 self-end rounded bg-[#4a6659] px-3 text-xs font-semibold text-white transition-opacity hover:opacity-90 disabled:opacity-60"
							>
								{t("btn.save")}
							</button>
						</form>
					)}
				</div>
			)}
		</div>
	);
}
