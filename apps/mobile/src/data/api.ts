import type { PatientContextSummary } from "@kinetic/ui-schema";
import { DATA_API_URL, RUNTIME_HEALTH_URL } from "../config/serverConfig";

/**
 * Typed REST client for the data-api (§7) + runtime health probe (§9.4).
 * No credentials — single-user local demo (§3.1). Callers never retry here:
 * transient failures are the offline queue's job (§5.6).
 */

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number | null,
  ) {
    super(message);
  }
}

async function jsonFetch<T>(url: string, init: RequestInit | undefined, timeoutMs: number): Promise<T> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const res = await fetch(url, { ...init, signal: controller.signal });
    if (!res.ok) {
      const body = await res.text().catch(() => "");
      throw new ApiError(`${init?.method ?? "GET"} ${url} → ${res.status} ${body.slice(0, 120)}`, res.status);
    }
    return (await res.json()) as T;
  } finally {
    clearTimeout(timer);
  }
}

const post = (body: unknown): RequestInit => ({
  method: "POST",
  headers: { "content-type": "application/json" },
  body: JSON.stringify(body),
});

export interface CheckinResponse {
  status: "ok" | "deduped";
  checkins?: number;
  unlock?: { n: number; label: string } | null;
}

export const api = {
  async dataHealthz(): Promise<boolean> {
    try {
      const r = await jsonFetch<{ status: string }>(`${DATA_API_URL}/healthz`, undefined, 4000);
      return r.status === "ok";
    } catch {
      return false;
    }
  },
  async runtimeHealthz(): Promise<boolean> {
    try {
      const r = await jsonFetch<{ status: string }>(RUNTIME_HEALTH_URL, undefined, 4000);
      return r.status === "ok";
    } catch {
      return false;
    }
  },
  snapshot(): Promise<PatientContextSummary> {
    return jsonFetch<PatientContextSummary>(`${DATA_API_URL}/me/snapshot`, undefined, 8000);
  },
  checkin(answer: string, eventId: string, doseAt?: string): Promise<CheckinResponse> {
    return jsonFetch<CheckinResponse>(
      `${DATA_API_URL}/me/checkins`,
      post({ answer, eventId, doseAt }),
      8000,
    );
  },
  answerQuestion(value: string, eventId: string): Promise<{ status: string }> {
    return jsonFetch(`${DATA_API_URL}/me/answers`, post({ kind: "question", value, eventId }), 8000);
  },
  answerTemperature(value: string, eventId: string): Promise<{ status: string }> {
    return jsonFetch(`${DATA_API_URL}/me/answers`, post({ kind: "temperature", value, eventId }), 8000);
  },
  answerVomit(value: string, eventId: string): Promise<{ status: string }> {
    return jsonFetch(`${DATA_API_URL}/me/answers`, post({ kind: "vomit", value, eventId }), 8000);
  },
  confirmSymptoms(labels: string[], transcript: string | undefined, eventId: string): Promise<{ status: string }> {
    return jsonFetch(`${DATA_API_URL}/me/answers`, post({ kind: "symptoms", labels, transcript, eventId }), 8000);
  },
  shareDiary(text: string, noted: string[], eventId: string): Promise<{ status: string }> {
    return jsonFetch(`${DATA_API_URL}/me/answers`, post({ kind: "diary", text, noted, eventId }), 8000);
  },
  sendHandoff(text: string, transcript: string | undefined, eventId: string): Promise<{ status: string }> {
    return jsonFetch(`${DATA_API_URL}/me/handoffs`, post({ text, transcript, eventId }), 8000);
  },
  ackReminder(id: string, eventId: string): Promise<{ status: string }> {
    return jsonFetch(`${DATA_API_URL}/me/reminders/${id}/ack`, post({ eventId }), 8000);
  },
  // Dev-only demo harness (§5.5): reseed the backend into a scenario state.
  scenario(
    name: "morning" | "question" | "badge" | "clear" | "health" | "sick" | "diary",
  ): Promise<{ status: string }> {
    return jsonFetch(`${DATA_API_URL}/dev/scenario/${name}`, post({}), 8000);
  },
};