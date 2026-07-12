import { readFile, readdir } from "node:fs/promises";
import { resolve } from "node:path";
import { gzipSync } from "node:zlib";

const distDirectory = resolve("dist");
const html = await readFile(resolve(distDirectory, "index.html"), "utf8");
const entryMatch = html.match(/<script[^>]+src="\/(assets\/index-[^"]+\.js)"/);

if (!entryMatch) {
  throw new Error("Unable to locate the Vite entry bundle in dist/index.html.");
}

const entrySource = await readFile(resolve(distDirectory, entryMatch[1]), "utf8");
const eager3DImport = /^import[^;\n]*from["']\.\/(?:HouseScene|three-runtime)-/m.test(entrySource);
const eager3DPreload = /<link[^>]+rel="modulepreload"[^>]+href="\/assets\/(?:HouseScene|three-runtime)-/.test(html);
if (eager3DImport || eager3DPreload) {
  throw new Error("The default 2D entry eagerly imports the lazy 3D runtime.");
}

const maxEntryBytes = 500 * 1024;
const preloadPaths = [...html.matchAll(/<link[^>]+rel="modulepreload"[^>]+href="\/(assets\/[^"?]+\.js)"/g)]
  .map((match) => match[1]);
const preloadSources = await Promise.all(
  preloadPaths.map((path) => readFile(resolve(distDirectory, path), "utf8")),
);
const initialBytes = [entrySource, ...preloadSources]
  .reduce((total, source) => total + Buffer.byteLength(source), 0);
if (initialBytes >= maxEntryBytes) {
  throw new Error("The default 2D entry exceeds the 500 KiB lazy-loading budget.");
}

const assetNames = await readdir(resolve(distDirectory, "assets"));
const threeRuntimeName = assetNames.find((name) => /^three-runtime-.+\.js$/.test(name));
if (!threeRuntimeName) {
  throw new Error("Unable to locate the deferred 3D runtime bundle.");
}
const threeRuntime = await readFile(resolve(distDirectory, "assets", threeRuntimeName));
const deferredThreeGzipBytes = gzipSync(threeRuntime).byteLength;
const maxDeferredThreeGzipBytes = 300 * 1024;
if (deferredThreeGzipBytes > maxDeferredThreeGzipBytes) {
  throw new Error(`The deferred 3D runtime exceeds its 300 KiB gzip budget (${deferredThreeGzipBytes} bytes).`);
}

console.log(`Verified: 2D initial JavaScript is ${initialBytes} bytes and deferred 3D gzip is ${deferredThreeGzipBytes} bytes within budget.`);
