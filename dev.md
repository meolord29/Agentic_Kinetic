# dev.md — local setup & demo guide (Ubuntu)

End-to-end instructions for taking a fresh **Ubuntu laptop** from zero to a
working demo: backend up in Docker, the APK built, installed and running inside
an Android Virtual Machine (AVD), the agent UI rendering dynamically, and proof
that every layer works.

Everything documented here has been run on the reference laptop described in
§0. Where this laptop already has a tool installed, the audit table says so —
skip the matching install section.

```
Browser tabs of the architecture, in one picture:

  [Android VM (AVD)]  --10.0.2.2-->  [Docker on the host (127.0.0.1 only)]
  apps/mobile                          data-api :8080  (Postgres :5432, unexposed)
  Expo / RN 0.86, on-device whisper      runtime  :8200  (LLM router, MODEL_ID)
  package: ai.kinetic.patient            migrations (auto-run on `npm run up`)
```

The emulator reaches the host's loopback via the special alias **`10.0.2.2`**.
Compose binds ports to `127.0.0.1` only, and the app's Android network-security
config permits cleartext HTTP **for `10.0.2.2` only** (see
`apps/mobile/app.config.js`). No LAN setup, no TLS, no exposure.

---

## 0. Toolchain audit — what do you already have?

Run this first. Anything green, skip in §2; anything red, install it.

| Check | Command | Reference laptop |
|---|---|---|
| Node ≥ 20 | `node -v` | v22.22.1 ✅ |
| JDK 17+ | `java -version` | openjdk 17.0.20 ✅ |
| Docker Engine | `docker --version` | 29.8.0 ✅ |
| Docker **Compose v2** | `docker compose version` | v5.5.1 ✅ |
| adb | `adb version` | 1.0.41 ✅ |
| Android SDK | `ls $HOME/Android/Sdk` | build-tools, cmake, cmdline-tools, emulator, ndk, platforms, system-images ✅ |
| KVM | `kvm-ok` (or `ls -la /dev/kvm`) | /dev/kvm present, `kvm` group ✅ |
| ffmpeg | `ffmpeg -version` | ❌ not installed — needed for §8 |
| AVD | `emulator -list-avds` | `kinetic` ✅ |

The only gap on the reference laptop is **ffmpeg**:

```bash
sudo apt install -y ffmpeg
```

---

## 1. System requirements

| Requirement | Notes |
|---|---|
| Ubuntu 22.04+ (or Debian 12+) | x86_64 with hardware virtualization (VT-x/AMD-V) enabled in BIOS/UEFI |
| Disk | ~25 GB free: Android SDK ~5 GB, one AVD ~8 GB, whisper model ~75 MB, Docker images ~1 GB, `node_modules` ~1 GB, Gradle caches ~3 GB, APK ~160–300 MB |
| RAM | 16 GB recommended (emulator + Docker + Gradle at the same time) |
| CPU | 4+ cores; KVM-capable |

---

## 2. Install the toolchain (Ubuntu)

Each subsection: what it is → install → verify.

### 2.1 Basics

```bash
sudo apt update
sudo apt install -y git curl unzip ffmpeg
git --version && curl --version | head -1 && ffmpeg -version | head -1
```

### 2.2 Node.js ≥ 20 (via nvm)

The workspace needs Node ≥ 20 (`package.json` → `engines`). Node 22 LTS matches
the `node:22-alpine` containers the backend runs in.

```bash
curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.3/install.sh | bash
# close & reopen the shell, then:
nvm install 22
node -v && npm -v
```

### 2.3 JDK 17+

The Android build uses **Gradle 9.3.1**, which refuses to run on anything older
than JDK 17. Ubuntu's packaged OpenJDK 17 is proven on the reference laptop
(21 also works).

```bash
sudo apt install -y openjdk-17-jdk
java -version
```

(Optional, recommended for a server-y setup: set `JAVA_HOME` in `~/.bashrc` —
`export JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64`.)

### 2.4 Docker Engine + Compose v2

The backend (Postgres, migrations, data-api, runtime) runs in Docker Compose.
You need **Compose v2** — the `docker compose` subcommand, *not* the legacy
`docker-compose` binary.

```bash
# official Docker apt repository
sudo apt-get update
sudo apt-get install -y ca-certificates curl
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] \
  https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo $VERSION_CODENAME) stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

# run docker without sudo
sudo usermod -aG docker $USER
sudo systemctl enable --now docker
```

**Log out and back in** (group changes only apply to new sessions), then:

```bash
docker run --rm hello-world
docker compose version
```

### 2.5 Android SDK, adb, emulator

Two routes. Route A is friendlier; Route B is fully scripted.

**Env exports (both routes need this — `deploy/demo.sh` expects exactly these
paths).** Append to `~/.bashrc`:

```bash
export ANDROID_HOME="$HOME/Android/Sdk"
export PATH="$ANDROID_HOME/platform-tools:$ANDROID_HOME/emulator:$ANDROID_HOME/cmdline-tools/latest/bin:$PATH"
```

**Route A — Android Studio**

1. Install Android Studio (JetBrains Toolbox, or download the `.tar.gz` from
   developer.android.com and run `studio.sh`).
2. SDK Manager (More Actions → SDK Manager) → install:
   - **SDK Platforms** → Android 15 (API 35)
   - **SDK Tools** → Android SDK Build-Tools, Android SDK Platform-Tools
     (this is **adb**), Android Emulator, NDK (side by side, 27.x), CMake,
     Android SDK Command-line Tools (latest)
3. Accept licenses: `sdkmanager --licenses`

**Route B — CLI only (no Studio)**

```bash
mkdir -p "$HOME/Android/Sdk/cmdline-tools"
cd "$HOME/Android/Sdk/cmdline-tools"
CMDLINE_TOOLS_ZIP="$(mktemp -d)/clt.zip"
curl -fSL -o "$CMDLINE_TOOLS_ZIP" \
  https://dl.google.com/android/repository/commandlinetools-linux-11076708_latest.zip
unzip -q "$CMDLINE_TOOLS_ZIP" -d .
mv cmdline-tools latest

sdkmanager "platform-tools" "platforms;android-35" "build-tools;35.0.0" \
  "emulator" "ndk;27.1.12297006" "cmake;3.22.1" \
  "system-images;android-35;google_apis;x86_64"
sdkmanager --licenses
```

**Verify:**

```bash
adb version
sdkmanager --list_installed
```

> `adb` lives in `platform-tools`. On the first run of every shell, the **adb
> server must start before the emulator** — see §5 for the boot-order rule.

### 2.6 KVM acceleration (mandatory for a usable emulator)

Without KVM the emulator runs ~10x slower (software emulation).

```bash
sudo apt install -y qemu-kvm cpu-checker
sudo usermod -aG kvm $USER
# log out & back in, then:
kvm-ok        # expect: "/dev/kvm exists … KVM acceleration can be used"
```

If `kvm-ok` fails, enable **VT-x / AMD-V (SVM)** in the BIOS/UEFI.

### 2.7 OpenRouter API key

The runtime routes every LLM request to one model through
[OpenRouter](https://openrouter.ai) (OpenAI-compatible, bring-your-own-key).

1. Create an account at <https://openrouter.ai>, add a small credit balance.
2. Create a key at <https://openrouter.ai/settings/keys>.
3. Keep it for §3 (`deploy/.env`).

---

## 3. Project setup

```bash
git clone https://github.com/meolord29/Agentic_Kinetic.git
cd Agentic_Kinetic
```

**One install covers everything.** The repo is an npm workspace
(`packages/*`, `services/*`, `apps/*`); the install is hoisted to the root,
and the backend containers bind-mount the repo and reuse that same install —
so a single `npm install` at the root is all the containers need too.

```bash
npm install
```

**Configure the backend env** (gitignored; compose reads it via
`--env-file deploy/.env`):

```bash
cp deploy/.env.example deploy/.env
```

Edit `deploy/.env`:

```bash
# generate once, paste in:
openssl rand -hex 24   # → DB_PASSWORD
openssl rand -hex 24   # → MIGRATOR_PASSWORD

DB_PASSWORD=<generated>
MIGRATOR_PASSWORD=<generated>
OPENROUTER_API_KEY=sk-or-v1-...        # from §2.7
MODEL_ID=openai/gpt-4o-mini            # every LLM request goes to this model
# OPENROUTER_BASE_URL=https://openrouter.ai/api/v1   # optional override
```

**Sanity check** (typechecks every workspace):

```bash
npm run typecheck
```

---

## 4. Start the backend

```bash
npm run up
```

This runs `docker compose --env-file deploy/.env -f deploy/docker-compose.yml
up --build -d`. What it brings up:

| Service | What it does | Port |
|---|---|---|
| `db` | postgres:16 (`kinetic` database) | internal only — not exposed |
| `migrations` | one-shot: applies `deploy/db/migrations/*.sql`, exits | — |
| `data-api` | Fastify API (snapshots, answers, scenario seeds, audit log) | `127.0.0.1:8080` |
| `runtime` | CopilotKit runtime + LLM router agent (`MODEL_ID`) | `127.0.0.1:8200` |

**Prove it works** (health endpoints, compose already waits for these too):

```bash
curl -fsS localhost:8080/healthz && echo " data-api green"
curl -fsS localhost:8200/healthz && echo " runtime green"
```

Tail logs / stop:

```bash
npm run logs    # follow data-api + runtime
npm run down    # stop everything (data survives in the pgdata volume)
```

---

## 5. Create & boot the Android Virtual Machine

### 5.1 Create the AVD (once)

Name it **`kinetic`** — that's the default `deploy/demo.sh` expects.

```bash
# list valid device profiles (pick one):
avdmanager list device | grep -A1 "pixel_7"

avdmanager create avd \
  -n kinetic \
  -k "system-images;android-35;google_apis;x86_64" \
  -d pixel_7
```

(or GUI route: Android Studio → Device Manager → Create Device → Pixel 7 →
API 35.)

### 5.2 Boot order — the adb-first rule

On any fresh shell/first boot, the **adb daemon must start before the
emulator**, or install/screencap/logcat all fail with
`Unable to connect to adb daemon on port: 5037`:

```bash
adb devices                     # 1. starts the adb daemon on :5037
emulator -avd kinetic -no-metrics &   # 2. boot the AVD (background it)
```

Wait for full boot (returns `1` when done):

```bash
adb wait-for-device
until [ "$(adb shell getprop sys.boot_completed 2>/dev/null | tr -d '\r')" = "1" ]; do sleep 2; done
adb devices                     # expect: emulator-5554  device
```

> The emulator is the app's **audio input** too (hold-to-talk voice): use
> Extended controls → Microphone → "Host microphone" if you want live voice,
> or skip straight to the scripted fixture in §8 which needs no mic at all.

---

## 6. Build the APK

### 6.1 Generate the native project (once, and after any `app.config.js` change)

`apps/mobile/android/` is **gitignored** — it is generated by Expo prebuild.
The config plugins in `apps/mobile/app.config.js` write the Android
network-security config that allows cleartext HTTP **to `10.0.2.2` only**
(reproducible across regenerations — don't hand-patch the manifest).

```bash
npm run prebuild -w apps/mobile      # = expo prebuild -p android
```

### 6.2 Fetch the whisper model (bundled into the APK)

On-device speech-to-text runs whisper.cpp; the model is shipped **inside the
APK** as a Metro asset (`metro.config.js` adds `bin` + `wav` to `assetExts`).
The chosen model is **ggml-tiny multilingual f16 (~75 MB)** — fetched by:

```bash
./scripts/fetch-whisper-model.sh
ls -la apps/mobile/assets/whisper/   # ggml-tiny.bin must exist
```

The script deletes superseded models, so the APK only ever carries one.

### 6.3 Assemble

**Debug APK** (dev loop, pairs with Metro / `expo start`):

```bash
cd apps/mobile/android
export ANDROID_HOME="$HOME/Android/Sdk"
./gradlew assembleDebug
# → app/build/outputs/apk/debug/app-debug.apk
```

**Release APK** (standalone demo, no Metro needed — this is what `demo.sh`
installs):

```bash
npm run build:release -w apps/mobile
# → apps/mobile/android/app/build/outputs/apk/release/app-release.apk  (~158 MB)
```

First build takes a while (Gradle downloads dependencies); later builds are
incremental (seconds). Requires the JDK 17+ from §2.3.

> **Changed the whisper model or any bundled asset?** Incremental builds can
> keep stale assets in the APK. Verify with
> `unzip -l app/build/outputs/apk/release/app-release.apk | grep -Ei "\.bin|\.wav"`
> and, if a stale model is still inside, rebuild clean:
> `./gradlew clean assembleRelease`.

---

## 7. Run the app in the Android VM

With the AVD booted (§5.2) and the backend up (§4):

```bash
# one-time runtime permission (mic), Android 13+ requires the grant:
adb shell pm grant ai.kinetic.patient android.permission.RECORD_AUDIO

# install + launch
adb install -r apps/mobile/android/app/build/outputs/apk/release/app-release.apk
adb shell am force-stop ai.kinetic.patient || true
adb shell am start -n ai.kinetic.patient/.MainActivity
```

Allow **~15 s** on a cold start before JS activity shows up, then watch it
live:

```bash
adb logcat -s ReactNativeJS:*
# healthy turn looks like:
#   I ReactNativeJS: [run] start
#   I ReactNativeJS: '[compose] commit', 'plan-…', N, 'tiles'
#   I ReactNativeJS: '[run] ok', 104, 'ms'
```

Screenshot at any time:

```bash
adb exec-out screencap -p > /tmp/opencode/app.png
```

### Dev alternative: Metro hot-reload loop

Instead of installing a built APK each time:

```bash
cd apps/mobile
npx expo run:android        # builds, installs, starts Metro (:8081), live-reloads
# or: npx expo start  then press `a` with the AVD running
```

### Networking: how the app reaches the backend

- The app is hard-coded to the emulator's host-loopback alias:
  `http://10.0.2.2:8200/api/copilotkit` (+ data-api `:8080`), see
  `apps/mobile/src/config/serverConfig.ts`.
- Cleartext HTTP is permitted **only** for `10.0.2.2` (network-security
  config written by the config plugins). A real device would be refused —
  by design; hosted builds swap in an HTTPS domain.
- Debugging fallback if a build resolves `localhost` directly:
  `adb reverse tcp:8080 tcp:8080 && adb reverse tcp:8200 tcp:8200`.

> **Emulator quirk:** some AVD images show a "stylus" IME overlay that hijacks
> text input — an emulator feature, not an app bug. Dismiss it once, or switch
> input method: `adb shell ime set com.android.adbkeyboard/.AdbIME`.

---

## 8. Run the demo (recorded audio → dynamic UI)

This is the scripted, deterministic demo path. No microphone needed: a voice
clip is transcribed **on-device** by whisper.cpp, classified by the LLM router,
and the home UI re-composes dynamically — including the agent asking the
follow-up question (e.g. "What time did you take the new pill?", temperature /
symptom chains).

### 8.1 Bring the stack to a known state

Backend up (§4), AVD booted (§5.2), app installed & running (§7). Then seed a
clean scenario. Either tap a row in the in-app **ScenarioDrawer** (dev
harness) or hit the API directly:

```bash
# reset to a neutral baseline:
curl -s -X POST localhost:8080/dev/scenario/clear

# available scenarios (same rows as the drawer):
#   morning  – "Morning dose (31 · dose due)"   ← clean-slate reset too
#   question – "Care-team question"
#   badge    – "Badge day (99 → tap dose)"
#   clear    – "All clear"
#   health   – "Voice · health question (hold FAB)"
#   sick     – "Sick day · symptom chains"
#   diary    – "Diary entry shared"
```

### 8.2 Trigger the demo voice clip

1. Open the ScenarioDrawer in the app (⚙ button top-right).
2. Tap **"🎙 Demo audio · 'I have a flu' (on-device whisper)"**.

What happens under the hood: the bundled fixture WAV
(`apps/mobile/assets/voice/demo-flu.wav`) goes through the **same pipeline as
hold-to-talk** — on-device whisper.cpp transcription → router agent
(`classify_voice_note` → `sick`, "Flu-like") → `compose_overlay` commit → the
result popover renders ("You said … I think I have a flu." + noted rows +
**Looks right / Say it again**). Nothing commits before confirmation.

In logcat you'll see:

```
I ReactNativeJS: '[compose_overlay] commit', 'sick'
```

### 8.3 Confirm and watch the dynamic UI ask follow-ups

Tap **Looks right** → the home re-composes:

- "Thanks for telling us!" flash **without** a +1 (voice shares are never
  check-ins),
- the follow-up question chain fires **one question at a time**:
  VomitCheckCard → TemperatureCard ("38 °C +" etc.) → done rows
  ("How you feel · Flu-like").

Answer them by tapping — each answer re-plans the home server-side.

### 8.4 Driving the UI from the shell (no manual tapping)

Find any button's coordinates from the UI dump instead of guessing:

```bash
adb shell uiautomator dump /sdcard/ui.xml >/dev/null
adb shell cat /sdcard/ui.xml | python3 -c "
import re, sys
xml = sys.stdin.read()
for m in re.finditer(r'text=\"([^\"]{1,80})\"[^>]*bounds=\"\[(\d+),(\d+)\]\[(\d+),(\d+)\]\"', xml):
    t, l, tp, r, b = m.group(1), *map(int, m.group(2, 3, 4, 5))
    print(repr(t), (l + r) // 2, (tp + b) // 2)
"
# then tap the row you want:
adb shell input tap 540 2137
```

### 8.5 Record the demo as an mp4

Capture the dynamic UI change as video (75 s cap per file, 3 min max per
recording):

```bash
adb shell screenrecord --time-limit 75 /sdcard/demo.mp4 &
# …drive the demo (§8.2–8.3) while it records…
sleep 78                      # let it finalize on-device
adb pull /sdcard/demo.mp4 demo/demo-voice.mp4
```

> If the recording is interrupted, the file can be a corrupt stub — check with
> `adb shell ls -la /sdcard/demo.mp4` before pulling, or just re-record.

### 8.6 Prove it server-side

```bash
# snapshot state (due flags, progress):
curl -s localhost:8080/me/snapshot | python3 -m json.tool | head -30

# audit trail — every request lands here:
docker exec deploy-db-1 psql -U kinetic_agent -d kinetic -t \
  -c "SELECT action, purpose FROM app.audit_log ORDER BY at DESC LIMIT 5"
```

Expected after the flu demo: `compose_overlay 'sick'` in logcat, temperature
answers in the audit log (`answers.create | temperature answer …`), and
`due.temperature: {"due": false}` in the snapshot once the chain is complete.

### 8.7 Live-mic variant (optional, demo-flaky)

The fixture path is the deterministic one. For real hold-to-talk: set the
emulator's audio input to the host microphone (Extended controls →
Microphone), hold the mic FAB, speak, release. The whisper → router → confirm
pipeline is identical — only the recorder differs. If whisper can't
initialize, the app **hides the mic FAB by design** and the typed-request path
stays available.

---

## 9. End-to-end proof checklist

Run top to bottom; each gate has a visible pass condition:

```bash
# 1. backend
curl -fsS localhost:8080/healthz && curl -fsS localhost:8200/healthz
#    → both print "OK"-style 200 bodies, no hang

# 2. AVD
adb devices
#    → emulator-5554  device

# 3. app
adb shell pidof ai.kinetic.patient && adb logcat -d -s ReactNativeJS:* | tail -3
#    → pid printed; logcat ends with '[run] ok' / '[compose] commit'

# 4. demo turn
#    ScenarioDrawer → fixture button → popover; then §8.6 checks pass
#    (audit rows exist, due flags clear)

# 5. screenshot / video evidence
adb exec-out screencap -p > /tmp/opencode/proof.png
```

Type-level safety across every workspace:

```bash
npm run typecheck
```

---

## 10. One-command demo: `deploy/demo.sh`

`deploy/demo.sh` automates §4–§7 (expects the release APK from §6.3):

```bash
./deploy/demo.sh
```

Sequence: compose up (`--wait`, healthz greens) → whisper model fetch (no-op
if present) → `adb devices` (the adb-first rule) → boot the AVD (skipped if
one is already up) → `adb install -r` the release APK → launch via monkey →
screencap to `deploy/demo-screencap.png` → dump ReactNativeJS errors.

Overrides: `AVD_NAME=my-avd ./deploy/demo.sh` or
`APK=/path/to/app-debug.apk ./deploy/demo.sh`.

---

## 11. Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `permission denied … /var/run/docker.sock` | Not in the `docker` group yet → `sudo usermod -aG docker $USER`, **log out & back in** (§2.4) |
| `docker: 'compose' is not a docker command` | Compose v1 (`docker-compose`) installed → install `docker-compose-plugin` (§2.4) |
| `emulator: ERROR: … /dev/kvm` or glacial boot | KVM missing → §2.6; check BIOS VT-x/AMD-V; `kvm-ok` must pass |
| `ERROR: Unable to connect to adb daemon on port: 5037` | Emulator started before adb → kill emulator, run `adb devices` first (§5.2) |
| `adb: no devices/emulators found` mid-session | Emulator crashed/restarted → `adb kill-server && adb start-server && adb devices`, re-verify boot with `getprop sys.boot_completed` |
| App shows no data / agent dead | Backend down or unhealthy → `curl localhost:8080/healthz`; remember the emulator reaches the host as `10.0.2.2`, compose binds `127.0.0.1` only (§7) |
| `Cleartext HTTP traffic … not permitted` | Expected on any host other than `10.0.2.2` — the security config is scoped on purpose; use the emulator path or regenerate native project after editing `app.config.js` (`npm run prebuild -w apps/mobile`) |
| Mic FAB missing in the app | whisper model not initialized → is `apps/mobile/assets/whisper/ggml-tiny.bin` present (§6.2)? The FAB hides by design; typed input still works |
| Stale model/asset inside the APK after a swap | Incremental build kept merged-res leftovers → verify with `unzip -l … \| grep .bin`, then `./gradlew clean assembleRelease` (§6.3) |
| `Unsupported class file major version` / Gradle dies at start | Wrong JDK → Gradle 9.3.1 needs JDK 17+ (§2.3); check `java -version` and `JAVA_HOME` |
| Port clash on 8080 / 8200 / 8081 | data-api / runtime / Metro already bound (old compose project or stray dev server) → `npm run down`, `lsof -i :8080`, retry |
| Port 5432 "already in use" | A local Postgres outside compose — the compose `db` is **not** exposed to the host, so the clash is with something else; stop the local service |
| Text input hijacked by "stylus" overlay | Emulator IME feature, not the app → dismiss once or `adb shell ime set com.android.adbkeyboard/.AdbIME` (§7) |
| Emulator renders but is very slow / wrong colors | Software rendering (llvmpipe) fallback — cosmetic, accepted for the demo; whisper is CPU-bound anyway |
| `screenrecord` file won't play | Recording was interrupted before finalizing → re-record and wait past `--time-limit` before pulling (§8.5) |
| Cold start seems frozen | First JS turn takes ~15 s after `am start` — watch `adb logcat -s ReactNativeJS:*` for `[run] ok` (§7) |
