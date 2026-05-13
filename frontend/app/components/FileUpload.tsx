"use client";

import { useRef, useState } from "react";
import { uploadFile, UploadedFile } from "../../lib/api";
import { useLocale } from "../i18n/LocaleContext";

interface FileUploadProps {
  sessionId: string | null;
  onUploaded?: (file: UploadedFile) => void;
}

interface UploadDropZoneProps {
  dragging: boolean;
  uploading: boolean;
  progress: number;
  onClick: () => void;
  onDragOver: (e: React.DragEvent) => void;
  onDragLeave: () => void;
  onDrop: (e: React.DragEvent) => void;
}

function UploadDropZone({
  dragging,
  uploading,
  progress,
  onClick,
  onDragOver,
  onDragLeave,
  onDrop,
}: UploadDropZoneProps) {
  const { t } = useLocale();
  const dropZoneClassName = `flex cursor-pointer flex-col items-center justify-center gap-1 rounded border-2 border-dashed px-4 py-3 text-center transition-colors ${
    dragging
      ? "border-[#4caf50] bg-[#f5fdf5]"
      : uploading
        ? "cursor-not-allowed border-gray-200 bg-gray-50"
        : "border-gray-300 bg-white hover:border-[#4caf50] hover:bg-[#f5fdf5]"
  }`;

  return (
    <div
      onClick={onClick}
      onDragOver={onDragOver}
      onDragLeave={onDragLeave}
      onDrop={onDrop}
      className={dropZoneClassName}
    >
      <svg width="20" height="20" viewBox="0 0 20 20" fill="none" className="text-gray-400">
        <path
          d="M10 3v10M6 7l4-4 4 4"
          stroke="currentColor"
          strokeWidth="1.5"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
        <path
          d="M3 14v1a2 2 0 002 2h10a2 2 0 002-2v-1"
          stroke="currentColor"
          strokeWidth="1.5"
          strokeLinecap="round"
        />
      </svg>
      {uploading ? (
        <span className="text-xs text-gray-500">{t("upload.uploading")} {progress}%</span>
      ) : (
        <span className="text-xs text-gray-500">
          {t("upload.drop")} <span className="text-[#4caf50] font-medium">{t("upload.browse")}</span>
        </span>
      )}
    </div>
  );
}

function UploadProgressBar({ progress }: { progress: number }) {
  return (
    <div className="mt-1 h-1 w-full overflow-hidden rounded-full bg-gray-200">
      <div
        className="h-1 rounded-full bg-[#4caf50] transition-all duration-200"
        style={{ width: `${progress}%` }}
      />
    </div>
  );
}

function UploadedFileList({ files }: { files: UploadedFile[] }) {
  if (files.length === 0) return null;

  return (
    <ul className="mt-2 space-y-1">
      {files.map((f) => (
        <li key={f.gcs_path} className="flex items-center gap-1.5 text-xs text-gray-600">
          <svg width="12" height="12" viewBox="0 0 12 12" fill="none" className="shrink-0 text-[#4caf50]">
            <path d="M2 6l2.5 2.5L10 3.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
          <span className="truncate">{f.filename}</span>
        </li>
      ))}
    </ul>
  );
}

export default function FileUpload({ sessionId, onUploaded }: FileUploadProps) {
  const { t } = useLocale();
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [progress, setProgress] = useState(0);
  const [uploaded, setUploaded] = useState<UploadedFile[]>([]);
  const [error, setError] = useState<string | null>(null);

  async function handleFiles(files: FileList | null) {
    if (!files || files.length === 0) return;
    if (!sessionId) {
      setError(t("upload.no_session"));
      return;
    }

    setError(null);
    setUploading(true);
    setProgress(0);

    const file = files[0];
    try {
      const result = await uploadFile(file, sessionId, setProgress);
      const entry = { filename: result.filename, gcs_path: result.gcs_path };
      setUploaded((prev) => [...prev, entry]);
      onUploaded?.(entry);
    } catch (err) {
      setError(err instanceof Error ? err.message : t("upload.failed"));
    } finally {
      setUploading(false);
      setProgress(0);
      if (inputRef.current) inputRef.current.value = "";
    }
  }

  function onDragOver(e: React.DragEvent) {
    e.preventDefault();
    setDragging(true);
  }

  function onDragLeave() {
    setDragging(false);
  }

  function onDrop(e: React.DragEvent) {
    e.preventDefault();
    setDragging(false);
    handleFiles(e.dataTransfer.files);
  }

  return (
    <div className="mt-2">
      <UploadDropZone
        dragging={dragging}
        uploading={uploading}
        progress={progress}
        onClick={() => !uploading && inputRef.current?.click()}
        onDragOver={onDragOver}
        onDragLeave={onDragLeave}
        onDrop={onDrop}
      />

      {uploading && <UploadProgressBar progress={progress} />}
      {error && <p className="mt-1 text-xs text-red-500">{error}</p>}
      <UploadedFileList files={uploaded} />

      <input
        ref={inputRef}
        type="file"
        className="hidden"
        onChange={(e) => handleFiles(e.target.files)}
        disabled={uploading}
      />
    </div>
  );
}
