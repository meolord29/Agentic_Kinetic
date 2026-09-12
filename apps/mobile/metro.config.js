const { getDefaultConfig } = require("expo/metro-config");

const config = getDefaultConfig(__dirname);

// §5.1 ledger: `jose` (pulled in via CopilotKit telemetry deps) imports `node:`
// builtins that break Hermes release bundles. Force the browser export
// condition for jose ONLY — never globally.
config.resolver.resolveRequest = (context, moduleName, platform) => {
  if (moduleName === "jose") {
    return context.resolveRequest(
      { ...context, unstable_conditionNames: ["browser", "import", "require"] },
      moduleName,
      platform,
    );
  }
  return context.resolveRequest(context, moduleName, platform);
};

module.exports = config;