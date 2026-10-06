"use client";

import type { FeedbackVote } from "../../lib/api";
import type { Message } from "../hooks/useMessages";
import MessageBubble from "./MessageBubble";

export default function ChatTranscript({
	messages,
	sessionId,
	bottomRef,
	onFeedback,
	onFeedbackComment,
	onChoiceSelect,
	textareaRef,
}: {
	messages: Message[];
	sessionId: string | null;
	bottomRef: React.RefObject<HTMLDivElement | null>;
	onFeedback: (localId: string, vote: FeedbackVote) => Promise<void>;
	onFeedbackComment: (localId: string, comment: string) => Promise<void>;
	onChoiceSelect: (msgId: string, choice: string) => void;
	textareaRef: React.RefObject<HTMLTextAreaElement | null>;
}) {
	return (
		<div className="min-h-0 flex-1 space-y-3 overflow-y-auto px-4 py-4">
			{messages.map((msg) => (
				<MessageBubble
					key={msg.id}
					msg={msg}
					sessionId={sessionId}
					onFeedback={onFeedback}
					onFeedbackComment={onFeedbackComment}
					onChoiceSelect={onChoiceSelect}
					textareaRef={textareaRef}
				/>
			))}
			<div ref={bottomRef} />
		</div>
	);
}
