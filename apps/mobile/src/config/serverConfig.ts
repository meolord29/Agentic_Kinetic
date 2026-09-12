// §9.4 same-machine demo networking: the emulator reaches the host's loopback
// via the 10.0.2.2 alias. Compose ports bind 127.0.0.1 only. Hosted builds
// swap these for an HTTPS domain (§9.5) — no other code change.
export const RUNTIME_URL = "http://10.0.2.2:8200/api/copilotkit";
export const RUNTIME_HEALTH_URL = "http://10.0.2.2:8200/healthz";
export const DATA_API_URL = "http://10.0.2.2:8080";