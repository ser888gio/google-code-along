"use client";

import { useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { FeedbackVote } from "../../lib/api";
import type { Message } from "../hooks/useMessages";
import { useLocale } from "../i18n/LocaleContext";

const VOTE_BUTTONS: Record<
	FeedbackVote,
	{ labelKey: string; activeClass: string; paths: string[] }
> = {
	up: {
		labelKey: "feedback.helpful",
		activeClass: "border-[#4a6659] bg-[#edf5ef] text-[#1a3a2a]",
		paths: [
			"M7 10v10",
			"M15 5.5 14 10h5.5a2 2 0 0 1 2 2.3l-1.1 6a2 2 0 0 1-2 1.7H7V10l5-7a2 2 0 0 1 3 2.5Z",
			"M3 10h4v10H3z",
		],
	},
	down: {
		labelKey: "feedback.unhelpful",
		activeClass: "border-red-300 bg-red-50 text-red-700",
		paths: [
			"M17 14V4",
			"M9 18.5 10 14H4.5a2 2 0 0 1-2-2.3l1.1-6a2 2 0 0 1 2-1.7H17v10l-5 7a2 2 0 0 1-3-2.5Z",
			"M21 14h-4V4h4z",
		],
	},
};

function deriveBubbleState(msg: Message, sessionId: string | null) {
	return {
		isThinking: Boolean(msg.streaming && !msg.text),
		canSendFeedback: Boolean(sessionId && msg.messageId && !msg.streaming),
		feedbackPending: Boolean(msg.feedback?.pending),
		activeVote: msg.feedback?.vote,
		showChoices: Boolean(msg.choices?.length) && !msg.streaming,
	};
}

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
	const [commentOpen, setCommentOpen] = useState(false);
	const [localComment, setLocalComment] = useState<string | null>(null);
	const comment = localComment ?? msg.feedback?.comment ?? "";

	if (msg.role === "user") return <UserBubble text={msg.text} />;

	const {
		isThinking,
		canSendFeedback,
		feedbackPending,
		activeVote,
		showChoices,
	} = deriveBubbleState(msg, sessionId);

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
				<ThinkingIndicator />
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
					{showChoices && onChoiceSelect && (
						<ChoiceButtons
							choices={msg.choices ?? []}
							onSelect={(choice) => onChoiceSelect(msg.id, choice)}
							onOther={() => {
								onChoiceSelect(msg.id, "");
								textareaRef?.current?.focus();
							}}
						/>
					)}
				</>
			)}
			{canSendFeedback && !isThinking && (
				<FeedbackBar
					activeVote={activeVote}
					pending={feedbackPending}
					commentOpen={commentOpen}
					comment={comment}
					onVote={(vote) => void handleVote(vote)}
					onToggleComment={() => setCommentOpen((open) => !open)}
					onCommentChange={setLocalComment}
					onSubmit={handleCommentSubmit}
				/>
			)}
		</div>
	);
}

function UserBubble({ text }: { text: string }) {
	const { t } = useLocale();
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
				<span className="text-base text-gray-700">{text}</span>
			</div>
		</div>
	);
}

function ThinkingIndicator() {
	const { t } = useLocale();
	return (
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
	);
}

function ChoiceButtons({
	choices,
	onSelect,
	onOther,
}: {
	choices: string[];
	onSelect: (choice: string) => void;
	onOther: () => void;
}) {
	const { t } = useLocale();
	return (
		<div className="mt-3 flex flex-wrap gap-2">
			{choices.map((choice) => (
				<button
					key={choice}
					type="button"
					onClick={() => onSelect(choice)}
					className="rounded border border-[#4a6659] px-3 py-1.5 text-sm text-[#1a3a2a] transition-colors hover:bg-[#edf5ef]"
				>
					{choice}
				</button>
			))}
			<button
				type="button"
				onClick={onOther}
				className="rounded border border-gray-300 px-3 py-1.5 text-sm text-gray-500 transition-colors hover:border-gray-400 hover:text-gray-700"
			>
				{t("btn.other")}
			</button>
		</div>
	);
}

function VoteButton({
	vote,
	active,
	pending,
	onVote,
}: {
	vote: FeedbackVote;
	active: boolean;
	pending: boolean;
	onVote: () => void;
}) {
	const { t } = useLocale();
	const { labelKey, activeClass, paths } = VOTE_BUTTONS[vote];
	return (
		<button
			type="button"
			aria-label={t(labelKey)}
			title={t(labelKey)}
			disabled={pending}
			onClick={onVote}
			className={`flex h-7 w-7 items-center justify-center rounded border transition-colors ${
				active
					? activeClass
					: "border-gray-200 text-gray-400 hover:border-gray-300 hover:text-gray-700"
			} ${pending ? "opacity-60" : ""}`}
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
				{paths.map((d) => (
					<path key={d} d={d} />
				))}
			</svg>
		</button>
	);
}

function FeedbackBar({
	activeVote,
	pending,
	commentOpen,
	comment,
	onVote,
	onToggleComment,
	onCommentChange,
	onSubmit,
}: {
	activeVote: FeedbackVote | undefined;
	pending: boolean;
	commentOpen: boolean;
	comment: string;
	onVote: (vote: FeedbackVote) => void;
	onToggleComment: () => void;
	onCommentChange: (comment: string) => void;
	onSubmit: (e: React.FormEvent<HTMLFormElement>) => void;
}) {
	const { t } = useLocale();
	return (
		<div className="mt-3 border-t border-gray-100 pt-2">
			<div className="flex items-center gap-1.5">
				{(["up", "down"] as const).map((vote) => (
					<VoteButton
						key={vote}
						vote={vote}
						active={activeVote === vote}
						pending={pending}
						onVote={() => onVote(vote)}
					/>
				))}
				{activeVote && (
					<button
						type="button"
						onClick={onToggleComment}
						className="ml-1 text-xs text-gray-500 hover:text-gray-800"
					>
						{commentOpen ? t("btn.hide_comment") : t("btn.add_comment")}
					</button>
				)}
			</div>
			{commentOpen && activeVote && (
				<form onSubmit={onSubmit} className="mt-2 flex gap-2">
					<textarea
						value={comment}
						onChange={(e) => onCommentChange(e.target.value)}
						placeholder={t("feedback.optional_comment")}
						rows={2}
						className="min-h-16 flex-1 resize-y rounded border border-gray-200 px-3 py-2 text-sm text-gray-700 outline-none focus:border-[#4a6659] focus:ring-1 focus:ring-[#4a6659]"
					/>
					<button
						type="submit"
						disabled={pending}
						className="h-8 self-end rounded bg-[#4a6659] px-3 text-xs font-semibold text-white transition-opacity hover:opacity-90 disabled:opacity-60"
					>
						{t("btn.save")}
					</button>
				</form>
			)}
		</div>
	);
}
