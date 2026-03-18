const AUTH_PAGE_PATHS = new Set(["/login", "/register", "/forgot-password"]);

interface RedirectLocationLike {
  pathname?: unknown;
  search?: unknown;
  hash?: unknown;
}

interface AuthRedirectState {
  from?: RedirectLocationLike;
}

export const DEFAULT_POST_AUTH_REDIRECT = "/learning-hub";

function isSafePathname(value: unknown): value is string {
  return typeof value === "string" && value.startsWith("/") && !value.startsWith("//");
}

function getOptionalSegment(value: unknown, prefix: string): string {
  if (typeof value !== "string") {
    return "";
  }
  if (!value) {
    return "";
  }
  return value.startsWith(prefix) ? value : "";
}

export function resolveAuthRedirectTarget(
  state: unknown,
  fallback = DEFAULT_POST_AUTH_REDIRECT
): string {
  if (!state || typeof state !== "object") {
    return fallback;
  }

  const from = (state as AuthRedirectState).from;
  if (!from || typeof from !== "object") {
    return fallback;
  }

  const pathname = from.pathname;
  if (!isSafePathname(pathname) || AUTH_PAGE_PATHS.has(pathname)) {
    return fallback;
  }

  const search = getOptionalSegment(from.search, "?");
  const hash = getOptionalSegment(from.hash, "#");

  return `${pathname}${search}${hash}`;
}
