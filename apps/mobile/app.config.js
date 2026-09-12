const { AndroidConfig, withAndroidManifest, withDangerousMod } = require("expo/config-plugins");
const fs = require("node:fs");
const path = require("node:path");

/**
 * §5.7/R3: demo-flavor cleartext HTTP scoped to the 10.0.2.2 loopback ONLY —
 * never app-wide. Reproducible across `expo prebuild` (the P0 hand-patch was
 * lost when android/ regenerated).
 */
const NSC_XML = `<?xml version="1.0" encoding="utf-8"?>
<network-security-config>
  <domain-config cleartextTrafficPermitted="true">
    <domain includeSubdomains="false">10.0.2.2</domain>
  </domain-config>
</network-security-config>
`;

const withLoopbackCleartext = (config) =>
  withDangerousMod(config, [
    "android",
    async (mod) => {
      const resXml = path.join(
        mod.modRequest.projectRoot,
        "android",
        "app",
        "src",
        "main",
        "res",
        "xml",
      );
      fs.mkdirSync(resXml, { recursive: true });
      fs.writeFileSync(path.join(resXml, "network_security_config.xml"), NSC_XML);
      return mod;
    },
  ]);

const withNetworkSecurityConfig = (config) =>
  withAndroidManifest(config, (mod) => {
    mod.modResults.manifest.application[0].$["android:networkSecurityConfig"] =
      "@xml/network_security_config";
    return mod;
  });

/** @type {import('@expo/metro-config').MetroConfig} */
module.exports = {
  expo: {
    name: "Agentic Kinetic",
    slug: "agentic-kinetic",
    version: "0.1.0",
    orientation: "portrait",
    icon: "./assets/icon.png",
    userInterfaceStyle: "light",
    android: {
      package: "ai.kinetic.patient",
      permissions: ["RECORD_AUDIO"],
      adaptiveIcon: {
        backgroundColor: "#EAE3D2",
        foregroundImage: "./assets/android-icon-foreground.png",
        backgroundImage: "./assets/android-icon-background.png",
        monochromeImage: "./assets/android-icon-monochrome.png",
      },
      predictiveBackGestureEnabled: false,
    },
    web: {
      favicon: "./assets/favicon.png",
    },
    plugins: [withLoopbackCleartext, withNetworkSecurityConfig],
  },
};
