export interface User {
  id: string;
  email: string;
  username: string;
  programming_level: number;
  maths_level: number;
  is_admin: boolean;
  created_at: string;
}

export interface TokenResponse {
  access_token: string;
  token_type: string;
}

export interface LoginCredentials {
  email: string;
  password: string;
}

export interface RegisterData {
  email: string;
  username: string;
  password: string;
  programming_level?: number;
  maths_level?: number;
}

export interface ProfileUpdateData {
  username?: string;
  programming_level?: number;
  maths_level?: number;
}

export interface ChangePasswordData {
  current_password: string;
  new_password: string;
}

export interface ChatMessage {
  id?: string;
  role: "user" | "assistant";
  content: string;
  attachments?: Attachment[];
  hint_level_used?: number;
  problem_difficulty?: number;
  maths_difficulty?: number;
  created_at?: string;
}

export interface ChatSession {
  id: string;
  preview: string;
  created_at: string;
}

export interface TokenUsage {
  week_start: string;
  week_end: string;
  input_tokens_used: number;
  output_tokens_used: number;
  weighted_tokens_used: number;
  remaining_weighted_tokens: number;
  weekly_weighted_limit: number;
  usage_percentage: number;
}

export interface Attachment {
  id: string;
  filename: string;
  content_type: string;
  file_type: "image" | "document";
  url: string;
}

export interface UploadBatchResponse {
  files: Attachment[];
}

export interface UploadLimits {
  max_images: number;
  max_documents: number;
  max_image_bytes: number;
  max_document_bytes: number;
  image_extensions: string[];
  document_extensions: string[];
  accept_extensions: string[];
}

export interface NotebookSummary {
  id: string;
  title: string;
  original_filename: string;
  size_bytes: number;
  created_at: string;
}

export interface NotebookDetail extends NotebookSummary {
  notebook_json: Record<string, unknown>;
}

export interface LearningZone {
  id: string;
  title: string;
  description: string | null;
  order: number;
  created_at: string;
  notebook_count: number;
}

export interface ZoneNotebook {
  id: string;
  zone_id: string;
  title: string;
  description?: string | null;
  original_filename: string;
  size_bytes: number;
  order: number;
  created_at: string;
  has_progress: boolean;
}

export interface ZoneDetail extends LearningZone {
  notebooks: ZoneNotebook[];
}

export interface ZoneNotebookDetail extends ZoneNotebook {
  notebook_json: Record<string, unknown>;
}

export interface ZoneSharedFile {
  id: string;
  zone_id: string;
  relative_path: string;
  original_filename: string;
  content_type: string | null;
  size_bytes: number;
  created_at: string;
  updated_at: string;
}

export interface ZoneRuntimeFile {
  relative_path: string;
  content_base64: string;
  content_type: string | null;
}

export interface ZoneImportResult {
  notebooks_created: number;
  shared_files_created: number;
  shared_files_updated: number;
}

export interface ScopedChatSession {
  id: string;
  session_type: "notebook" | "zone";
  module_id: string | null;
  created_at: string | null;
}

export interface AdminUsagePeriod {
  input_tokens: number;
  output_tokens: number;
  estimated_cost_usd: number;
}

export interface AdminUsage {
  today: AdminUsagePeriod;
  this_week: AdminUsagePeriod;
  this_month: AdminUsagePeriod;
}

export interface AuditLogEntry {
  id: string;
  admin_email: string;
  action: string;
  resource_type: string;
  resource_id: string | null;
  resource_title: string | null;
  details: string | null;
  created_at: string | null;
}

export interface AuditLogResponse {
  entries: AuditLogEntry[];
  total: number;
  page: number;
  per_page: number;
  total_pages: number;
}

export interface HealthModelProviderStatus {
  configured: boolean;
  reason?: string;
  transport?: string;
  checked_models: Record<string, boolean>;
  available_models: string[];
}

export interface HealthModelSnapshot {
  provider: string;
  model: string;
  google_gemini_transport?: string;
}

export interface HealthCurrentModels {
  llm_provider: string;
  google_gemini_transport: string;
  llm_models: Record<string, string>;
  active_llm: HealthModelSnapshot;
  embedding_provider: string;
  embedding_models: Record<string, string>;
  active_embedding: HealthModelSnapshot;
}

export interface HealthModelSmokeResults {
  llm: Record<string, HealthModelProviderStatus>;
  embeddings: Record<string, HealthModelProviderStatus>;
}

export interface HealthModelsResponse {
  current: HealthCurrentModels;
  smoke_tested_models: HealthModelSmokeResults;
  cached: boolean;
  checked_at: string;
}
