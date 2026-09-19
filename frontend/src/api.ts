import type { Answer, WorkspaceSummary } from "./types";

const BASE = "/api";
const KEY = "insightsgen.session";

let sessionId: string | null = localStorage.getItem(KEY);

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, init);
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail ?? JSON.stringify(body);
    } catch {
      /* non-JSON error body */
    }
    const err = new Error(detail) as Error & { status?: number };
    err.status = res.status;
    throw err;
  }
  return (await res.json()) as T;
}

export async function createSession(): Promise<string> {
  const { session_id } = await request<{ session_id: string }>("/session", { method: "POST" });
  sessionId = session_id;
  localStorage.setItem(KEY, session_id);
  return session_id;
}

async function sid(): Promise<string> {
  return sessionId ?? (await createSession());
}

/** Run a session-scoped call; if the server forgot the session, start a fresh one and retry once. */
async function withSession<T>(fn: (id: string) => Promise<T>): Promise<T> {
  try {
    return await fn(await sid());
  } catch (e) {
    if ((e as { status?: number }).status === 404) {
      await createSession();
      return fn(sessionId!);
    }
    throw e;
  }
}

export const getSession = () => withSession((id) => request<WorkspaceSummary>(`/session/${id}`));

export const uploadFiles = (files: File[]) =>
  withSession((id) => {
    const form = new FormData();
    files.forEach((f) => form.append("files", f, f.name));
    return request<WorkspaceSummary>(`/session/${id}/files`, { method: "POST", body: form });
  });

export const loadSample = () => withSession((id) => request<WorkspaceSummary>(`/session/${id}/sample`, { method: "POST" }));

export const removeTable = (name: string) =>
  withSession((id) => request<WorkspaceSummary>(`/session/${id}/tables/${encodeURIComponent(name)}`, { method: "DELETE" }));

export const getSuggestions = () =>
  withSession(async (id) => (await request<{ questions: string[] }>(`/session/${id}/suggestions`)).questions);

export const ask = (question: string) =>
  withSession((id) =>
    request<Answer>(`/session/${id}/ask`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question }),
    }),
  );

export async function resetSession(): Promise<void> {
  if (sessionId) {
    try {
      await request(`/session/${sessionId}`, { method: "DELETE" });
    } catch {
      /* already gone */
    }
  }
  sessionId = null;
  localStorage.removeItem(KEY);
  await createSession();
}
