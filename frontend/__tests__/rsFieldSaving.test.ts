import { act, renderHook } from "@testing-library/react";
import { useRsState } from "../app/hooks/useRsState";
import { installBackend, jsonResponse } from "./fakes";

afterEach(() => {
	jest.useRealTimers();
});

it("flushing before a download waits for an edit whose save is already in flight", async () => {
	jest.useFakeTimers();
	let finishSave: () => void = () => {};
	installBackend([
		[
			"/rs-field-state",
			() =>
				new Promise<Response>((resolve) => {
					finishSave = () => resolve(jsonResponse({ fields: {} }));
				}),
		],
	]);
	const { result } = renderHook(() => useRsState("s1", () => {}));

	act(() => result.current.setUserField("department", "Finance"));
	await act(async () => {
		await jest.advanceTimersByTimeAsync(600);
	});

	const events: string[] = [];
	let flushing: Promise<void> = Promise.resolve();
	act(() => {
		flushing = result.current.flushPendingPatches().then(() => {
			events.push("flushed");
		});
	});
	await act(async () => {
		await Promise.resolve();
	});
	events.push("save finished");
	await act(async () => {
		finishSave();
		await flushing;
	});

	expect(events).toEqual(["save finished", "flushed"]);
});
