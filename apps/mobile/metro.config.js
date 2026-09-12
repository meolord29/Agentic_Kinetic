const { getDefaultConfig } = require("expo/metro-config");

const config = getDefaultConfig(__dirname);

// §5.4: the whisper model (raw .bin) and the demo voice fixture (wav) are
// bundled in the APK as Metro assets.
for (const ext of ["bin", "wav"]) {
  if (!config.resolver.assetExts.includes(ext)) config.resolver.assetExts.push(ext);
}

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