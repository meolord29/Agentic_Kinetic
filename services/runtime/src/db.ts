import { createSnapshotStore, type KineticData, type SnapshotStore } from "@kinetic/snapshot";

/**
 * P0/P1 db module (user decision: the agent reads Postgres directly with the
 * least-privilege kinetic_agent role; user auth dropped entirely — single-user
 * local demo, §3.1). The derivation itself lives in the shared
 * `@kinetic/snapshot` package so the data-api serves the exact same facts.
 */
const store = createSnapshotStore({ connectionString: process.env.DATABASE_URL ?? "" });

export const healthz = store.healthz;
export const getSnapshot = store.getSnapshot;
export const getData = store.getData;
export const close = store.close;

export type { KineticData, SnapshotStore };