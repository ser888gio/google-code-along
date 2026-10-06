import { render, screen } from "@testing-library/react";
import type React from "react";
import "@testing-library/jest-dom";

import ChatInput from "../app/components/ChatInput";
import { LocaleProvider } from "../app/i18n/LocaleContext";
import en from "../app/i18n/en.json";

type Props = React.ComponentProps<typeof ChatInput>;

function renderInput(props: Partial<Props> = {}) {
	localStorage.setItem("locale", "en");
	const base: Props = {
		chatMode: "voice",
		input: "",
		isStreaming: false,
		sessionEnded: false,
		sessionId: "s1",
		wsConnectionState: "connected",
		isRecording: false,
		isPlaying: false,
		recorderError: null,
		textareaRef: { current: null },
		onInputChange: jest.fn(),
		onKeyDown: jest.fn(),
		onSend: jest.fn(),
		onOpenUpload: jest.fn(),
		onOpenRating: jest.fn(),
		onMicToggle: jest.fn(),
	};
	render(
		<LocaleProvider>
			<ChatInput {...base} {...props} />
		</LocaleProvider>,
	);
}

const mic = () => screen.getByTitle(/speaking/);

describe("ChatInput — voice mode", () => {
	it.each([
		[{ isRecording: true }, "voice.listening"],
		[{ isPlaying: true }, "voice.ai_speaking"],
		[{ sessionEnded: true }, "voice.chat_ended"],
		[{}, "voice.tap_to_speak"],
		[{ wsConnectionState: "disconnected" }, "voice.connecting"],
	] as const)("status for %j", (props, key) => {
		renderInput(props);
		expect(
			screen.getAllByText(en[key as keyof typeof en]).length,
		).toBeGreaterThanOrEqual(1);
	});

	it("recording takes priority over playing", () => {
		renderInput({ isRecording: true, isPlaying: true });
		expect(screen.getByText(en["voice.listening"])).toBeInTheDocument();
		expect(screen.queryByText(en["voice.ai_speaking"])).toBeNull();
	});

	it("shows connection and recorder errors", () => {
		renderInput({ wsConnectionState: "error", recorderError: "Mic denied" });
		expect(screen.getByText("Mic denied")).toBeInTheDocument();
		expect(screen.getByText(en["voice.conn_failed"])).toBeInTheDocument();
	});

	it("mic shows the stop state while recording", () => {
		renderInput({ isRecording: true });
		expect(mic()).toHaveAttribute("title", "Stop speaking");
		expect(mic().className).toContain("bg-red-500");
	});

	it("mic is disabled and greyed when not connected", () => {
		renderInput({ wsConnectionState: "connecting" });
		expect(mic()).toBeDisabled();
		expect(mic().className).toContain("bg-gray-300");
	});

	it("mic is enabled when connected and session open", () => {
		renderInput();
		expect(mic()).toBeEnabled();
		expect(mic().className).toContain("bg-[#4a6659]");
	});
});

describe("ChatInput — text mode", () => {
	it("disables End chat without a session", () => {
		renderInput({ chatMode: "text", sessionId: null });
		expect(
			screen.getByRole("button", { name: en["btn.end_chat"] }),
		).toBeDisabled();
	});

	it("shows the ended label once the session ended", () => {
		renderInput({ chatMode: "text", sessionEnded: true });
		expect(
			screen.getByRole("button", { name: en["btn.ended"] }),
		).toBeDisabled();
	});
});
