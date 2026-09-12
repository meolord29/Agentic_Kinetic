import { useFrontendTool } from "@copilotkit/react-native/headless";
import { z } from "zod";
import { Overlay } from "@kinetic/ui-schema";
import { useOverlayStore } from "../plan/overlay";

type ComposeOverlayArgs = { overlay: Overlay };

/**
 * compose_overlay — the router's down-channel frontend tool (§4.3/§6.2).
 * Registered ONCE at the app root (§5.1 ledger). The handler re-validates the
 * overlay against the ui-schema (client-side gate, §4.6) before it can reach
 * pixels; a rejected overlay clears any stale popover instead of rendering it.
 */
export function useComposeOverlay() {
  useFrontendTool<ComposeOverlayArgs>(
    {
      name: "compose_overlay",
      description:
        "Show the result of a voice/typed note for confirmation before anything is saved.",
      agentId: "router",
      parameters: z.object({ overlay: Overlay }),
      followUp: false,
      handler: async (args: ComposeOverlayArgs) => {
        if (args.overlay.kind !== "voiceResult") {
          console.warn("[compose_overlay] rejected: non-voice overlay", args.overlay);
          return "rejected: overlay kind not renderable";
        }
        console.log("[compose_overlay] commit", args.overlay.variant);
        useOverlayStore.getState().commit(args.overlay);
        return "rendered";
      },
    },
    [],
  );
}
