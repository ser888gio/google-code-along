import { streamChat } from "../lib/api";

function sseResponse(chunks: string[], ok = true, status = 200) {
	const encoder = new TextEncoder();
	const body = new ReadableStream<Uint8Array>({
		start(controller) {
			for (const chunk of chunks) controller.enqueue(encoder.encode(chunk));
			controller.close();
		},
	});
	return { ok, status, body } as unknown as Response;
}

function callbacks() {
	const calls: string[] = [];
	const rec =
		(name: string) =>
		(...args: unknown[]) =>
			calls.push(args.length ? `${name}:${JSON.stringify(args)}` : name);
	return {
		calls,
		onChunk: rec("chunk"),
		onSessionId: rec("session"),
		onDone: rec("done"),
		onError: rec("error"),
		onFinalizing: rec("finalizing"),
		onFieldUpdate: rec("field"),
		onActiveField: rec("active"),
		onMessageId: rec("messageId"),
		onChoices: rec("choices"),
		onTextReplace: rec("replace"),
	};
}

async function run(chunks: string[], ok = true, status = 200) {
	global.fetch = jest.fn().mockResolvedValue(sseResponse(chunks, ok, status));
	const cb = callbacks();
	await streamChat(
		"hi",
		null,
		cb.onChunk,
		cb.onSessionId,
		cb.onDone,
		cb.onError,
		cb.onFinalizing,
		cb.onFieldUpdate,
		undefined,
		undefined,
		cb.onActiveField,
		cb.onMessageId,
		cb.onChoices,
		cb.onTextReplace,
	);
	return cb.calls;
}

describe("streamChat SSE dispatch", () => {
	it("fires every key of one event in a fixed order", async () => {
		const event = {
			text_replace: "R",
			choices: ["a", "b"],
			field_update: { key: "department", value: "IT" },
			active_field: "requester",
			event: "finalizing",
			text: "T",
			message_id: "m1",
			session_id: "s1",
		};
		expect(await run([`data: ${JSON.stringify(event)}\n`])).toEqual([
			'session:["s1"]',
			'messageId:["m1"]',
			'chunk:["T"]',
			"finalizing",
			'active:["requester"]',
			'field:["department","IT"]',
			'choices:[["a","b"]]',
			'replace:["R"]',
			"done",
		]);
	});

	it("stops on error after reporting ids, skipping later keys and done", async () => {
		const event = { session_id: "s1", error: "boom", text: "ignored" };
		expect(
			await run([
				`data: ${JSON.stringify(event)}\n`,
				'data: {"text":"after"}\n',
			]),
		).toEqual(['session:["s1"]', 'error:["boom"]']);
	});

	it("stops at [DONE] and ignores what follows", async () => {
		expect(
			await run([
				'data: {"text":"a"}\n',
				"data: [DONE]\n",
				'data: {"text":"b"}\n',
			]),
		).toEqual(['chunk:["a"]', "done"]);
	});

	it("reassembles lines split across chunks and skips junk", async () => {
		expect(
			await run(['data: {"te', 'xt":"joined"}\n: comment\ndata: not-json\n']),
		).toEqual(['chunk:["joined"]', "done"]);
	});

	it("defaults a missing field_update value and ignores malformed updates", async () => {
		expect(
			await run([
				'data: {"field_update":{"key":"comments"}}\n',
				'data: {"field_update":{"value":"no key"}}\n',
				'data: {"active_field":42,"choices":"nope","text_replace":1}\n',
			]),
		).toEqual(['field:["comments",""]', "done"]);
	});

	it("reports a server error without reading the body", async () => {
		expect(await run([], false, 503)).toEqual(['error:["Server error: 503"]']);
	});
});
