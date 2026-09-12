import { CopilotKitProvider } from "@copilotkit/react-native/headless";
import { StatusBar } from "expo-status-bar";
import { StyleSheet, View } from "react-native";
import { colors } from "@kinetic/design-tokens";
import { useComposeHome } from "./src/agent/useComposeHome";
import { useComposeOverlay } from "./src/agent/useComposeOverlay";
import { usePatientContext } from "./src/agent/usePatientContext";
import { RUNTIME_URL } from "./src/config/serverConfig";
import Home from "./src/screens/Home";
import VoiceLayer from "./src/voice/VoiceLayer";

/**
 * App root (§5.3, P3 voice edition — no user auth by design (§3.1)):
 *   CopilotKitProvider(runtimeUrl = 10.0.2.2:8200)
 *     → tools (compose_home + compose_overlay, once each) → screen + VoiceLayer.
 */
export default function App() {
  return (
    <CopilotKitProvider
      runtimeUrl={RUNTIME_URL}
      onError={(event) => {
        console.warn("[copilotkit]", event.code, event.error?.message);
      }}
    >
      <View style={styles.root}>
        <Root />
        <StatusBar style="dark" />
      </View>
    </CopilotKitProvider>
  );
}

function Root() {
  // Register the down-channel tools exactly once each (§5.1 ledger) and feed
  // the up-channel context (§4.3).
  useComposeHome();
  useComposeOverlay();
  usePatientContext();
  return (
    <>
      <Home />
      <VoiceLayer />
    </>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.ground },
});