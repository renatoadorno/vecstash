# Bun — Runtime, Bundler, and Package Manager

Bun is an all-in-one JavaScript & TypeScript toolkit. It ships as a single executable and includes a runtime, package manager, bundler, and test runner.

## Installation

```bash
# macOS / Linux
curl -fsSL https://bun.sh/install | bash

# Homebrew
brew install oven-sh/bun/bun

# npm (if you already have Node.js)
npm install -g bun
```

After installing, verify with:

```bash
bun --version
```

## HTTP Server (Bun.serve)

Bun provides a built-in high-performance HTTP server via `Bun.serve()`. It uses a declarative route-based API (Bun v1.2.3+).

### Basic Setup

```js
const server = Bun.serve({
  routes: {
    // Static response
    "/api/status": new Response("OK"),

    // Dynamic route with params
    "/users/:id": (req) => {
      return new Response(`Hello User ${req.params.id}!`);
    },

    // Per-method handlers
    "/api/posts": {
      GET: () => new Response("List posts"),
      POST: async (req) => {
        const body = await req.json();
        return Response.json({ created: true, ...body });
      },
    },

    // Wildcard catch-all
    "/api/*": Response.json({ message: "Not found" }, { status: 404 }),

    // Redirect
    "/blog/hello": Response.redirect("/blog/hello/world"),

    // Serve a file
    "/favicon.ico": Bun.file("./favicon.ico"),
  },

  // Fallback for unmatched routes
  fetch(req) {
    return new Response("Not Found", { status: 404 });
  },
});

console.log(`Server running at ${server.url}`);
```

### Configuration

You can configure the port, hostname, TLS, and more:

```js
Bun.serve({
  port: 3000,
  hostname: "0.0.0.0",
  fetch(req) {
    return new Response("Hello!");
  },
});
```

### Unix Domain Sockets

```js
Bun.serve({
  unix: "/tmp/my-socket.sock",
  fetch(req) {
    return new Response("Hello via Unix socket!");
  },
});
```

### Hot Route Reloading

Run with `bun --hot server.ts` to enable hot reloading. The server stays running and routes are updated without restart.

### Server Lifecycle

```js
const server = Bun.serve({ /* ... */ });

server.stop();          // Graceful shutdown
server.ref();           // Keep process alive
server.unref();         // Allow process to exit
server.reload({ /* new config */ });  // Update routes at runtime
```

## File I/O

Bun provides optimized APIs for reading and writing files through `Bun.file()` and `Bun.write()`.

### Reading Files (Bun.file)

`Bun.file(path)` returns a lazy `BunFile` reference (extends `Blob`). The file is not read until you consume it.

```js
const file = Bun.file("foo.txt");
file.size;   // number of bytes
file.type;   // MIME type

// Read contents in different formats
const text = await file.text();          // string
const json = await file.json();          // parsed JSON
const stream = file.stream();            // ReadableStream
const buffer = await file.arrayBuffer(); // ArrayBuffer
const bytes = await file.bytes();        // Uint8Array

// Check existence
const exists = await file.exists();      // boolean
```

### Writing Files (Bun.write)

`Bun.write(destination, data)` writes data to a file, returning the number of bytes written.

```js
// Write a string
await Bun.write("output.txt", "Hello, world!");

// Copy a file
const input = Bun.file("input.txt");
await Bun.write("output.txt", input);

// Write binary data
const encoder = new TextEncoder();
const data = encoder.encode("binary data");
await Bun.write("output.bin", data);

// Write a fetch response directly to disk
const response = await fetch("https://example.com");
await Bun.write("page.html", response);

// Write to stdout
await Bun.write(Bun.stdout, "printed to terminal\n");
```

### Incremental Writing (FileSink)

For large or streaming writes, use the `FileSink` API:

```js
const file = Bun.file("output.txt");
const writer = file.writer();

writer.write("first line\n");
writer.write("second line\n");

writer.flush();  // flush buffer to disk
writer.end();    // close the writer
```

## Package Manager

Bun includes a fast, npm-compatible package manager.

```bash
bun install              # Install all dependencies
bun add express          # Add a package
bun add -d typescript    # Add a dev dependency
bun remove express       # Remove a package
bun update               # Update all packages
```

Bun uses a binary lockfile (`bun.lock`) for faster installs. It reads `package.json` and is compatible with npm registries.

## Bundler

Bun includes a JavaScript/TypeScript bundler:

```bash
bun build ./src/index.ts --outdir ./dist
```

```js
// Programmatic API
const result = await Bun.build({
  entrypoints: ["./src/index.ts"],
  outdir: "./dist",
  target: "browser",     // "browser" | "bun" | "node"
  minify: true,
  sourcemap: "external",
});

for (const artifact of result.outputs) {
  console.log(artifact.path);
}
```

## Test Runner

Bun has a built-in test runner compatible with Jest-like syntax:

```bash
bun test                    # Run all tests
bun test --watch            # Watch mode
bun test tests/auth.test.ts # Run specific file
```

```ts
import { describe, it, expect } from "bun:test";

describe("math", () => {
  it("adds numbers", () => {
    expect(2 + 2).toBe(4);
  });

  it("handles async", async () => {
    const result = await Promise.resolve(42);
    expect(result).toBe(42);
  });
});
```

## Environment Variables

Bun automatically loads `.env` files:

```bash
# .env
DATABASE_URL=postgres://localhost:5432/mydb
API_KEY=secret123
```

```js
// Access via Bun.env or process.env
console.log(Bun.env.DATABASE_URL);
console.log(process.env.API_KEY);
```

Priority order: `.env.local` > `.env.development` / `.env.production` > `.env`

## Shell (Bun.$)

Bun includes a cross-platform shell API for running commands:

```js
import { $ } from "bun";

// Run a command
const result = await $`ls -la`;
console.log(result.text());

// Pipe commands
await $`cat file.txt | grep "pattern"`;

// With variables (auto-escaped)
const name = "my file.txt";
await $`cat ${name}`;
```
