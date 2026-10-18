// Copies the IDL produced by `anchor build` into the backend, which reads instruction,
// account and event layouts from it (backend/app/chain/codec.py), so the backend always
// talks to the program it was built against.
// Runs automatically as the Anchor.toml post-build hook; safe to run by hand.
import { copyFileSync, existsSync, mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const from = join(root, "target", "idl", "proofsettle.json");
const outDir = join(root, "backend", "app", "chain");

if (!existsSync(from)) {
  console.error("sync-idl: target/idl/proofsettle.json not found. Run `anchor build` first.");
  process.exit(1);
}
mkdirSync(outDir, { recursive: true });
copyFileSync(from, join(outDir, "proofsettle.json"));
console.log("sync-idl: target/idl/proofsettle.json -> backend/app/chain/proofsettle.json");
