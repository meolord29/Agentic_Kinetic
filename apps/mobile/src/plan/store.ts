import { create } from "zustand";
import type { HomePlan } from "@kinetic/ui-schema";

/**
 * The plan store (§5.3 plan/store.ts). The agent owns WHAT is on screen; this
 * store holds the last committed plan. `commit` runs only after the §4.6
 * client-side gate passes — an unvalidated plan can never reach pixels.
 *
 * `dismissedBadgeN` is the one P2 demo accommodation for "Keep going"
 * (dismiss_celebration): the server-side celebration window (§5.6) is live for
 * 5 minutes and the ack endpoint is P4, so the client suppresses the
 * already-seen badge locally until the next scenario seed resets it.
 */
interface PlanState {
  plan: HomePlan | null;
  committedAt: number | null;
  parseError: string | null;
  dismissedBadgeN: number | null;
  commit: (plan: HomePlan) => void;
  fail: (message: string) => void;
  dismissCelebration: () => void;
  resetDismissal: () => void;
}

export const usePlanStore = create<PlanState>((set) => ({
  plan: null,
  committedAt: null,
  parseError: null,
  dismissedBadgeN: null,
  commit: (plan) => set({ plan, committedAt: Date.now(), parseError: null }),
  fail: (message) => set({ parseError: message }),
  dismissCelebration: () =>
    set((s) => {
      const n = s.plan?.tiles.find((t) => t.component === "BadgeCelebrationCard");
      return { dismissedBadgeN: n && n.component === "BadgeCelebrationCard" ? n.props.n : s.dismissedBadgeN };
    }),
  resetDismissal: () => set({ dismissedBadgeN: null }),
}));