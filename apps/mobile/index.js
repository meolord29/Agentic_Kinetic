// §5.1 ledger — import order is load-bearing (first-writer-wins crypto):
//   1. react-native-get-random-values  2. CopilotKit polyfills  3. everything else
import "react-native-get-random-values";
import "@copilotkit/react-native/polyfills";

import { registerRootComponent } from "expo";

import App from "./App";

registerRootComponent(App);