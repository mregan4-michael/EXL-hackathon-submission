import type { DemoUser, Evaluation, Json, Row } from "./types";

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly detail: string,
    readonly correlationId: string | null,
  ) {
    super(`${status}: ${detail}`);
  }
}

async function call<T>(user: string | null, path: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    "X-Correlation-ID": crypto.randomUUID(),
  };
  if (user) headers["X-Demo-User"] = user;
  const init: RequestInit = { method: body === undefined ? "GET" : "POST", headers };
  if (body !== undefined) init.body = JSON.stringify(body);
  const res = await fetch(path, init);
  const text = await res.text();
  if (!res.ok) {
    let detail = text;
    try {
      const p = JSON.parse(text) as { detail?: string; title?: string; errors?: unknown };
      detail = p.detail ?? (p.errors ? JSON.stringify(p.errors) : (p.title ?? text));
    } catch {
      /* plain-text error body */
    }
    throw new ApiError(res.status, detail, res.headers.get("X-Correlation-ID"));
  }
  return (text ? JSON.parse(text) : null) as T;
}

export const api = {
  users: () => call<DemoUser[]>(null, "/api/demo/users"),
  list: (user: string, entitySet: string) => call<Row[]>(user, `/api/${entitySet}`),
  evaluate: (user: string, screen: string, inputs: Record<string, Json>) =>
    call<Evaluation>(user, `/api/screens/${screen}/evaluate`, { inputs }),
  act: (
    user: string,
    screen: string,
    control: string,
    inputs: Record<string, Json>,
    context: Record<string, Json>,
    rowId: string | null,
  ) =>
    call<{ record: Row; navigateTo: string[] }>(
      user,
      `/api/screens/${screen}/actions/${control}`,
      { inputs, context, rowId },
    ),
};
