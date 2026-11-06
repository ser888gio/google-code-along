import { act, renderHook } from "@testing-library/react";
import { useAudioPlayer } from "../lib/useAudioPlayer";
import { useAudioRecorder } from "../lib/useAudioRecorder";
import {
	FakeAudioContext,
	installAudio,
	installMicrophone,
	removeAudio,
} from "./fakes";

class BrokenWorkletContext extends FakeAudioContext {
	audioWorklet = {
		addModule: async () => {
			throw new Error("worklet blocked");
		},
	};
}

beforeEach(() => {
	installAudio();
});

afterEach(() => {
	removeAudio();
});

describe("microphone recording", () => {
	it("opens only one microphone stream when the mic is tapped twice during the permission prompt", async () => {
		const mic = installMicrophone();
		const { result } = renderHook(() => useAudioRecorder(() => {}));

		await act(async () => {
			void result.current.startRecording();
			void result.current.startRecording();
			mic.grantAll();
		});

		expect(mic.tracks).toHaveLength(1);
		expect(result.current.isRecording).toBe(true);
	});

	it("releases the microphone when recording stops before permission is granted", async () => {
		const mic = installMicrophone();
		const { result } = renderHook(() => useAudioRecorder(() => {}));

		await act(async () => {
			const starting = result.current.startRecording();
			result.current.stopRecording();
			mic.grantAll();
			await starting;
		});

		expect(mic.tracks[0].stopped).toBe(true);
		expect(result.current.isRecording).toBe(false);
	});

	it("releases the microphone when the recorder fails to start after permission", async () => {
		Object.assign(globalThis, { AudioContext: BrokenWorkletContext });
		const mic = installMicrophone();
		const { result } = renderHook(() => useAudioRecorder(() => {}));

		await act(async () => {
			const starting = result.current.startRecording();
			mic.grantAll();
			await starting;
		});

		expect(mic.tracks[0].stopped).toBe(true);
		expect(FakeAudioContext.instances[0].closed).toBe(true);
		expect(result.current.error).toBe("worklet blocked");
	});
});

describe("audio playback", () => {
	it("closes the audio context when the player fails to initialise", async () => {
		Object.assign(globalThis, { AudioContext: BrokenWorkletContext });
		const { result } = renderHook(() => useAudioPlayer());

		let started: boolean | undefined;
		await act(async () => {
			started = await result.current.init();
		});

		expect(started).toBe(false);
		expect(FakeAudioContext.instances[0].closed).toBe(true);
	});
});
