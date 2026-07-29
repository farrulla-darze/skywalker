// Minimal fetch wrapper: JWT injection + 401 handling.

const TOKEN_KEY = "skywalker_token";

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string | null) {
  if (token) localStorage.setItem(TOKEN_KEY, token);
  else localStorage.removeItem(TOKEN_KEY);
}

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

export async function api<T>(
  path: string,
  options: { method?: string; body?: unknown } = {},
): Promise<T> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  const token = getToken();
  if (token) headers["Authorization"] = `Bearer ${token}`;

  const response = await fetch(path, {
    method: options.method ?? "GET",
    headers,
    body: options.body !== undefined ? JSON.stringify(options.body) : undefined,
  });

  if (response.status === 401) {
    setToken(null);
    window.dispatchEvent(new Event("skywalker:unauthorized"));
  }
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const data = await response.json();
      detail = typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail);
    } catch {
      /* keep statusText */
    }
    throw new ApiError(response.status, detail);
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export interface StreamEvent {
  type:
    | "step_started"
    | "step_finished"
    | "token"
    | "revised"
    | "consultation"
    | "ping"
    | "done"
    | "error";
  [key: string]: unknown;
}

/** POST to an SSE endpoint and yield parsed events (fetch-based; EventSource can't POST). */
export async function* apiStream(
  path: string,
  body: unknown,
): AsyncGenerator<StreamEvent> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  const token = getToken();
  if (token) headers["Authorization"] = `Bearer ${token}`;

  const response = await fetch(path, {
    method: "POST",
    headers,
    body: JSON.stringify(body),
  });
  if (!response.ok || !response.body) {
    throw new ApiError(response.status, response.statusText);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const parts = buffer.split("\n\n");
    buffer = parts.pop() ?? "";
    for (const part of parts) {
      const line = part.trim();
      if (line.startsWith("data: ")) {
        yield JSON.parse(line.slice(6)) as StreamEvent;
      }
    }
  }
}
