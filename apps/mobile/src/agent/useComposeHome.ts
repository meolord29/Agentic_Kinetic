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
      handler: async (plan: ComposeHomeArgs) => {
        const parsed = parsePlan(plan);
        if (!parsed.ok) {
          usePlanStore.getState().fail(parsed.error);
          return "rejected: plan failed ui-schema validation";
        }
        usePlanStore.getState().commit(parsed.plan);
        return "rendered";
      },
    },
    [],
  );
}

export type { Tile };