/* Browser tests against a real Flask instance.

   One server on a free port, pointed with --app-dir at a throwaway data
   directory under the OS temp folder, with a generated sample library
   beside it. Nothing touches the real library next to app.py. The specs
   share that server and run one after another. */
import { defineConfig } from "@playwright/test";
import { execFileSync } from "node:child_process";
import { existsSync, mkdtempSync, readdirSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const python = process.env.ARIADNE_PYTHON ?? (process.platform === "win32" ? "py" : "python3");

// evaluated once in the runner, then inherited by the workers through env
if (!process.env.ARIADNE_E2E_DIR) {
  // earlier runs leave their directories behind (the server still held the
  // database when they ended); clear them now that nothing uses them
  for (const name of readdirSync(tmpdir())) {
    if (name.startsWith("ariadne-e2e-")) {
      try { rmSync(join(tmpdir(), name), { recursive: true, force: true }); } catch { /* still in use */ }
    }
  }
}
const appDir = process.env.ARIADNE_E2E_DIR ?? mkdtempSync(join(tmpdir(), "ariadne-e2e-"));
process.env.ARIADNE_E2E_DIR = appDir;
const port = process.env.ARIADNE_E2E_PORT ?? execFileSync(python, [
  "-c", "import socket; s = socket.socket(); s.bind(('127.0.0.1', 0)); print(s.getsockname()[1])",
]).toString().trim();
process.env.ARIADNE_E2E_PORT = port;
const library = join(appDir, "library");
if (!existsSync(library)) {
  execFileSync(python, [join(root, "scripts", "make_sample_library.py"), library, "16"], { stdio: "inherit" });
}

export default defineConfig({
  testDir: "e2e",
  fullyParallel: false,
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  timeout: 60_000,
  expect: { timeout: 10_000 },
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : "list",
  use: {
    baseURL: `http://127.0.0.1:${port}`,
    viewport: { width: 1280, height: 800 },
    trace: "retain-on-failure",
  },
  webServer: {
    command: `${python} app.py --no-browser --port ${port} --app-dir "${appDir}"`,
    cwd: root,
    url: `http://127.0.0.1:${port}/api/stats`,
    reuseExistingServer: false,
    timeout: 90_000,
    stdout: "ignore",
    stderr: "pipe",
  },
});
