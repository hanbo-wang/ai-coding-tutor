import {
  ClipboardEvent,
  ChangeEvent,
  DragEvent,
  FormEvent,
  KeyboardEvent,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { apiFetch } from "../api/http";
import type { UploadLimits } from "../api/types";

interface ChatInputProps {
  onSend: (message: string, files: File[]) => Promise<void> | void;
  disabled: boolean;
}

interface PendingAttachment {
  id: string;
  file: File;
  previewUrl: string | null;
}

const DEFAULT_UPLOAD_LIMITS: UploadLimits = {
  max_images: 3,
  max_documents: 2,
  max_image_bytes: 5 * 1024 * 1024,
  max_document_bytes: 2 * 1024 * 1024,
  image_extensions: [".png", ".jpg", ".jpeg", ".gif", ".webp"],
  document_extensions: [".pdf", ".txt", ".py", ".js", ".ts", ".csv", ".ipynb"],
  accept_extensions: [
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".pdf",
    ".txt",
    ".py",
    ".js",
    ".ts",
    ".csv",
    ".ipynb",
  ],
};
const IMAGE_MIME_TO_EXTENSION: Record<string, string> = {
  "image/png": ".png",
  "image/jpeg": ".jpg",
  "image/gif": ".gif",
  "image/webp": ".webp",
};
const DOCUMENT_MIME_TO_EXTENSION: Record<string, string> = {
  "application/pdf": ".pdf",
  "text/plain": ".txt",
  "text/x-python": ".py",
  "application/javascript": ".js",
  "text/javascript": ".js",
  "application/typescript": ".ts",
  "text/typescript": ".ts",
  "text/csv": ".csv",
  "application/x-ipynb+json": ".ipynb",
};
function normaliseExtensions(extensions: string[]): string[] {
  return extensions
    .map((extension) => {
      const trimmed = extension.trim().toLowerCase();
      if (!trimmed) return "";
      return trimmed.startsWith(".") ? trimmed : `.${trimmed}`;
    })
    .filter((extension): extension is string => extension.length > 0);
}

function normaliseUploadLimits(limits: UploadLimits): UploadLimits {
  const imageExtensions = normaliseExtensions(limits.image_extensions);
  const documentExtensions = normaliseExtensions(limits.document_extensions);
  const acceptExtensions = normaliseExtensions(limits.accept_extensions);
  return {
    ...limits,
    image_extensions: imageExtensions,
    document_extensions: documentExtensions,
    accept_extensions:
      acceptExtensions.length > 0
        ? acceptExtensions
        : [...new Set([...imageExtensions, ...documentExtensions])],
  };
}

function getFileKind(
  file: File,
  imageExtensionSet: Set<string>,
  documentExtensionSet: Set<string>
): "image" | "document" | "unsupported" {
  const ext = extensionOf(file.name);
  if (imageExtensionSet.has(ext)) return "image";
  if (documentExtensionSet.has(ext)) return "document";
  const mime = normaliseMimeType(file.type);
  if (mime in IMAGE_MIME_TO_EXTENSION) return "image";
  if (mime in DOCUMENT_MIME_TO_EXTENSION) return "document";
  return "unsupported";
}

function extensionOf(filename: string): string {
  const idx = filename.lastIndexOf(".");
  if (idx < 0) return "";
  return filename.slice(idx).toLowerCase();
}

function normaliseMimeType(mimeType: string): string {
  return mimeType.split(";")[0].trim().toLowerCase();
}

function normaliseIncomingFile(file: File, index: number): File {
  if (extensionOf(file.name)) {
    return file;
  }

  const mime = normaliseMimeType(file.type);
  const guessedExtension =
    IMAGE_MIME_TO_EXTENSION[mime] ?? DOCUMENT_MIME_TO_EXTENSION[mime];
  if (!guessedExtension) {
    return file;
  }

  const timestamp = Date.now();
  const fallbackBaseName =
    mime in IMAGE_MIME_TO_EXTENSION
      ? `pasted-image-${timestamp}-${index + 1}`
      : `attachment-${timestamp}-${index + 1}`;
  const nextName = `${file.name || fallbackBaseName}${guessedExtension}`;
  const nextType = file.type || mime || "application/octet-stream";
  return new File([file], nextName, {
    type: nextType,
    lastModified: file.lastModified,
  });
}

function validateFile(
  file: File,
  limits: UploadLimits,
  imageExtensionSet: Set<string>,
  documentExtensionSet: Set<string>
): string | null {
  const fileKind = getFileKind(file, imageExtensionSet, documentExtensionSet);
  if (fileKind === "image") {
    if (file.size > limits.max_image_bytes) {
      return `File "${file.name}" is too large.`;
    }
    return null;
  }

  if (fileKind === "document") {
    if (file.size > limits.max_document_bytes) {
      return `File "${file.name}" is too large.`;
    }
    return null;
  }

  return `Unsupported file type: ${file.name}.`;
}

function createAttachment(
  file: File,
  imageExtensionSet: Set<string>,
  documentExtensionSet: Set<string>
): PendingAttachment {
  const isImage = getFileKind(file, imageExtensionSet, documentExtensionSet) === "image";
  return {
    id: `${file.name}-${file.size}-${Math.random().toString(36).slice(2, 10)}`,
    file,
    previewUrl: isImage ? URL.createObjectURL(file) : null,
  };
}

export function ChatInput({ onSend, disabled }: ChatInputProps) {
  const [text, setText] = useState("");
  const [attachments, setAttachments] = useState<PendingAttachment[]>([]);
  const [error, setError] = useState("");
  const [uploadLimits, setUploadLimits] = useState<UploadLimits>(DEFAULT_UPLOAD_LIMITS);
  const [isSending, setIsSending] = useState(false);
  const [isDragging, setIsDragging] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const attachmentsRef = useRef<PendingAttachment[]>([]);
  const imageExtensionSet = useMemo(
    () => new Set(uploadLimits.image_extensions),
    [uploadLimits.image_extensions]
  );
  const documentExtensionSet = useMemo(
    () => new Set(uploadLimits.document_extensions),
    [uploadLimits.document_extensions]
  );
  const maxTotalFiles = uploadLimits.max_images + uploadLimits.max_documents;
  const uploadLimitLabel = `${uploadLimits.max_images} photos and ${uploadLimits.max_documents} files`;

  const effectiveDisabled = disabled || isSending;
  const canSend = useMemo(
    () => text.trim().length > 0 || attachments.length > 0,
    [text, attachments]
  );

  useEffect(() => {
    attachmentsRef.current = attachments;
  }, [attachments]);

  useEffect(() => {
    let cancelled = false;
    void apiFetch<UploadLimits>("/api/upload/limits")
      .then((limits) => {
        if (!cancelled) {
          setUploadLimits(normaliseUploadLimits(limits));
        }
      })
      .catch(() => {
        // Keep local defaults if backend limits cannot be fetched.
      });

    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    return () => {
      for (const attachment of attachmentsRef.current) {
        if (attachment.previewUrl) {
          URL.revokeObjectURL(attachment.previewUrl);
        }
      }
    };
  }, []);

  const addFiles = (incomingFiles: File[]) => {
    if (incomingFiles.length === 0) return;
    setError("");
    const files = incomingFiles.map((file, index) =>
      normaliseIncomingFile(file, index)
    );

    let imageCount = attachments.filter(
      (item) => getFileKind(item.file, imageExtensionSet, documentExtensionSet) === "image"
    ).length;
    let documentCount = attachments.filter(
      (item) => getFileKind(item.file, imageExtensionSet, documentExtensionSet) === "document"
    ).length;

    const newAttachments: PendingAttachment[] = [];
    for (const file of files) {
      const validationError = validateFile(
        file,
        uploadLimits,
        imageExtensionSet,
        documentExtensionSet
      );
      if (validationError) {
        setError(validationError);
        for (const item of newAttachments) {
          if (item.previewUrl) URL.revokeObjectURL(item.previewUrl);
        }
        return;
      }

      const kind = getFileKind(file, imageExtensionSet, documentExtensionSet);
      if (kind === "image") {
        imageCount += 1;
      } else if (kind === "document") {
        documentCount += 1;
      }
      if (imageCount > uploadLimits.max_images || documentCount > uploadLimits.max_documents) {
        setError(
          `Too many files. You can upload up to ${uploadLimitLabel} per message.`
        );
        for (const item of newAttachments) {
          if (item.previewUrl) URL.revokeObjectURL(item.previewUrl);
        }
        return;
      }
      newAttachments.push(
        createAttachment(file, imageExtensionSet, documentExtensionSet)
      );
    }

    if (attachments.length + newAttachments.length > maxTotalFiles) {
      setError(
        `Too many files. You can upload up to ${uploadLimitLabel} per message.`
      );
      for (const item of newAttachments) {
        if (item.previewUrl) URL.revokeObjectURL(item.previewUrl);
      }
      return;
    }

    setAttachments((prev) => [...prev, ...newAttachments]);
  };

  const removeAttachment = (id: string) => {
    setAttachments((prev) => {
      const found = prev.find((item) => item.id === id);
      if (found?.previewUrl) {
        URL.revokeObjectURL(found.previewUrl);
      }
      return prev.filter((item) => item.id !== id);
    });
  };

  const resetAfterSend = () => {
    setText("");
    setError("");
    setAttachments((prev) => {
      for (const item of prev) {
        if (item.previewUrl) URL.revokeObjectURL(item.previewUrl);
      }
      return [];
    });
    if (textareaRef.current) {
      textareaRef.current.style.height = "auto";
    }
    if (fileInputRef.current) {
      fileInputRef.current.value = "";
    }
  };

  const handleSubmit = async (e?: FormEvent) => {
    e?.preventDefault();
    if (!canSend || effectiveDisabled) return;

    try {
      setIsSending(true);
      await onSend(
        text.trim(),
        attachments.map((item) => item.file)
      );
      resetAfterSend();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to send message.");
    } finally {
      setIsSending(false);
    }
  };

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      void handleSubmit();
    }
  };

  const handleInput = () => {
    if (textareaRef.current) {
      textareaRef.current.style.height = "auto";
      textareaRef.current.style.height = `${Math.min(
        textareaRef.current.scrollHeight,
        200
      )}px`;
    }
  };

  const handleFileInputChange = (e: ChangeEvent<HTMLInputElement>) => {
    const selectedFiles = Array.from(e.target.files ?? []);
    addFiles(selectedFiles);
  };

  const handleDragOver = (e: DragEvent<HTMLFormElement>) => {
    e.preventDefault();
    setIsDragging(true);
  };

  const handleDragLeave = (e: DragEvent<HTMLFormElement>) => {
    e.preventDefault();
    if (e.currentTarget === e.target) {
      setIsDragging(false);
    }
  };

  const handleDrop = (e: DragEvent<HTMLFormElement>) => {
    e.preventDefault();
    setIsDragging(false);
    if (effectiveDisabled) return;
    const droppedFiles = Array.from(e.dataTransfer.files ?? []);
    addFiles(droppedFiles);
  };

  const handlePaste = (e: ClipboardEvent<HTMLTextAreaElement>) => {
    if (effectiveDisabled) return;

    // Support quick screenshot paste from clipboard.
    const clipboardFiles: File[] = [];
    for (const item of Array.from(e.clipboardData.items)) {
      if (item.kind === "file" && item.type.startsWith("image/")) {
        const file = item.getAsFile();
        if (file) clipboardFiles.push(file);
      }
    }
    if (clipboardFiles.length > 0) {
      addFiles(clipboardFiles);
    }
  };

  return (
    <form
      onSubmit={handleSubmit}
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
      className={`border-t border-gray-200 p-4 bg-white ${
        isDragging ? "ring-2 ring-accent ring-inset" : ""
      }`}
    >
      {attachments.length > 0 && (
        <div className="mb-3 flex flex-wrap gap-2">
          {attachments.map((attachment) => {
            const isImage = attachment.previewUrl !== null;
            return (
              <div
                key={attachment.id}
                className="relative rounded-md border border-gray-200 bg-gray-50 p-2 pr-7"
              >
                {isImage ? (
                  <img
                    src={attachment.previewUrl ?? ""}
                    alt={attachment.file.name}
                    className="h-16 w-20 rounded object-cover"
                  />
                ) : (
                  <p className="text-xs text-gray-700 max-w-[180px] truncate">
                    {attachment.file.name}
                  </p>
                )}
                <button
                  type="button"
                  onClick={() => removeAttachment(attachment.id)}
                  className="absolute right-1 top-1 text-gray-400 hover:text-gray-700"
                  aria-label="Remove attachment"
                >
                  ×
                </button>
              </div>
            );
          })}
        </div>
      )}

      <div className="flex items-end gap-3">
        <input
          ref={fileInputRef}
          type="file"
          multiple
          onChange={handleFileInputChange}
          className="hidden"
          accept={uploadLimits.accept_extensions.join(",")}
        />
        <button
          type="button"
          onClick={() => fileInputRef.current?.click()}
          disabled={effectiveDisabled || attachments.length >= maxTotalFiles}
          className="h-10 w-10 rounded-lg border border-gray-300 text-gray-600 hover:bg-gray-100 disabled:opacity-50"
          title="Attach files"
        >
          <svg
            className="mx-auto h-5 w-5"
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={2}
              d="M15.172 7l-6.586 6.586a2 2 0 102.828 2.828L18 9.828a4 4 0 10-5.656-5.656L5.757 10.76a6 6 0 108.486 8.486L20.5 13"
            />
          </svg>
        </button>

        <textarea
          ref={textareaRef}
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={handleKeyDown}
          onInput={handleInput}
          onPaste={handlePaste}
          placeholder="Ask a question..."
          rows={1}
          disabled={effectiveDisabled}
          className="flex-1 resize-none border border-gray-300 rounded-lg px-4 py-2.5 focus:outline-none focus:ring-2 focus:ring-accent disabled:opacity-50"
        />

        <button
          type="submit"
          disabled={effectiveDisabled || !canSend}
          className="bg-accent text-brand font-medium px-5 py-2.5 rounded-lg hover:bg-accent-dark focus:outline-none focus:ring-2 focus:ring-accent disabled:opacity-50 whitespace-nowrap"
        >
          {isSending ? "Sending..." : "Send"}
        </button>
      </div>

      {error && <p className="mt-2 text-sm text-red-600">{error}</p>}
    </form>
  );
}
