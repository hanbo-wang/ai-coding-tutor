import { useEffect } from "react";

interface UserNoticeDialogProps {
  isOpen: boolean;
  onClose: () => void;
}

export function UserNoticeDialog({
  isOpen,
  onClose,
}: UserNoticeDialogProps) {
  useEffect(() => {
    if (!isOpen) {
      return;
    }

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        onClose();
      }
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [isOpen, onClose]);

  if (!isOpen) {
    return null;
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/60 p-4"
      onClick={onClose}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="user-notice-title"
        className="max-h-[90vh] w-full max-w-2xl overflow-y-auto rounded-xl bg-white shadow-2xl"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="flex items-start justify-between gap-4 border-b border-gray-200 px-6 py-4">
          <div>
            <h2 id="user-notice-title" className="text-lg font-bold text-brand">
              User Notice
            </h2>
            <p className="mt-1 text-sm text-gray-600">
              Important information about using Guided Cursor.
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-md border border-gray-300 px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-50"
          >
            Close
          </button>
        </div>

        <div className="space-y-4 px-6 py-5 text-sm leading-6 text-gray-700">
          <p>
            Welcome to <strong>Guided Cursor</strong>, an AI-powered platform
            designed to guide you through programming problems step by step. As
            with all AI systems, responses may not always be perfectly accurate.
            You are encouraged to think critically and verify all output
            independently.
          </p>
          <p>
            <strong>Privacy.</strong> We may collect anonymised usage data to
            improve the platform and support academic research into AI-assisted
            pedagogy. No data will be shared outside the project team. Your
            usage and performance will <strong>not</strong> be disclosed to
            module leaders and will have <strong>no bearing</strong> on your
            academic grades.
          </p>
          <p>
            <strong>Data Retention.</strong> This platform may be taken offline
            at the end of the academic term, and all stored data may be
            permanently deleted. Please back up any materials you wish to keep
            in advance.
          </p>
          <p>
            <strong>Contact.</strong> For any questions or concerns, please
            reach out to{" "}
            <a
              href="mailto:hello@guidedcursor.studio"
              className="font-medium text-accent-dark hover:underline"
            >
              hello@guidedcursor.studio
            </a>
            .
          </p>
        </div>
      </div>
    </div>
  );
}
