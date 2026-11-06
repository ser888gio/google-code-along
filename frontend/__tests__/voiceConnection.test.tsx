import { act, renderHook } from "@testing-library/react";
import type React from "react";
import { useVoiceMode } from "../app/hooks/useVoiceMode";
import { LocaleProvider } from "../app/i18n/LocaleContext";
import { useWebSocket } from "../lib/useWebSocket";
import {
	FakeWebSocket,
	installAudio,
	installBackend,
	removeAudio,
} from "./fakes";

beforeEach(() => {
	FakeWebSocket.instances = [];
	globalThis.WebSocket = FakeWebSocket as unknown as typeof WebSocket;
	localStorage.setItem("locale", "en");
});

afterEach(() => {
	removeAudio();
});

function renderSocket() {
	return renderHook(() =>
		useWebSocket({ onAudioData: () => {}, onMessage: () => {} }),
	);
}

describe("voice WebSocket connection", () => {
	it("keeps the new connection when the previous socket's close event arrives late", () => {
		const { result } = renderSocket();
		act(() => result.current.connect("u", "s1", "en"));
		const first = FakeWebSocket.instances[0];
		act(() => first.serverOpens());

		act(() => result.current.disconnect());
		act(() => result.current.connect("u", "s1", "en"));
		const second = FakeWebSocket.instances[1];
		act(() => second.serverOpens());
		act(() => first.closeEventArrives());

		const chunk = new ArrayBuffer(4);
		act(() => result.current.sendAudio(chunk));
		expect(second.sent).toEqual([chunk]);
		expect(result.current.connectionState).toBe("connected");
	});

	it("still reports the error after the failed socket closes", () => {
		const { result } = renderSocket();
		act(() => result.current.connect("u", "s1", "en"));
		const socket = FakeWebSocket.instances[0];

		act(() => socket.errorEventArrives());
		act(() => socket.closeEventArrives());

		expect(result.current.connectionState).toBe("error");
	});
});

type ShownMessage = { role: string; text: string };

function chatLog() {
	const messages = new Map<string, ShownMessage>();
	return {
		shown: () => [...messages.values()],
		addMessage: (role: "user" | "assistant", text: string) => {
			const id = `m${messages.size}`;
			messages.set(id, { role, text });
			return id;
		},
		appendToMessage: (id: string, chunk: string) => {
			const msg = messages.get(id);
			if (msg) msg.text += chunk;
		},
		replaceMessageText: (id: string, text: string) => {
			const msg = messages.get(id);
			if (msg) msg.text = text;
		},
	};
}

function renderVoice(
	setError: (msg: string) => void = () => {},
	log = chatLog(),
) {
	const wrapper = ({ children }: { children: React.ReactNode }) => (
		<LocaleProvider>{children}</LocaleProvider>
	);
	return renderHook(
		() =>
			useVoiceMode({
				addMessage: log.addMessage,
				appendToMessage: log.appendToMessage,
				replaceMessageText: log.replaceMessageText,
				finalizeMessage: () => {},
				applyExtraction: () => {},
				setSrsData: () => {},
				setFinalizingStatus: () => {},
				setActiveTab: () => {},
				setIsExtracting: () => {},
				extractNonceRef: { current: 0 },
				setError,
				sessionId: "s1",
			}),
		{ wrapper },
	);
}

describe("voice mode", () => {
	it("stays in text mode and explains why when audio playback cannot start", async () => {
		const errors: string[] = [];
		const { result } = renderVoice((msg) => errors.push(msg));

		await act(async () => {
			await result.current.handleToggleVoice("s1", () => {});
		});

		expect(result.current.chatMode).toBe("text");
		expect(FakeWebSocket.instances).toHaveLength(0);
		expect(errors).toEqual([
			"Voice mode could not start audio playback in this browser.",
		]);
	});

	it("returns to text mode when the server closes the connection", async () => {
		installAudio();
		const { result } = renderVoice();
		await act(async () => {
			await result.current.handleToggleVoice("s1", () => {});
		});
		const socket = FakeWebSocket.instances[0];
		act(() => socket.serverOpens());
		expect(result.current.chatMode).toBe("voice");

		act(() => socket.closeEventArrives());

		expect(result.current.chatMode).toBe("text");
	});
});

describe("voice transcripts", () => {
	async function connectedVoice() {
		installAudio();
		installBackend([]);
		const log = chatLog();
		const { result } = renderVoice(() => {}, log);
		await act(async () => {
			await result.current.handleToggleVoice("s1", () => {});
		});
		const socket = FakeWebSocket.instances[0];
		act(() => socket.serverOpens());
		return { log, socket };
	}

	it("shows what the user said when only the final transcript arrives", async () => {
		const { log, socket } = await connectedVoice();

		act(() => socket.serverSends({ type: "user_transcript", text: "Ano" }));

		expect(log.shown()).toEqual([{ role: "user", text: "Ano" }]);
	});

	it("corrects the live caption instead of repeating it when the final transcript arrives after the turn", async () => {
		const { log, socket } = await connectedVoice();

		act(() => {
			socket.serverSends({ type: "user_transcript_partial", text: "Helo" });
			socket.serverSends({ type: "turn_complete" });
			socket.serverSends({ type: "user_transcript", text: "Hello" });
		});

		expect(log.shown()).toEqual([{ role: "user", text: "Hello" }]);
	});
});
