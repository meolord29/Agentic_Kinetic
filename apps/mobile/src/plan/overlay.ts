import { create } from "zustand";
import type { Overlay } from "@kinetic/ui-schema";

/**
 * Overlay store (§4.2 down-channel, second tool). The router emits
 * `compose_overlay` with a voiceResult overlay; the client gate (ui-schema
 * zod, run inside useComposeOverlay) has already passed by the time anything
 * lands here. Nothing on screen commits until the user taps "Looks right" —
 * confirm-before-act (workflows 07/08/11/12 §6).
 */
interface OverlayState {
  overlay: Extract<Overlay, { kind: "voiceResult" }> | null;
  commit: (overlay: Extract<Overlay, { kind: "voiceResult" }>) => void;
  clear: () => void;
}

export const useOverlayStore = create<OverlayState>((set) => ({
  overlay: null,
  commit: (overlay) => set({ overlay }),
  clear: () => set({ overlay: null }),
}));
