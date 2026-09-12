import { useFrontendTool } from "@copilotkit/react-native/headless";
import { HomePlan, type Tile } from "@kinetic/ui-schema";
import { usePlanStore } from "../plan/store";
import { parsePlan } from "../plan/validate";

type ComposeHomeArgs = HomePlan;

/**
 * compose_home — the down-channel frontend tool (§4.3/§4.6). Registered ONCE
 * at the app root (§5.1 ledger). The ui_agent emits the plan as this tool
 * call; the handler double-checks it against the ui-schema and commits.
 */
export function useComposeHome() {
  useFrontendTool<ComposeHomeArgs>(
    {
      name: "compose_home",
      description: "Compose the patient home screen from a validated HomePlan.",
      agentId: "ui_agent",
      parameters: HomePlan,
      // §5.1 ledger: the plan is terminal — a compose_home result must never
      // request a follow-up run (recursive re-plan loop guard).
      followUp: false,
      handler: async (plan: ComposeHomeArgs) => {
        const parsed = parsePlan(plan);
        if (!parsed.ok) {
          console.warn("[compose] REJECTED:", parsed.error);
          usePlanStore.getState().fail(parsed.error);
          return "rejected: plan failed ui-schema validation";
        }
        console.log("[compose] commit", parsed.plan.planId, parsed.plan.tiles.length, "tiles");
        usePlanStore.getState().commit(parsed.plan);
        return "rendered";
      },
    },
    [],
  );
}

export type { Tile };