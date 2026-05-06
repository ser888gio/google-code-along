"use client";

import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { AdminTranscriptMessage } from "../../../lib/api";

interface Turn {
  id: string;
  user?: AdminTranscriptMessage;
  assistant?: AdminTranscriptMessage;
}

function turnsFromMessages(messages: AdminTranscriptMessage[]): Turn[] {
  const turns: Turn[] = [];
  let current: Turn | null = null;

  for (const message of messages) {
    if (message.role === "user") {
      current = {
        id: message.message_id ?? `${turns.length}:user`,
        user: message,
      };
      turns.push(current);
      continue;
    }

    if (!current || current.assistant) {
      current = {
        id: message.message_id ?? `${turns.length}:assistant`,
      };
      turns.push(current);
    }
    current.assistant = message;
  }

  return turns;
}

function Bubble({
  message,
  selected,
  onSelect,
}: {
  message: AdminTranscriptMessage;
  selected: boolean;
  onSelect: (message: AdminTranscriptMessage) => void;
}) {
  const isUser = message.role === "user";
  return (
    <button
      type="button"
      onClick={() => onSelect(message)}
      className={`h-full min-h-32 w-full rounded border px-4 py-3 text-left transition-colors ${
        selected
          ? "border-[#4a6659] bg-[#f5fdf5]"
          : isUser
            ? "border-gray-200 bg-gray-50 hover:border-gray-300"
            : "border-gray-200 bg-white hover:border-gray-300"
      }`}
    >
      <div className="mb-2 flex items-center justify-between gap-3">
        <span className="text-[11px] font-bold uppercase tracking-widest text-gray-500">
          {isUser ? "Prompt" : "Completion"}
        </span>
        {message.feedback?.vote === "down" && (
          <span className="rounded border border-red-200 bg-red-50 px-2 py-0.5 text-[11px] font-semibold text-red-700">
            thumbs down
          </span>
        )}
      </div>
      <div className="text-sm leading-6 text-gray-800 [&_a]:text-[#4a6659] [&_a]:underline [&_code]:rounded [&_code]:bg-gray-100 [&_code]:px-1 [&_h1]:mb-1 [&_h1]:text-base [&_h1]:font-bold [&_h2]:mb-1 [&_h2]:text-sm [&_h2]:font-bold [&_li]:my-0.5 [&_ol]:list-decimal [&_ol]:pl-5 [&_p]:my-1 [&_p:first-child]:mt-0 [&_p:last-child]:mb-0 [&_ul]:list-disc [&_ul]:pl-5">
        <ReactMarkdown remarkPlugins={[remarkGfm]}>
          {message.text_redacted || "_No redacted text captured._"}
        </ReactMarkdown>
      </div>
    </button>
  );
}

export default function MessageBubbles({
  messages,
  selectedMessageId,
  onSelect,
}: {
  messages: AdminTranscriptMessage[];
  selectedMessageId: string | null;
  onSelect: (message: AdminTranscriptMessage) => void;
}) {
  const turns = turnsFromMessages(messages);

  return (
    <div className="space-y-4">
      {turns.map((turn, index) => (
        <section key={turn.id} className="grid gap-3 lg:grid-cols-2">
          <div className="min-w-0">
            {turn.user ? (
              <Bubble
                message={turn.user}
                selected={selectedMessageId === turn.user.message_id}
                onSelect={onSelect}
              />
            ) : (
              <div className="h-full min-h-32 rounded border border-dashed border-gray-200 bg-gray-50" />
            )}
          </div>
          <div className="min-w-0">
            {turn.assistant ? (
              <Bubble
                message={turn.assistant}
                selected={selectedMessageId === turn.assistant.message_id}
                onSelect={onSelect}
              />
            ) : (
              <div className="h-full min-h-32 rounded border border-dashed border-gray-200 bg-gray-50 px-4 py-3 text-sm text-gray-400">
                Waiting for completion
              </div>
            )}
          </div>
          <div className="lg:col-span-2 border-b border-gray-100 pb-1">
            <span className="text-[11px] text-gray-400">Turn {index + 1}</span>
          </div>
        </section>
      ))}
    </div>
  );
}
