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
  getDiscoveryState: jest.fn().mockResolvedValue(null),
  downloadPdf: jest.fn().mockResolvedValue(undefined),
  downloadRsTemplateDocx: jest.fn().mockResolvedValue(undefined),
  getFirestoreData: jest.fn().mockResolvedValue(null),
  getSessions: jest.fn().mockResolvedValue([]),
  getHistory: jest.fn().mockResolvedValue([]),
  getAnalysis: jest.fn().mockResolvedValue({ status: "not_found" }),
  getSessionUploads: jest.fn().mockResolvedValue([]),
  patchDirectFields: jest.fn().mockResolvedValue(null),
}));

// Stub child components that have their own complex deps
jest.mock("../app/components/FileUpload", () => () => <div data-testid="file-upload" />);
jest.mock("../app/components/BpmnPanel", () => () => <div data-testid="bpmn-panel" />);
jest.mock("../app/components/DataflowPanel", () => () => <div data-testid="dataflow-panel" />);
jest.mock("../app/components/FirestoreSrsPanel", () => () => <div data-testid="firestore-panel" />);
jest.mock("../app/components/AnalysisPanel", () => ({
  __esModule: true,
  default: () => <div data-testid="analysis-panel" />,
  FinalizingOverlay: () => <div data-testid="finalizing-overlay" />,
}));

jest.mock("react-markdown", () => ({
  __esModule: true,
  default: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));
jest.mock("remark-gfm", () => ({
  __esModule: true,
  default: jest.fn(),
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
import { streamChat, extractContext, patchDirectFields } from "../lib/api";

const mockStreamChat = streamChat as jest.Mock;
const mockExtractContext = extractContext as jest.Mock;
const mockPatchDirectFields = patchDirectFields as jest.Mock;

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

  it("renders the welcome message", () => {
    renderPage();
    expect(
      screen.getByText(/Welcome to your Business Analyst session/i)
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

  it("renders the Preview tab by default", () => {
    renderPage();
    expect(screen.getAllByText("Requirements Specification").length).toBeGreaterThanOrEqual(1);
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
      expect(screen.getAllByText("AI CONSULTANT").length).toBeGreaterThanOrEqual(1);
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

  it("shows the error toast title", async () => {
    rejectStream("Some error");
    renderPage();

    const textarea = screen.getByPlaceholderText(/Describe your project/i);
    await userEvent.type(textarea, "Fail");
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /Send/i }));
    });

    await waitFor(() => {
      expect(screen.getByText("Something went wrong")).toBeInTheDocument();
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
  const TABS = ["Preview", "BPMN", "Data", "Database", "Analysis", "Summary"];

  it("renders all RS tabs", () => {
    renderPage();
    for (const tab of TABS) {
      expect(screen.getByRole("button", { name: tab })).toBeInTheDocument();
    }
  });

  it("clicking Analysis before finalization shows the pending message", async () => {
    renderPage();
    const analysisTab = screen.getByRole("button", { name: "Analysis" });
    await act(async () => {
      fireEvent.click(analysisTab);
    });
    expect(screen.getByText(/Analysis will appear here/i)).toBeInTheDocument();
  });

  it("clicking Preview tab shows the requirements specification panel", async () => {
    renderPage();
    // Click away first, then back
    const analysisTab = screen.getByRole("button", { name: "Analysis" });
    const previewTab = screen.getByRole("button", { name: "Preview" });
    await act(async () => { fireEvent.click(analysisTab); });
    await act(async () => { fireEvent.click(previewTab); });
    // "Requirements Specification" appears in both the tab bar label and the live template header
    expect(screen.getAllByText("Requirements Specification").length).toBeGreaterThanOrEqual(1);
  });
});

// ---------------------------------------------------------------------------
// Conversation state
// ---------------------------------------------------------------------------

describe("ChatPage — conversation state", () => {
  it("shows the requirements panel on initial load", () => {
    renderPage();
    expect(screen.getAllByText("Requirements Specification").length).toBeGreaterThanOrEqual(1);
  });

  it("keeps the sent message visible after the stream finishes", async () => {
    resolveStream();
    renderPage();

    const textarea = screen.getByPlaceholderText(/Describe your project/i);
    await userEvent.type(textarea, "First message");
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /Send/i }));
    });

    await waitFor(() => {
      expect(screen.getByText("First message")).toBeInTheDocument();
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

  it("shows the current RS section labels before any conversation", () => {
    renderPage();
    expect(screen.getByText("Identity & Current State")).toBeInTheDocument();
    expect(screen.getByText("Target State")).toBeInTheDocument();
    expect(screen.getByText("Value & ROI")).toBeInTheDocument();
    expect(screen.getByText("Priority & Risk")).toBeInTheDocument();
    expect(screen.getByText("Technical Context")).toBeInTheDocument();
    expect(screen.getByText("Additional")).toBeInTheDocument();
  });

  it("shows placeholder text when rsPartial is null", () => {
    renderPage();
    const placeholders = screen.getAllByText(/Gathering/i);
    expect(placeholders.length).toBe(13);
  });

  it("updates field content after a turn when extractContext returns data", async () => {
    mockExtractContext.mockResolvedValue({
      completeness: 35,
      fields: {
        process_as_is: { filled: true, value: "Team uses spreadsheets today." },
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

// ---------------------------------------------------------------------------
// Direct chat field answers
// ---------------------------------------------------------------------------

describe("ChatPage — direct chat field answers", () => {
  beforeEach(() => {
    mockStreamChat.mockReset();
    mockExtractContext.mockReset();
    mockExtractContext.mockResolvedValue(null);
    mockPatchDirectFields.mockReset();
    mockPatchDirectFields.mockResolvedValue(null);
  });

  function resolveTwoTurns(firstReply: string, secondReply = "Dekuji.") {
    mockStreamChat
      .mockImplementationOnce(
        async (
          _message: string,
          _sessionId: string | null,
          onChunk: (text: string) => void,
          onSessionId: (id: string) => void,
          onDone: () => Promise<void>
        ) => {
          onSessionId("test-session");
          onChunk(firstReply);
          await onDone();
        }
      )
      .mockImplementationOnce(
        async (
          _message: string,
          _sessionId: string | null,
          onChunk: (text: string) => void,
          onSessionId: (id: string) => void,
          onDone: () => Promise<void>
        ) => {
          onSessionId("test-session");
          onChunk(secondReply);
          await onDone();
        }
      );
  }

  it("fills Product Owner immediately when the user answers the direct question", async () => {
    resolveTwoTurns("Kdo je Product Owner?");
    renderPage();

    const textarea = screen.getByPlaceholderText(/Describe your project/i);
    await userEvent.type(textarea, "Potrebujeme novy use case.");
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /Send/i }));
    });

    await waitFor(() => {
      expect(screen.getByText("Kdo je Product Owner?")).toBeInTheDocument();
    });

    await userEvent.type(textarea, "Ales Priklad");
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /Send/i }));
    });

    const productOwnerInput = screen.getByPlaceholderText(/Enter product owner/i) as HTMLInputElement;
    expect(productOwnerInput.value).toBe("Ales Priklad");
    expect(mockPatchDirectFields).toHaveBeenCalledWith("test-session", {
      product_owner: "Ales Priklad",
    });

    const secondCallDirectFields = mockStreamChat.mock.calls[1][8];
    expect(secondCallDirectFields).toEqual(
      expect.objectContaining({ product_owner: "Ales Priklad" })
    );
  });

  it("does not fill Product Owner when the user defers the answer", async () => {
    resolveTwoTurns("Kdo je Product Owner?");
    renderPage();

    const textarea = screen.getByPlaceholderText(/Describe your project/i);
    await userEvent.type(textarea, "Potrebujeme novy use case.");
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /Send/i }));
    });

    await waitFor(() => {
      expect(screen.getByText("Kdo je Product Owner?")).toBeInTheDocument();
    });

    await userEvent.type(textarea, "Nevim, doplnim pozdeji.");
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /Send/i }));
    });

    const productOwnerInput = screen.getByPlaceholderText(/Enter product owner/i) as HTMLInputElement;
    expect(productOwnerInput.value).toBe("");
    expect(mockPatchDirectFields).not.toHaveBeenCalled();

    const secondCallDirectFields = mockStreamChat.mock.calls[1][8];
    expect(secondCallDirectFields?.product_owner).toBeUndefined();
    expect(mockStreamChat.mock.calls[1][9]).toEqual(["product_owner"]);
  });
});
