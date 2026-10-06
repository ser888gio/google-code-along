import { fireEvent, render, screen } from "@testing-library/react";
import type React from "react";
import "@testing-library/jest-dom";

import MessageBubble from "../app/components/MessageBubble";
import type { Message } from "../app/hooks/useMessages";
import { LocaleProvider } from "../app/i18n/LocaleContext";

jest.mock("react-markdown", () => ({
	__esModule: true,
	default: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));
jest.mock("remark-gfm", () => ({
	__esModule: true,
	default: jest.fn(),
}));

const assistant: Message = {
	id: "local-1",
	role: "assistant",
	text: "Hello there",
	messageId: "m1",
	streaming: false,
};

function renderBubble(
	msg: Message,
	props: Partial<React.ComponentProps<typeof MessageBubble>> = {},
) {
	const onFeedback = jest.fn().mockResolvedValue(undefined);
	const onFeedbackComment = jest.fn().mockResolvedValue(undefined);
	const onChoiceSelect = jest.fn();
	localStorage.setItem("locale", "en");
	render(
		<LocaleProvider>
			<MessageBubble
				msg={msg}
				sessionId="s1"
				onFeedback={onFeedback}
				onFeedbackComment={onFeedbackComment}
				onChoiceSelect={onChoiceSelect}
				{...props}
			/>
		</LocaleProvider>,
	);
	return { onFeedback, onFeedbackComment, onChoiceSelect };
}

describe("MessageBubble", () => {
	it("renders a user message with the YOU label and no feedback controls", () => {
		renderBubble({ id: "u1", role: "user", text: "My question" });
		expect(screen.getByText("YOU")).toBeInTheDocument();
		expect(screen.getByText("My question")).toBeInTheDocument();
		expect(screen.queryByLabelText("Mark answer helpful")).toBeNull();
	});

	it("shows the thinking indicator and no feedback while streaming without text", () => {
		renderBubble({ ...assistant, text: "", streaming: true });
		expect(screen.getByText(/Thinking/)).toBeInTheDocument();
		expect(screen.queryByLabelText("Mark answer helpful")).toBeNull();
	});

	it("hides feedback when there is no session or no server message id", () => {
		renderBubble(assistant, { sessionId: null });
		expect(screen.queryByLabelText("Mark answer helpful")).toBeNull();
	});

	it("renders choices and the Other button, and routes clicks", () => {
		const focus = jest.fn();
		const textareaRef = {
			current: { focus } as unknown as HTMLTextAreaElement,
		};
		const { onChoiceSelect } = renderBubble(
			{ ...assistant, choices: ["Option A", "Option B"] },
			{ textareaRef },
		);

		fireEvent.click(screen.getByRole("button", { name: "Option B" }));
		expect(onChoiceSelect).toHaveBeenCalledWith("local-1", "Option B");

		fireEvent.click(screen.getByRole("button", { name: "Other…" }));
		expect(onChoiceSelect).toHaveBeenCalledWith("local-1", "");
		expect(focus).toHaveBeenCalled();
	});

	it("does not render choices while streaming", () => {
		renderBubble({ ...assistant, streaming: true, choices: ["Option A"] });
		expect(screen.queryByRole("button", { name: "Option A" })).toBeNull();
	});

	it("sends a vote; the comment form waits until the vote is reflected in msg.feedback", () => {
		const { onFeedback } = renderBubble(assistant);
		fireEvent.click(screen.getByLabelText("Mark answer unhelpful"));
		expect(onFeedback).toHaveBeenCalledWith("local-1", "down");
		expect(screen.queryByPlaceholderText("Optional comment")).toBeNull();
	});

	it("submits a comment for the active vote and toggles the form", () => {
		const { onFeedbackComment } = renderBubble({
			...assistant,
			feedback: { vote: "up", comment: "old" },
		});

		fireEvent.click(screen.getByRole("button", { name: "Add comment" }));
		const box = screen.getByPlaceholderText("Optional comment");
		expect(box).toHaveValue("old");

		fireEvent.change(box, { target: { value: "new comment" } });
		fireEvent.click(screen.getByRole("button", { name: "Save" }));
		expect(onFeedbackComment).toHaveBeenCalledWith("local-1", "new comment");

		fireEvent.click(screen.getByRole("button", { name: "Hide comment" }));
		expect(screen.queryByPlaceholderText("Optional comment")).toBeNull();
	});

	it("disables vote buttons while feedback is pending", () => {
		renderBubble({ ...assistant, feedback: { vote: "up", pending: true } });
		expect(screen.getByLabelText("Mark answer helpful")).toBeDisabled();
		expect(screen.getByLabelText("Mark answer unhelpful")).toBeDisabled();
	});
});
