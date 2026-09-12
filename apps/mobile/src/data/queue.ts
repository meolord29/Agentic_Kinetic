import { createMMKV } from "react-native-mmkv";
import type { PatientContextSummary } from "@kinetic/ui-schema";

/**
 * §5.6 offline queue — the data-api is an eventually-reachable authority.
 * Every committed answer enqueues with a client eventId the moment the user
 * commits it; the UI advances on optimistic state; a flush loop retries with
 * backoff and the server dedups on eventId, so retries are safe.
 *
 * P1 storage: default MMKV instance (§5.7 ledger — MMKV is the settled
 * localStorage translation; an encrypted instance joins when tokens do).
 */
export const storage = createMMKV({ id: "kinetic.default" });

const QUEUE_KEY = "kinetic.queue.v1";
const SNAPSHOT_KEY = "kinetic.snapshot.v1";

export type Endpoint = "/me/checkins" | "/me/answers" | "/me/reminders/ack" | "/me/handoffs";

export interface QueueItem {
  eventId: string;
  endpoint: Endpoint;
  /** Reminder id for the ack endpoint. */
  reminderId?: string;
  payload: Record<string, unknown>;
  queuedAt: number;
}

export function getQueue(): QueueItem[] {
  const raw = storage.getString(QUEUE_KEY);
  if (!raw) return [];
  try {
    return JSON.parse(raw) as QueueItem[];
  } catch {
    return [];
  }
}

export function setQueue(items: QueueItem[]): void {
  storage.set(QUEUE_KEY, JSON.stringify(items));
}

export function enqueue(item: Omit<QueueItem, "queuedAt">): void {
  setQueue([...getQueue(), { ...item, queuedAt: Date.now() }]);
}

export function cachedSnapshot(): PatientContextSummary | null {
  const raw = storage.getString(SNAPSHOT_KEY);
  if (!raw) return null;
  try {
    return JSON.parse(raw) as PatientContextSummary;
  } catch {
    return null;
  }
}

export function cacheSnapshot(snapshot: PatientContextSummary): void {
  storage.set(SNAPSHOT_KEY, JSON.stringify(snapshot));
}