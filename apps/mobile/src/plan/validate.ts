import { HomePlan, type HomePlan as HomePlanType } from "@kinetic/ui-schema";

/**
 * §4.6 client-side gate (commit time). The runtime already ran the full
 * §4.6 invariants (tile admissibility, verbatim diffs) against the snapshot —
 * that context stays server-side until the P1 up-channel feeds it back here.
 * The client's job: nothing that fails the ui-schema ever reaches pixels.
 */
export function parsePlan(raw: unknown): { ok: true; plan: HomePlanType } | { ok: false; error: string } {
  const result = HomePlan.safeParse(raw);
  if (!result.success) {
    const error = result.error.issues
      .map((i) => `${i.path.join(".")}: ${i.message}`)
      .join("; ")
      .slice(0, 280);
    return { ok: false, error };
  }
  return { ok: true, plan: result.data };
}