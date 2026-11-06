// Working stand-ins for browser APIs jsdom lacks (WebSocket, Web Audio) and for
// the backend over fetch. They behave like the real thing at the boundary.

export function jsonResponse(body: unknown, status = 200) {
	return {
		ok: status >= 200 && status < 300,
		status,
		json: async () => body,
	} as Response;
}

type Route = [urlPart: string, respond: () => Promise<Response> | Response];

export function installBackend(routes: Route[]): jest.Mock {
	const fetchFn = jest.fn(async (url: string) => {
		const route = routes.find(([part]) => String(url).includes(part));
		return route ? route[1]() : jsonResponse({}, 404);
	});
	globalThis.fetch = fetchFn as unknown as typeof fetch;
	return fetchFn;
}

export class FakeWebSocket {
	static readonly OPEN = 1;
	static instances: FakeWebSocket[] = [];

	readyState = 0;
	binaryType = "blob";
	sent: unknown[] = [];
	onopen: (() => void) | null = null;
	onclose: (() => void) | null = null;
	onerror: ((e: Event) => void) | null = null;
	onmessage: ((e: MessageEvent) => void) | null = null;

	constructor(public url: string) {
		FakeWebSocket.instances.push(this);
	}

	send(data: unknown) {
		this.sent.push(data);
	}

	// Real sockets deliver the close event later, so tests fire it explicitly.
	close() {
		this.readyState = 3;
	}

	serverOpens() {
		this.readyState = FakeWebSocket.OPEN;
		this.onopen?.();
	}

	closeEventArrives() {
		this.readyState = 3;
		this.onclose?.();
	}

	errorEventArrives() {
		this.onerror?.(new Event("error"));
	}

	serverSends(message: unknown) {
		this.onmessage?.({ data: JSON.stringify(message) } as MessageEvent);
	}
}

export class FakeAudioContext {
	static instances: FakeAudioContext[] = [];
	closed = false;
	destination = {};
	audioWorklet = { addModule: async () => undefined };

	constructor() {
		FakeAudioContext.instances.push(this);
	}

	createMediaStreamSource() {
		return { connect() {}, disconnect() {} };
	}

	async close() {
		this.closed = true;
	}
}

class FakeMicTrack {
	stopped = false;
	stop() {
		this.stopped = true;
	}
}

// getUserMedia stays pending until the test grants it, like a permission prompt.
export function installMicrophone() {
	const tracks: FakeMicTrack[] = [];
	const prompts: Array<() => void> = [];
	Object.defineProperty(globalThis.navigator, "mediaDevices", {
		configurable: true,
		value: {
			getUserMedia: () =>
				new Promise((resolve) => {
					const track = new FakeMicTrack();
					tracks.push(track);
					prompts.push(() => resolve({ getTracks: () => [track] }));
				}),
		},
	});
	return {
		tracks,
		grantAll: () => {
			for (const grant of prompts.splice(0)) grant();
		},
	};
}

class FakeAudioWorkletNode {
	port = { postMessage: () => undefined, onmessage: null };
	connect() {}
	disconnect() {}
}

export function installAudio() {
	FakeAudioContext.instances = [];
	Object.assign(globalThis, {
		AudioContext: FakeAudioContext,
		AudioWorkletNode: FakeAudioWorkletNode,
	});
}

export function removeAudio() {
	const g = globalThis as Record<string, unknown>;
	Reflect.deleteProperty(g, "AudioContext");
	Reflect.deleteProperty(g, "AudioWorkletNode");
}
