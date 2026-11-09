import { act, renderHook } from "@testing-library/react";
import { useChatSession } from "../app/hooks/useChatSession";
import { useRsExtraction } from "../app/hooks/useRsExtraction";
import { installBackend, jsonResponse } from "./fakes";

afterEach(() => {
	jest.useRealTimers();
});

describe("analysis polling", () => {
	it("stops and reports failure when the finalizer errors", async () => {
		jest.useFakeTimers();
		const backend = installBackend([
			["/analyses/s1", () => jsonResponse({ status: "error" })],
		]);
		const { result } = renderHook(() => useRsExtraction(() => {}));

		act(() => {
			result.current.startPolling("s1");
		});
		await act(async () => {
			await jest.advanceTimersByTimeAsync(5000);
		});
		expect(result.current.finalizingStatus).toBe("failed");

		await act(async () => {
			await jest.advanceTimersByTimeAsync(20000);
		});
		expect(backend).toHaveBeenCalledTimes(1);
	});

	it("reports failure instead of waiting forever when the backend stays unreachable", async () => {
		jest.useFakeTimers();
		const backend = installBackend([
			["/analyses/s1", () => jsonResponse({}, 503)],
		]);
		const { result } = renderHook(() => useRsExtraction(() => {}));

		act(() => {
			result.current.startPolling("s1");
		});
		await act(async () => {
			await jest.advanceTimersByTimeAsync(60000);
		});

		expect(result.current.finalizingStatus).toBe("failed");
		expect(backend).toHaveBeenCalledTimes(3);
	});

	it("keeps waiting while the analysis has not been created yet", async () => {
		jest.useFakeTimers();
		installBackend([
			["/analyses/s1", () => jsonResponse({ status: "not_found" })],
		]);
		const { result } = renderHook(() => useRsExtraction(() => {}));

		act(() => {
			result.current.startPolling("s1");
		});
		await act(async () => {
			await jest.advanceTimersByTimeAsync(60000);
		});

		expect(result.current.finalizingStatus).toBe("idle");
	});

	it("does not send a new request while the previous one is still waiting", async () => {
		jest.useFakeTimers();
		const backend = installBackend([
			["/analyses/s1", () => new Promise<Response>(() => {})],
		]);
		const { result } = renderHook(() => useRsExtraction(() => {}));

		act(() => {
			result.current.startPolling("s1");
		});
		await act(async () => {
			await jest.advanceTimersByTimeAsync(30000);
		});

		expect(backend).toHaveBeenCalledTimes(1);
	});
});

describe("reopening a session from history", () => {
	it.each([
		["pending", "finalizing"],
		["error", "failed"],
		["not_found", "idle"],
	])("maps analysis status %s to %s", async (backendStatus, expected) => {
		installBackend([
			["/analyses/s1", () => jsonResponse({ status: backendStatus })],
		]);
		const { result } = renderHook(() => useChatSession(() => {}));

		const loaded = await act(() => result.current.loadSession("s1"));

		expect(loaded.finalizingStatus).toBe(expected);
	});
});
