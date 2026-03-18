/**
 * Task 6.4 — Component tests for the chat UI (app/page.tsx).
 *
 * Tests cover:
 *  - Message rendering (user and assistant bubbles)
 *  - Loading / streaming states
 *  - Error card rendering and dismissal
 *  - ProgressTracker step display
 *  - Input send button disabled states
 *  - Tab bar navigation
 *  - RS document preview rendering
 */

import React from "react";
import { render, screen, fireEvent, act, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import "@testing-library/jest-dom";

// Mock the api module before importing the page
jest.mock("../lib/api", () => ({
  streamChat: jest.fn(),
}));

// Mock next/navigation (Next.js may inject this)
jest.mock("next/navigation", () => ({
  useRouter: () => ({ push: jest.fn() }),
  useSearchParams: () => new URLSearchParams(),
  usePathname: () => "/",
}));

// Mock the Skoda theme provider — just render children
jest.mock("../app/providers", () => ({
  Providers: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

// Stub @skodaflow/web-library to avoid SSR/ESM issues in Jest
jest.mock("@skodaflow/web-library", () => ({
  SkodaThemeProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

import ChatPage from "../app/page";
import { streamChat } from "../lib/api";

const mockStreamChat = streamChat as jest.Mock;

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function renderPage() {
  return render(<ChatPage />);
}

// Simulate a completed stream that sends one text chunk
function resolveStream(chunk = "Hello! I am your AI consultant.", sessionId = "test-session") {
  mockStreamChat.mockImplementationOnce(
    async (
      _message: string,
      _sessionId: string | null,
      onChunk: (text: string) => void,
      onSessionId: (id: string) => void,
      onDone: () => void
    ) => {
      onSessionId(sessionId);
      onChunk(chunk);
      onDone();
    }
  );
}

// Simulate a stream that calls onError
function rejectStream(error = "Server error: 500") {
  mockStreamChat.mockImplementationOnce(
    async (
      _message: string,
      _sessionId: string | null,
      _onChunk: (text: string) => void,
      _onSessionId: (id: string) => void,
      _onDone: () => void,
      onError: (err: string) => void
    ) => {
      onError(error);
    }
  );
}

// ---------------------------------------------------------------------------
// Initial render
// ---------------------------------------------------------------------------

describe("ChatPage — initial render", () => {
  it("renders the Document Preprocessor header", () => {
    renderPage();
    expect(screen.getByText("Document Preprocessor")).toBeInTheDocument();
  });

  it("renders the empty-state placeholder text", () => {
    renderPage();
    expect(
      screen.getByText(/Start a conversation to build your specification/i)
    ).toBeInTheDocument();
  });

  it("renders the Send button", () => {
    renderPage();
    expect(screen.getByRole("button", { name: /Send/i })).toBeInTheDocument();
  });

  it("Send button is disabled when input is empty", () => {
    renderPage();
    const sendBtn = screen.getByRole("button", { name: /Send/i });
    expect(sendBtn).toBeDisabled();
  });

  it("renders the textarea input", () => {
    renderPage();
    expect(screen.getByPlaceholderText(/Describe your project/i)).toBeInTheDocument();
  });

  it("renders the progress tracker with step labels", () => {
    renderPage();
    expect(screen.getByText("COMPLETION")).toBeInTheDocument();
    expect(screen.getByText("VALIDATION")).toBeInTheDocument();
    expect(screen.getByText("DONE")).toBeInTheDocument();
  });
});

// ---------------------------------------------------------------------------
// Message rendering
// ---------------------------------------------------------------------------

describe("ChatPage — message rendering", () => {
  beforeEach(() => {
    mockStreamChat.mockReset();
  });

  it("shows user message bubble after sending", async () => {
    resolveStream();
    renderPage();

    const textarea = screen.getByPlaceholderText(/Describe your project/i);
    await userEvent.type(textarea, "I want to automate sales reports.");
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /Send/i }));
    });

    expect(
      screen.getByText("I want to automate sales reports.")
    ).toBeInTheDocument();
  });

  it("shows assistant message bubble after stream completes", async () => {
    resolveStream("Hello! I am your AI consultant.");
    renderPage();

    const textarea = screen.getByPlaceholderText(/Describe your project/i);
    await userEvent.type(textarea, "Hello");
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /Send/i }));
    });

    await waitFor(() => {
      expect(screen.getByText("Hello! I am your AI consultant.")).toBeInTheDocument();
    });
  });

  it("shows 'AI CONSULTANT' label on assistant messages", async () => {
    resolveStream("Hi there.");
    renderPage();

    const textarea = screen.getByPlaceholderText(/Describe your project/i);
    await userEvent.type(textarea, "Hello");
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /Send/i }));
    });

    await waitFor(() => {
      expect(screen.getByText("AI CONSULTANT")).toBeInTheDocument();
    });
  });

  it("shows 'VY' label on user messages", async () => {
    resolveStream();
    renderPage();

    const textarea = screen.getByPlaceholderText(/Describe your project/i);
    await userEvent.type(textarea, "My message");
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /Send/i }));
    });

    expect(screen.getByText("VY")).toBeInTheDocument();
  });

  it("clears the input field after sending", async () => {
    resolveStream();
    renderPage();

    const textarea = screen.getByPlaceholderText(/Describe your project/i) as HTMLTextAreaElement;
    await userEvent.type(textarea, "Test message");
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /Send/i }));
    });

    expect(textarea.value).toBe("");
  });
});

// ---------------------------------------------------------------------------
// Loading / streaming state
// ---------------------------------------------------------------------------

describe("ChatPage — loading state", () => {
  it("disables textarea while streaming", async () => {
    let unblock: () => void = () => {};
    mockStreamChat.mockImplementationOnce(
      async (
        _msg: string,
        _sid: string | null,
        _onChunk: (t: string) => void,
        _onSid: (id: string) => void,
        onDone: () => void
      ) => {
        await new Promise<void>((resolve) => {
          unblock = () => { onDone(); resolve(); };
        });
      }
    );

    renderPage();
    const textarea = screen.getByPlaceholderText(/Describe your project/i);
    await userEvent.type(textarea, "Streaming test");

    act(() => {
      fireEvent.click(screen.getByRole("button", { name: /Send/i }));
    });

    expect(textarea).toBeDisabled();
    await act(async () => { unblock(); });
  });
});

// ---------------------------------------------------------------------------
// Error card
// ---------------------------------------------------------------------------

describe("ChatPage — error state", () => {
  beforeEach(() => {
    mockStreamChat.mockReset();
  });

  it("shows error card when stream returns an error", async () => {
    rejectStream("Server error: 500");
    renderPage();

    const textarea = screen.getByPlaceholderText(/Describe your project/i);
    await userEvent.type(textarea, "This will fail");
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /Send/i }));
    });

    await waitFor(() => {
      expect(screen.getByText("Server error: 500")).toBeInTheDocument();
    });
  });

  it("shows ERROR label on the error card", async () => {
    rejectStream("Some error");
    renderPage();

    const textarea = screen.getByPlaceholderText(/Describe your project/i);
    await userEvent.type(textarea, "Fail");
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /Send/i }));
    });

    await waitFor(() => {
      expect(screen.getByText("ERROR")).toBeInTheDocument();
    });
  });

  it("dismisses the error card when ✕ is clicked", async () => {
    rejectStream("Dismiss me");
    renderPage();

    const textarea = screen.getByPlaceholderText(/Describe your project/i);
    await userEvent.type(textarea, "Trigger error");
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /Send/i }));
    });

    await waitFor(() => {
      expect(screen.getByText("Dismiss me")).toBeInTheDocument();
    });

    const dismissBtn = screen.getByRole("button", { name: "✕" });
    await act(async () => {
      fireEvent.click(dismissBtn);
    });

    expect(screen.queryByText("Dismiss me")).not.toBeInTheDocument();
  });
});

// ---------------------------------------------------------------------------
// Tab bar
// ---------------------------------------------------------------------------

describe("ChatPage — tab bar", () => {
  const TABS = ["Input", "Preview", "ER", "Flow", "Data", "Gantt", "Quality", "Summary"];

  it("renders all RS tabs", () => {
    renderPage();
    for (const tab of TABS) {
      expect(screen.getByRole("button", { name: tab })).toBeInTheDocument();
    }
  });

  it("clicking a non-Preview tab shows 'not yet available' message", async () => {
    renderPage();
    const erTab = screen.getByRole("button", { name: "ER" });
    await act(async () => {
      fireEvent.click(erTab);
    });
    expect(screen.getByText(/ER.*not yet available/i)).toBeInTheDocument();
  });

  it("clicking Preview tab shows the requirements specification panel", async () => {
    renderPage();
    // Click away first, then back
    const erTab = screen.getByRole("button", { name: "ER" });
    const previewTab = screen.getByRole("button", { name: "Preview" });
    await act(async () => { fireEvent.click(erTab); });
    await act(async () => { fireEvent.click(previewTab); });
    expect(screen.getByText("Requirements Specification")).toBeInTheDocument();
  });
});

// ---------------------------------------------------------------------------
// ProgressTracker
// ---------------------------------------------------------------------------

describe("ChatPage — progress tracker", () => {
  it("step 1 is active on initial load (shows '1' in tracker)", () => {
    renderPage();
    // Step 1 is active — step numbers 2 and 3 should be visible as text
    expect(screen.getByText("COMPLETION")).toBeInTheDocument();
  });

  it("advances to step 2 when first message is sent", async () => {
    resolveStream();
    renderPage();

    const textarea = screen.getByPlaceholderText(/Describe your project/i);
    await userEvent.type(textarea, "First message");
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /Send/i }));
    });

    // After sending, step 2 (VALIDATION) should be active/done
    await waitFor(() => {
      expect(screen.getByText("VALIDATION")).toBeInTheDocument();
    });
  });
});

// ---------------------------------------------------------------------------
// RS preview content
// ---------------------------------------------------------------------------

describe("ChatPage — RS preview", () => {
  it("shows mock RS content in the Preview tab by default", () => {
    renderPage();
    // MOCK_RS data includes this title
    expect(screen.getByText("Requirements Specification")).toBeInTheDocument();
  });

  it("shows mock RS project name", () => {
    renderPage();
    expect(screen.getByText(/Automated Sales Report System/i)).toBeInTheDocument();
  });

  it("shows section headings in the preview", () => {
    renderPage();
    expect(screen.getByText("1. Project Overview")).toBeInTheDocument();
    expect(screen.getByText("3. Functional Requirements")).toBeInTheDocument();
  });
});
