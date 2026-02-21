import { apiFetch } from "../api/http";
import { Attachment, UploadBatchResponse } from "../api/types";

export interface PreparedSendPayload {
  cleanedContent: string;
  displayContent: string;
  uploadIds: string[];
  attachments: Attachment[];
}

export async function prepareSendPayload(
  content: string,
  files: File[]
): Promise<PreparedSendPayload> {
  const cleanedContent = content.trim();

  let attachments: Attachment[] = [];
  if (files.length > 0) {
    const formData = new FormData();
    for (const file of files) {
      formData.append("files", file);
    }

    const uploadResponse = await apiFetch<UploadBatchResponse>("/api/upload", {
      method: "POST",
      body: formData,
    });
    attachments = uploadResponse.files;
  }

  return {
    cleanedContent,
    displayContent:
      cleanedContent || (attachments.length > 0 ? "Sent attachments." : ""),
    uploadIds: attachments.map((item) => item.id),
    attachments,
  };
}
