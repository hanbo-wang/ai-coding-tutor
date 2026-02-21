let accessToken: string | null = null;

type ResponseKind = "json" | "blob";

export function setAccessToken(token: string | null) {
  accessToken = token;
}

export function getAccessToken(): string | null {
  return accessToken;
}

function isAuthEndpoint(path: string): boolean {
  return (
    path.startsWith("/api/auth/login") ||
    path.startsWith("/api/auth/register") ||
    path.startsWith("/api/auth/refresh")
  );
}

function buildRequestHeaders(options: RequestInit): Headers {
  const headers = new Headers(options.headers);
  if (accessToken) {
    headers.set("Authorization", `Bearer ${accessToken}`);
  }
  const isFormDataBody =
    typeof FormData !== "undefined" && options.body instanceof FormData;
  if (!headers.has("Content-Type") && options.body && !isFormDataBody) {
    headers.set("Content-Type", "application/json");
  }
  return headers;
}

async function fetchWithAuth(
  path: string,
  options: RequestInit,
  headers: Headers
): Promise<Response> {
  return fetch(path, {
    ...options,
    headers,
    credentials: "include",
  });
}

async function parseApiError(response: Response): Promise<string> {
  const contentType = response.headers.get("content-type") || "";
  if (contentType.includes("application/json")) {
    const error = await response.json().catch(() => ({ detail: "Unknown error" }));
    if (error && typeof error.detail === "string") {
      return error.detail;
    }
  }

  const fallbackText = await response.text().catch(() => "");
  if (fallbackText) {
    return fallbackText;
  }
  return `API error: ${response.status}`;
}

async function parseSuccess<T>(response: Response, kind: ResponseKind): Promise<T> {
  if (kind === "blob") {
    return (await response.blob()) as T;
  }

  const text = await response.text();
  if (!text) {
    return {} as T;
  }
  return JSON.parse(text) as T;
}

async function request<T>(
  path: string,
  options: RequestInit,
  kind: ResponseKind
): Promise<T> {
  const headers = buildRequestHeaders(options);
  let response = await fetchWithAuth(path, options, headers);

  if (response.status === 401 && !isAuthEndpoint(path)) {
    const refreshed = await refreshAccessToken();
    if (!refreshed) {
      window.location.href = "/login";
      throw new Error("Session expired");
    }

    headers.set("Authorization", `Bearer ${accessToken}`);
    response = await fetchWithAuth(path, options, headers);
  }

  if (!response.ok) {
    throw new Error(await parseApiError(response));
  }

  return parseSuccess<T>(response, kind);
}

export async function apiFetch<T>(
  path: string,
  options: RequestInit = {}
): Promise<T> {
  return request<T>(path, options, "json");
}

export async function apiFetchBlob(
  path: string,
  options: RequestInit = {}
): Promise<Blob> {
  return request<Blob>(path, options, "blob");
}

async function refreshAccessToken(): Promise<boolean> {
  try {
    const response = await fetch("/api/auth/refresh", {
      method: "POST",
      credentials: "include",
    });
    if (!response.ok) {
      return false;
    }
    const data = await response.json();
    setAccessToken(data.access_token);
    return true;
  } catch {
    return false;
  }
}
