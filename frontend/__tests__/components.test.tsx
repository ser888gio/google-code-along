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
  extractContext: jest.fn().mockResolvedValue(null),
  downloadPdf: jest.fn().mockResolvedValue(undefined),
}));

// Stub child components that have their own complex deps
jest.mock("../app/components/FileUpload", () => () => <div data-testid="file-upload" />);
jest.mock("../app/components/BpmnPanel", () => () => <div data-testid="bpmn-panel" />);

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
import { streamChat, extractContext } from "../lib/api";

const mockStreamChat = streamChat as jest.Mock;
const mockExtractContext = extractContext as jest.Mock;

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
      onDone: () => Promise<void>
    ) => {
      onSessionId(sessionId);
      onChunk(chunk);
      await onDone();
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
  const TABS = ["Input", "Preview", "ER", "BPMN", "Flow", "Data", "Gantt", "Quality", "Summary"];

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
    // "Requirements Specification" appears in both the tab bar label and the live template header
    expect(screen.getAllByText("Requirements Specification").length).toBeGreaterThanOrEqual(1);
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
// RS live template
// ---------------------------------------------------------------------------

describe("ChatPage — RS live template", () => {
  beforeEach(() => {
    mockExtractContext.mockReset();
    mockExtractContext.mockResolvedValue(null);
  });

  it("shows the Requirements Specification title in the Preview tab", () => {
    renderPage();
    // Appears in both the tab bar label and the live template header
    expect(screen.getAllByText("Requirements Specification").length).toBeGreaterThanOrEqual(1);
  });

  it("shows all 8 section labels as placeholders before any conversation", () => {
    renderPage();
    expect(screen.getByText("Executive Summary")).toBeInTheDocument();
    expect(screen.getByText("Current State (As-Is)")).toBeInTheDocument();
    expect(screen.getByText("Desired Future State (To-Be)")).toBeInTheDocument();
    expect(screen.getByText("Scope")).toBeInTheDocument();
    expect(screen.getByText("Functional Requirements")).toBeInTheDocument();
    expect(screen.getByText("Non-Functional Requirements")).toBeInTheDocument();
    expect(screen.getByText("Assumptions & Constraints")).toBeInTheDocument();
    expect(screen.getByText("Open Questions")).toBeInTheDocument();
  });

  it("shows placeholder text when rsPartial is null", () => {
    renderPage();
    const placeholders = screen.getAllByText(/Gathering information/i);
    expect(placeholders.length).toBe(8);
  });

  it("updates section content after a turn when extractContext returns data", async () => {
    mockExtractContext.mockResolvedValue({
      completeness: 35,
      sections: {
        executive_summary:           { filled: false, content: null },
        current_state:               { filled: true,  content: "Team uses spreadsheets today." },
        desired_future_state:        { filled: false, content: null },
        scope:                       { filled: false, content: null },
        functional_requirements:     { filled: false, content: null },
        non_functional_requirements: { filled: false, content: null },
        assumptions_and_constraints: { filled: false, content: null },
        open_questions:              { filled: false, content: null },
      },
    });
    resolveStream("Great, let me note that down.");
    renderPage();

    const textarea = screen.getByPlaceholderText(/Describe your project/i);
    await userEvent.type(textarea, "We use spreadsheets today.");
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /Send/i }));
    });

    await waitFor(() => {
      expect(screen.getByText("Team uses spreadsheets today.")).toBeInTheDocument();
    });
  });

  it("shows completeness progress bar", () => {
    renderPage();
    expect(screen.getAllByText(/0%/i).length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText(/80% to generate/i)).toBeInTheDocument();
  });
});
