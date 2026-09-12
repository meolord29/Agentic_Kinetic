import { useEffect, useRef } from "react";
import * as Crypto from "expo-crypto";
import { create } from "zustand";
import { BADGE_THRESHOLDS, type Action, type PatientContextSummary } from "@kinetic/ui-schema";
import { api, ApiError } from "./api";
import { cacheSnapshot, cachedSnapshot, enqueue, getQueue, setQueue, type QueueItem } from "./queue";

/**
 * Client context controller (§4.3 up-channel + §5.6 offline queue):
 *   snapshot → optimistic mutation + enqueue → flush with backoff → re-plan.
 * The UI never waits on the network and never asks the patient to "try again"
 * — the queue is the app's job, not hers. Reward math is server-side at flush
 * time (§7.3); optimistic checkin counts here are display-only.
 */

type Connectivity = "connecting" | "online" | "offline";

interface SnapshotState {
  context: PatientContextSummary | null;
  connectivity: Connectivity;
  queued: number;
  /** Bumped on every commit/refresh — the signal to run the ui_agent again. */
  planNonce: number;
}

export const useSnapshotStore = create<SnapshotState>(() => ({
  context: cachedSnapshot(),
  connectivity: "connecting",
  queued: 0,
  planNonce: 0,
}));

const set = useSnapshotStore.setState;
const bumpPlan = () => set((s) => ({ planNonce: s.planNonce + 1 }));

function optimisticApply(context: PatientContextSummary, action: Action): PatientContextSummary {
  // Display-only optimistic state (§5.6) — the server recomputes the
  // authoritative reward math at flush time.
  switch (action.type) {
    case "answer_dose": {
      const checkins = context.progress.checkins + 1;
      const nextN = BADGE_THRESHOLDS.find((n) => n > checkins) ?? null;
      return {
        ...context,
        progress: {
          ...context.progress,
          checkins,
          level: Math.floor(checkins / 25) + 1,
          levelPct: Math.round(((checkins % 25) / 25) * 100),
          nextBadge: nextN
            ? { n: nextN, label: context.progress.nextBadge?.label ?? `Badge ${nextN}`, remaining: nextN - checkins }
            : null,
        },
        due: { ...context.due, dose: { status: "done", answer: action.value } },
      };
    }
    case "answer_question":
      return { ...context, due: { ...context.due, teamQuestion: { waiting: false, text: null } } };
    case "answer_temperature":
      return { ...context, due: { ...context.due, temperature: { due: false, reason: null } } };
    case "ack_reminder":
      return {
        ...context,
        due: { ...context.due, reminders: context.due.reminders.filter((r) => r.id !== action.id) },
      };
    default:
      return context;
  }
}

function toQueueItem(action: Action, eventId: string): Omit<QueueItem, "queuedAt"> | null {
  switch (action.type) {
    case "answer_dose":
      return { eventId, endpoint: "/me/checkins", payload: { answer: action.value, eventId } };
    case "answer_question":
      return { eventId, endpoint: "/me/answers", payload: { kind: "question", value: action.value, eventId } };
    case "answer_temperature":
      return { eventId, endpoint: "/me/answers", payload: { kind: "temperature", value: action.value, eventId } };
    case "ack_reminder":
      return { eventId, endpoint: "/me/reminders/ack", reminderId: action.id, payload: { eventId } };
    default:
      return null; // toast/go/tour/call_care_team stay UI-local (P3/P4 workflows)
  }
}

async function callEndpoint(item: QueueItem): Promise<unknown> {
  switch (item.endpoint) {
    case "/me/checkins":
      return api.checkin(item.payload.answer as string, item.eventId);
    case "/me/answers":
      return item.payload.kind === "question"
        ? api.answerQuestion(item.payload.value as string, item.eventId)
        : api.answerTemperature(item.payload.value as string, item.eventId);
    case "/me/reminders/ack":
      return api.ackReminder(item.reminderId!, item.eventId);
  }
}

let flushing = false;
let backoffMs = 1000;

/** Flush loop: in-order, stop-on-first-failure, exponential backoff (§5.6). */
export async function flushQueue(): Promise<void> {
  if (flushing) return;
  flushing = true;
  try {
    let queue = getQueue();
    while (queue.length > 0) {
      const item = queue[0];
      try {
        await callEndpoint(item);
        queue = queue.slice(1);
        setQueue(queue);
        set({ queued: queue.length });
        backoffMs = 1000;
      } catch (err) {
        const status = err instanceof ApiError ? err.status : null;
        if (status === null || status >= 500) {
          // Unreachable server or 5xx → stay queued, retry later. The UI shows
          // a quiet reconnecting chip; nothing asks the patient to retry.
          set({ connectivity: "offline" });
          setTimeout(() => void flushQueue(), backoffMs);
          backoffMs = Math.min(backoffMs * 2, 60000);
          return;
        }
        // 4xx → poison event; drop it but keep the audit trail server-side.
        console.warn("[queue] dropping poisoned event:", item.eventId, err instanceof Error ? err.message : err);
        queue = queue.slice(1);
        setQueue(queue);
        set({ queued: queue.length });
      }
    }
    // Queue drained (the failure path returns early) → pull authoritative
    // state (server-side badge math) and re-plan from it.
    await refresh();
    bumpPlan();
  } finally {
    flushing = false;
  }
}

export async function probeAndRefresh(): Promise<void> {
  set({ connectivity: "connecting" });
  const [dataOk, runtimeOk] = await Promise.all([api.dataHealthz(), api.runtimeHealthz()]);
  if (!dataOk || !runtimeOk) {
    set({ connectivity: "offline" });
    return;
  }
  set({ connectivity: "online" });
  await refresh();
  const queued = getQueue().length;
  set({ queued });
  if (queued > 0) void flushQueue();
}

export async function refresh(): Promise<void> {
  try {
    const snapshot = await api.snapshot();
    cacheSnapshot(snapshot);
    set({ context: snapshot });
  } catch (err) {
    console.warn("[snapshot] refresh failed — keeping last valid:", err);
    set({ connectivity: "offline" });
    const cached = cachedSnapshot();
    if (cached) set({ context: cached });
  }
}

/** The chip-tap entry point: optimistic → enqueue → flush → re-plan (§4.7). */
export function dispatchAction(action: Action): void {
  const current = useSnapshotStore.getState().context;
  if (current) {
    const next = optimisticApply(current, action);
    if (next !== current) {
      cacheSnapshot(next);
      set({ context: next });
    }
  }

  const eventId = Crypto.randomUUID();
  const item = toQueueItem(action, eventId);
  if (item) {
    enqueue(item);
    set({ queued: getQueue().length });
    void flushQueue();
  }

  bumpPlan();
}

/** Mount-time wiring: initial probe + quiet reconnect attempts while offline. */
export function useSnapshotLifecycle(): void {
  const connectivity = useSnapshotStore((s) => s.connectivity);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    void probeAndRefresh();
  }, []);

  useEffect(() => {
    if (connectivity !== "offline" || timer.current !== null) return;
    timer.current = setTimeout(() => {
      timer.current = null;
      void probeAndRefresh();
    }, 5000);
    return () => {
      if (timer.current !== null) {
        clearTimeout(timer.current);
        timer.current = null;
      }
    };
  }, [connectivity]);
}