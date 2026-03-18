/**
 * Task 6.4 (partial) — Unit tests for the API client (lib/api.ts).
 *
 * Verifies that streamChat, downloadPdf, and getDocument make the correct
 * HTTP calls and correctly parse SSE events / responses.
 */

import { streamChat, downloadPdf, getDocument, extractContext } from "../lib/api";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function buildStream(...lines: string[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder();
  const chunks = lines.map((l) => encoder.encode(l));
  let i = 0;
  return new ReadableStream({
    pull(controller) {
      if (i < chunks.length) {
        controller.enqueue(chunks[i++]);
      } else {
        controller.close();
      }
    },
  });
}

function mockFetch(
  body: ReadableStream | null,
  status = 200,
  headers: Record<string, string> = {}
): jest.Mock {
  const mockRes = {
    ok: status >= 200 && status < 300,
    status,
    body,
    json: jest.fn().mockResolvedValue({}),
    blob: jest.fn().mockResolvedValue(new Blob(["fake-pdf"], { type: "application/pdf" })),
    headers: new Headers(headers),
  };
  return jest.fn().mockResolvedValue(mockRes);
}

// ---------------------------------------------------------------------------
// streamChat
// ---------------------------------------------------------------------------

describe("streamChat", () => {
  afterEach(() => {
    jest.restoreAllMocks();
  });

  it("calls the /chat/stream endpoint with correct payload", async () => {
    const stream = buildStream(
      'data: {"session_id": "abc123"}\n\n',
      "data: [DONE]\n\n"
    );
    const fetch = mockFetch(stream);
    global.fetch = fetch;

    await streamChat("Hello", null, jest.fn(), jest.fn(), jest.fn(), jest.fn());

    expect(fetch).toHaveBeenCalledWith(
      expect.stringContaining("/chat/stream"),
      expect.objectContaining({
        method: "POST",
        body: expect.stringContaining('"message":"Hello"'),
      })
    );
  });

  it("calls onSessionId with the session_id from the first SSE event", async () => {
    const stream = buildStream(
      'data: {"session_id": "abc123"}\n\n',
      "data: [DONE]\n\n"
    );
    global.fetch = mockFetch(stream);

    const onSessionId = jest.fn();
    await streamChat("Hi", null, jest.fn(), onSessionId, jest.fn(), jest.fn());

    expect(onSessionId).toHaveBeenCalledWith("abc123");
  });

  it("calls onChunk for each text SSE event", async () => {
    const stream = buildStream(
      'data: {"session_id": "s1"}\n\n',
      'data: {"text": "Hello "}\n\n',
      'data: {"text": "world!"}\n\n',
      "data: [DONE]\n\n"
    );
    global.fetch = mockFetch(stream);

    const onChunk = jest.fn();
    await streamChat("Hi", "s1", onChunk, jest.fn(), jest.fn(), jest.fn());

    expect(onChunk).toHaveBeenCalledTimes(2);
    expect(onChunk).toHaveBeenNthCalledWith(1, "Hello ");
    expect(onChunk).toHaveBeenNthCalledWith(2, "world!");
  });

  it("calls onDone when [DONE] event is received", async () => {
    const stream = buildStream(
      'data: {"session_id": "s1"}\n\n',
      "data: [DONE]\n\n"
    );
    global.fetch = mockFetch(stream);

    const onDone = jest.fn();
    await streamChat("Hi", "s1", jest.fn(), jest.fn(), onDone, jest.fn());

    expect(onDone).toHaveBeenCalledTimes(1);
  });

  it("calls onError when the server returns a non-OK status", async () => {
    global.fetch = mockFetch(null, 500);

    const onError = jest.fn();
    await streamChat("Hi", null, jest.fn(), jest.fn(), jest.fn(), onError);

    expect(onError).toHaveBeenCalledWith("Server error: 500");
  });

  it("passes session_id in the request body when provided", async () => {
    const stream = buildStream(
      'data: {"session_id": "existing"}\n\n',
      "data: [DONE]\n\n"
    );
    const fetch = mockFetch(stream);
    global.fetch = fetch;

    await streamChat("Hello", "existing", jest.fn(), jest.fn(), jest.fn(), jest.fn());

    const callBody = JSON.parse(fetch.mock.calls[0][1].body);
    expect(callBody.session_id).toBe("existing");
  });

  it("passes null session_id when no session exists", async () => {
    const stream = buildStream(
      'data: {"session_id": "new-id"}\n\n',
      "data: [DONE]\n\n"
    );
    const fetch = mockFetch(stream);
    global.fetch = fetch;

    await streamChat("Hello", null, jest.fn(), jest.fn(), jest.fn(), jest.fn());

    const callBody = JSON.parse(fetch.mock.calls[0][1].body);
    expect(callBody.session_id).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// getDocument
// ---------------------------------------------------------------------------

describe("getDocument", () => {
  afterEach(() => {
    jest.restoreAllMocks();
  });

  it("calls /document with the session_id", async () => {
    const mockRes = {
      ok: true,
      status: 200,
      json: jest.fn().mockResolvedValue({ markdown: null, ready: false }),
    };
    const fetch = jest.fn().mockResolvedValue(mockRes);
    global.fetch = fetch;

    await getDocument("test-session");

    expect(fetch).toHaveBeenCalledWith(
      expect.stringContaining("/document"),
      expect.objectContaining({
        method: "POST",
        body: expect.stringContaining('"session_id":"test-session"'),
      })
    );
  });

  it("returns the parsed DocumentResponse", async () => {
    const mockRes = {
      ok: true,
      status: 200,
      json: jest.fn().mockResolvedValue({ markdown: "# RS", ready: true }),
    };
    global.fetch = jest.fn().mockResolvedValue(mockRes);

    const result = await getDocument("s1");

    expect(result.ready).toBe(true);
    expect(result.markdown).toBe("# RS");
  });

  it("throws on non-OK status", async () => {
    const mockRes = { ok: false, status: 500 };
    global.fetch = jest.fn().mockResolvedValue(mockRes);

    await expect(getDocument("s1")).rejects.toThrow("Error 500");
  });
});

// ---------------------------------------------------------------------------
// extractContext
// ---------------------------------------------------------------------------

describe("extractContext", () => {
  afterEach(() => {
    jest.restoreAllMocks();
  });

  it("calls /context/extract with the session_id", async () => {
    const payload = {
      completeness: 40,
      sections: {
        executive_summary:           { filled: false, content: null },
        current_state:               { filled: true,  content: "Some current state." },
        desired_future_state:        { filled: false, content: null },
        scope:                       { filled: false, content: null },
        functional_requirements:     { filled: false, content: null },
        non_functional_requirements: { filled: false, content: null },
        assumptions_and_constraints: { filled: false, content: null },
        open_questions:              { filled: false, content: null },
      },
    };
    const fetch = jest.fn().mockResolvedValue({
      ok: true,
      json: jest.fn().mockResolvedValue(payload),
    });
    global.fetch = fetch;

    const result = await extractContext("session-abc");

    expect(fetch).toHaveBeenCalledWith(
      expect.stringContaining("/context/extract"),
      expect.objectContaining({
        method: "POST",
        body: expect.stringContaining('"session_id":"session-abc"'),
      })
    );
    expect(result?.completeness).toBe(40);
    expect(result?.sections.current_state.filled).toBe(true);
  });

  it("returns null when the server responds with a non-OK status", async () => {
    global.fetch = jest.fn().mockResolvedValue({ ok: false, status: 404 });

    const result = await extractContext("bad-session");

    expect(result).toBeNull();
  });

  it("returns null on network error", async () => {
    global.fetch = jest.fn().mockRejectedValue(new Error("Network failure"));

    const result = await extractContext("any-session");

    expect(result).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// downloadPdf
// ---------------------------------------------------------------------------

describe("downloadPdf", () => {
  let createObjectURL: jest.Mock;
  let revokeObjectURL: jest.Mock;
  let clickSpy: jest.Mock;

  beforeEach(() => {
    createObjectURL = jest.fn().mockReturnValue("blob:fake-url");
    revokeObjectURL = jest.fn();
    global.URL.createObjectURL = createObjectURL;
    global.URL.revokeObjectURL = revokeObjectURL;

    clickSpy = jest.fn();
    jest.spyOn(document, "createElement").mockReturnValue({
      href: "",
      download: "",
      click: clickSpy,
    } as unknown as HTMLAnchorElement);
  });

  afterEach(() => {
    jest.restoreAllMocks();
  });

  it("calls /document/pdf with the session_id", async () => {
    const mockRes = {
      ok: true,
      blob: jest.fn().mockResolvedValue(new Blob(["pdf"], { type: "application/pdf" })),
    };
    const fetch = jest.fn().mockResolvedValue(mockRes);
    global.fetch = fetch;

    await downloadPdf("my-session");

    expect(fetch).toHaveBeenCalledWith(
      expect.stringContaining("/document/pdf"),
      expect.objectContaining({
        method: "POST",
        body: expect.stringContaining('"session_id":"my-session"'),
      })
    );
  });

  it("triggers a browser download click", async () => {
    const mockRes = {
      ok: true,
      blob: jest.fn().mockResolvedValue(new Blob(["pdf"])),
    };
    global.fetch = jest.fn().mockResolvedValue(mockRes);

    await downloadPdf("my-session");

    expect(clickSpy).toHaveBeenCalled();
  });

  it("throws an error when the server returns non-OK", async () => {
    const mockRes = {
      ok: false,
      status: 404,
      json: jest.fn().mockResolvedValue({ detail: "No document found." }),
    };
    global.fetch = jest.fn().mockResolvedValue(mockRes);

    await expect(downloadPdf("no-doc-session")).rejects.toThrow("No document found.");
  });
});
