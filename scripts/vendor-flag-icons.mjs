import { cpSync, copyFileSync, mkdirSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const projectRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const packageRoot = resolve(projectRoot, "node_modules", "flag-icons");
const vendorRoot = resolve(projectRoot, "frontend", "vendor", "flag-icons");

mkdirSync(resolve(vendorRoot, "css"), { recursive: true });
mkdirSync(resolve(vendorRoot, "flags"), { recursive: true });
copyFileSync(
  resolve(packageRoot, "css", "flag-icons.min.css"),
  resolve(vendorRoot, "css", "flag-icons.min.css"),
);
cpSync(
  resolve(packageRoot, "flags", "4x3"),
  resolve(vendorRoot, "flags", "4x3"),
  { recursive: true },
);
copyFileSync(resolve(packageRoot, "LICENSE"), resolve(vendorRoot, "LICENSE"));
