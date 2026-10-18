// Copies the IDL and TypeScript types produced by `anchor build` into the web app,
// so the app always talks to the program it was built against.
// Runs automatically as the Anchor.toml post-build hook; safe to run by hand.
import { copyFileSync, existsSync, mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const outDir = join(root, "src", "lib", "solana", "idl");
const files = [
  ["target/idl/proofsettle.json", "proofsettle.json"],
  ["target/types/proofsettle.ts", "proofsettle.ts"],
];

mkdirSync(outDir, { recursive: true });
for (const [from, to] of files) {
  const src = join(root, from);
  if (!existsSync(src)) {
    console.error(`sync-idl: ${from} not found. Run \`anchor build\` first.`);
    process.exit(1);
  }
  copyFileSync(src, join(outDir, to));
  console.log(`sync-idl: ${from} -> src/lib/solana/idl/${to}`);
}
