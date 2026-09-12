import { create } from "zustand";

/**
 * Dev-harness bridge (§5.5): the ScenarioDrawer offers the bundled fixture
 * clip; VoiceLayer registers the runner that owns the whisper context + the
 * router agent. Demo-only — the runner is never registered in a non-dev flow
 * outside the drawer.
 */
interface FixtureState {
  runFluFixture: (() => Promise<void>) | null;
  register: (runner: (() => Promise<void>) | null) => void;
}

export const useVoiceFixture = create<FixtureState>((set) => ({
  runFluFixture: null,
  register: (runner) => set({ runFluFixture: runner }),
}));
