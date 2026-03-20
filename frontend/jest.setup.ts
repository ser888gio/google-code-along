// Polyfills that must run before the test framework is installed.
// Note: @testing-library/jest-dom is loaded via setupFilesAfterFramework
// because it requires `expect` to be available.

import { TextEncoder, TextDecoder } from "util";

if (typeof globalThis.TextEncoder === "undefined") {
  globalThis.TextEncoder = TextEncoder as typeof globalThis.TextEncoder;
}
if (typeof globalThis.TextDecoder === "undefined") {
  globalThis.TextDecoder = TextDecoder as typeof globalThis.TextDecoder;
}

if (typeof globalThis.ReadableStream === "undefined") {
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const { ReadableStream } = require("stream/web");
  globalThis.ReadableStream = ReadableStream;
}

// JSDOM does not implement scrollIntoView — stub it globally
if (typeof Element !== "undefined" && !Element.prototype.scrollIntoView) {
  Element.prototype.scrollIntoView = () => {};
}
