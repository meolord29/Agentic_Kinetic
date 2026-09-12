import { CopilotKitProvider } from "@copilotkit/react-native/headless";
import { StatusBar } from "expo-status-bar";
import { StyleSheet, View } from "react-native";
import { colors } from "@kinetic/design-tokens";
import { useComposeHome } from "./src/agent/useComposeHome";
import { usePatientContext } from "./src/agent/usePatientContext";
import { RUNTIME_URL } from "./src/config/serverConfig";
import Home from "./src/screens/Home";

/**
 * App root (§5.3, P0 probe shape — no user auth by design (§3.1), no navigation until P1):
 *   CopilotKitProvider(runtimeUrl = 10.0.2.2:8200) → tools (once) → screen.
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
  // Register compose_home exactly once (§5.1 ledger: once per agent) and feed
  // the up-channel context (§4.3).
  useComposeHome();
  usePatientContext();
  return <Home />;
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.ground },
});