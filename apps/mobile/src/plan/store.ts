import { create } from "zustand";
import type { HomePlan } from "@kinetic/ui-schema";

/**
 * The plan store (§5.3 plan/store.ts). The agent owns WHAT is on screen; this
 * store holds the last committed plan. `commit` runs only after the §4.6
 * client-side gate passes — an unvalidated plan can never reach pixels.
 */
interface PlanState {
  plan: HomePlan | null;
  committedAt: number | null;
  parseError: string | null;
  commit: (plan: HomePlan) => void;
  fail: (message: string) => void;
}

export const usePlanStore = create<PlanState>((set) => ({
  plan: null,
  committedAt: null,
  parseError: null,
  commit: (plan) => set({ plan, committedAt: Date.now(), parseError: null }),
  fail: (message) => set({ parseError: message }),
}));