"use client";

import { useRef, useState } from "react";
import { type UploadedFile, uploadFile } from "../../lib/api";
import { useLocale } from "../i18n/LocaleContext";

interface FileUploadProps {
	sessionId: string | null;
	onUploaded?: (file: UploadedFile) => void;
	onError: (message: string) => void;
	/** Called when no session exists yet; must create one and return the new session ID. */
	onEnsureSession?: () => string;
}

interface UploadDropZoneProps {
	dragging: boolean;
	onClick: () => void;
	onDragOver: (e: React.DragEvent) => void;
	onDragLeave: () => void;
	onDrop: (e: React.DragEvent) => void;
}

function UploadDropZone({
	dragging,
	onClick,
	onDragOver,
	onDragLeave,
	onDrop,
}: UploadDropZoneProps) {
	const { t } = useLocale();
	const dropZoneClassName = `flex cursor-pointer flex-col items-center justify-center gap-1 rounded border-2 border-dashed px-4 py-3 text-center transition-colors ${
		dragging
			? "border-[#4caf50] bg-[#f5fdf5]"
			: "border-gray-300 bg-white hover:border-[#4caf50] hover:bg-[#f5fdf5]"
	}`;

	return (
		<div
			role="button"
			tabIndex={0}
			onClick={onClick}
			onKeyDown={(e) => {
				if (e.key === "Enter" || e.key === " ") {
					e.preventDefault();
					onClick();
				}
			}}
			onDragOver={onDragOver}
			onDragLeave={onDragLeave}
			onDrop={onDrop}
			className={dropZoneClassName}
		>
			<svg
				aria-hidden="true"
				width="20"
				height="20"
				viewBox="0 0 20 20"
				fill="none"
				className="text-gray-400"
			>
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
			<span className="text-xs text-gray-500">
				{t("upload.drop")}{" "}
				<span className="text-[#4caf50] font-medium">{t("upload.browse")}</span>
			</span>
		</div>
	);
}

function UploadProgressBar({
	filename,
	progress,
}: {
	filename: string;
	progress: number;
}) {
	const { t } = useLocale();
	return (
		<div className="mt-2">
			<p className="truncate text-xs text-gray-500">
				{t("upload.uploading")} {filename} {progress}%
			</p>
			<div className="mt-1 h-1 w-full overflow-hidden rounded-full bg-gray-200">
				<div
					className="h-1 rounded-full bg-[#4caf50] transition-all duration-200"
					style={{ width: `${progress}%` }}
				/>
			</div>
		</div>
	);
}

function AddMoreButton({
	dragging,
	onClick,
	onDragOver,
	onDragLeave,
	onDrop,
}: UploadDropZoneProps) {
	const { t } = useLocale();
	return (
		<button
			type="button"
			onClick={onClick}
			onDragOver={onDragOver}
			onDragLeave={onDragLeave}
			onDrop={onDrop}
			className={`mt-3 flex w-full items-center justify-center gap-1.5 rounded border border-dashed px-3 py-2 text-xs font-semibold transition-colors ${
				dragging
					? "border-[#4caf50] bg-[#f5fdf5] text-[#1a3a2a]"
					: "border-gray-300 text-gray-600 hover:border-[#4caf50] hover:text-[#1a3a2a]"
			}`}
		>
			<span aria-hidden="true" className="text-base leading-none">
				+
			</span>
			{t("upload.add_more")}
		</button>
	);
}

function UploadedFileList({ files }: { files: UploadedFile[] }) {
	if (files.length === 0) return null;

	return (
		<ul className="space-y-1">
			{files.map((f, i) => (
				<li
					// The same file can be attached twice, so the path alone is not unique.
					key={`${i}-${f.gcs_path}`}
					className="flex items-center gap-1.5 text-xs text-gray-600"
				>
					<svg
						aria-hidden="true"
						width="12"
						height="12"
						viewBox="0 0 12 12"
						fill="none"
						className="shrink-0 text-[#4caf50]"
					>
						<path
							d="M2 6l2.5 2.5L10 3.5"
							stroke="currentColor"
							strokeWidth="1.5"
							strokeLinecap="round"
							strokeLinejoin="round"
						/>
					</svg>
					<span className="truncate">{f.filename}</span>
				</li>
			))}
		</ul>
	);
}

export default function FileUpload({
	sessionId,
	onUploaded,
	onError,
	onEnsureSession,
}: FileUploadProps) {
	const { t } = useLocale();
	const inputRef = useRef<HTMLInputElement>(null);
	const [dragging, setDragging] = useState(false);
	const [current, setCurrent] = useState<string | null>(null);
	const [progress, setProgress] = useState(0);
	const [uploaded, setUploaded] = useState<UploadedFile[]>([]);
	const uploading = current !== null;

	async function handleFiles(fileList: FileList | null) {
		const files = [...(fileList ?? [])];
		if (files.length === 0) return;

		const sid = sessionId ?? onEnsureSession?.();
		if (!sid) {
			onError(t("upload.no_session"));
			return;
		}

		// One at a time, so each file gets its own progress and a failure
		// does not stop the rest of the selection.
		for (const file of files) {
			setCurrent(file.name);
			setProgress(0);
			try {
				const result = await uploadFile(file, sid, setProgress);
				const entry = {
					filename: result.filename,
					gcs_path: result.gcs_path,
					sessionId: sid,
				};
				setUploaded((prev) => [...prev, entry]);
				onUploaded?.(entry);
			} catch (err) {
				const reason = err instanceof Error ? err.message : t("upload.failed");
				onError(`${file.name}: ${reason}`);
			}
		}
		setCurrent(null);
		setProgress(0);
		if (inputRef.current) inputRef.current.value = "";
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

	const openPicker = () => !uploading && inputRef.current?.click();
	const dropHandlers = { onDragOver, onDragLeave, onDrop };

	return (
		<div className="mt-2">
			{uploaded.length === 0 && !uploading && (
				<UploadDropZone
					dragging={dragging}
					onClick={openPicker}
					{...dropHandlers}
				/>
			)}
			<UploadedFileList files={uploaded} />

			{current !== null && (
				<UploadProgressBar filename={current} progress={progress} />
			)}
			{uploaded.length > 0 && !uploading && (
				<AddMoreButton
					dragging={dragging}
					onClick={openPicker}
					{...dropHandlers}
				/>
			)}

			<input
				ref={inputRef}
				type="file"
				multiple
				className="hidden"
				onChange={(e) => handleFiles(e.target.files)}
				disabled={uploading}
			/>
		</div>
	);
}
