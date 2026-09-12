import { useAgentContext } from "@copilotkit/react-native/headless";
import { useSnapshotStore } from "../data/snapshot";

/**
 * The up-channel (§4.3/§4.4): the full PatientContextSummary registered as
 * agent context, re-registered on every snapshot change (optimistic or
 * authoritative). P1's deterministic ui_agent reads the DB directly — this
 * context becomes the planner's input the moment the LLM composer joins.
 */
export function usePatientContext(): void {
  const context = useSnapshotStore((s) => s.context);
  useAgentContext({
    description:
      "Patient context summary: progress, consent, what is due today (dose, question, temperature, reminders).",
    value: context ?? { note: "no snapshot yet" },
  });
}