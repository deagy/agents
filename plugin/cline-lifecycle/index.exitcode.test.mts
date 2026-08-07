import { afterEach, describe, expect, it, vi } from "vitest";
import { promisify } from "node:util";

// This file exists solely to test runCadreSdlcAllowingReportExitCodes's one
// distinguishing behavior: parsing `err.stdout` as JSON when the kernel
// subprocess exits nonzero, versus falling back to the generic error shape.
// index.test.mts's "real bin/cadre sdlc subprocess calls" tests can't
// reliably exercise this -- the only deterministic live scenario (a
// nonexistent task) always produces a stderr-only exit 1, never the
// exit-2-with-JSON-on-stdout shape this helper exists to handle (confirmed
// during PR #34's review). node:child_process is mocked at module level, so
// this file must stay separate from index.test.mts, which does a real,
// unmocked import of index.ts for its own tests.
//
// index.ts calls `promisify(execFile)`, and Node's real `child_process`
// module tags its `execFile` export with `util.promisify.custom` so that
// promisified call resolves to `{stdout, stderr}` on success and rejects
// with an error object carrying `.stdout`/`.stderr` on a nonzero exit --
// generic util.promisify (single-callback-arg convention) does not produce
// that shape on its own. The mock below replicates that custom binding
// directly rather than relying on generic promisify semantics, so it
// exercises the exact same resolution path the real module provides.

const execFileMock = vi.hoisted(() => vi.fn());

vi.mock("node:child_process", () => {
  const execFile = (
    file: string,
    args: string[],
    options: unknown,
    callback: (error: unknown, stdout: string, stderr: string) => void,
  ) => execFileMock(file, args, options, callback);
  Object.defineProperty(execFile, promisify.custom, {
    value: (file: string, args: string[], options: unknown) =>
      new Promise((resolve, reject) => {
        execFileMock(file, args, options, (error: (Error & { stdout?: string; stderr?: string }) | null, stdout: string, stderr: string) => {
          if (error) {
            error.stdout = stdout;
            error.stderr = stderr;
            reject(error);
          } else {
            resolve({ stdout, stderr });
          }
        });
      }),
  });
  return { execFile };
});

const { runCadreSdlcAllowingReportExitCodes } = await import("./index.ts");

afterEach(() => {
  execFileMock.mockReset();
});

function mockNonzeroExit(exitCode: number, stdout: string, stderr: string) {
  execFileMock.mockImplementation((_file, _args, _options, callback) => {
    const error = new Error("") as Error & { code: number };
    error.code = exitCode;
    callback(error, stdout, stderr);
  });
}

describe("runCadreSdlcAllowingReportExitCodes", () => {
  it("relays a parseable JSON report on stdout from a nonzero exit (the exit-2 case)", async () => {
    const report = { status: "ok", refusals: [{ reason: "no-verified-account" }], plan_digest: "sha256:abc" };
    mockNonzeroExit(2, JSON.stringify(report), "");

    const result = await runCadreSdlcAllowingReportExitCodes(["sdlc", "create-gate-issues"], "/root");

    expect(result).toEqual(report);
    expect(execFileMock).toHaveBeenCalledTimes(1);
  });

  it("falls back to the generic error shape when stdout is empty on a nonzero exit (the GateIssuesBlocked case)", async () => {
    mockNonzeroExit(2, "", '{"error": "plan digest is stale"}');

    const result = await runCadreSdlcAllowingReportExitCodes(["sdlc", "create-gate-issues"], "/root");

    expect(result).toEqual({
      error: '{"error": "plan digest is stale"}',
      stderr: '{"error": "plan digest is stale"}',
    });
  });

  it("falls back to the generic error shape when stdout is present but not valid JSON", async () => {
    mockNonzeroExit(1, "not json at all", "usage: agentic-sdlc create-gate-issues [-h] ...");

    const result = await runCadreSdlcAllowingReportExitCodes(["sdlc", "create-gate-issues"], "/root");

    expect(result).toEqual({
      error: "usage: agentic-sdlc create-gate-issues [-h] ...",
      stderr: "usage: agentic-sdlc create-gate-issues [-h] ...",
    });
  });

  it("returns the parsed stdout directly on a clean (zero) exit", async () => {
    const report = { status: "ok", refusals: [] };
    execFileMock.mockImplementation((_file, _args, _options, callback) => {
      callback(null, JSON.stringify(report), "");
    });

    const result = await runCadreSdlcAllowingReportExitCodes(["sdlc", "create-gate-issues"], "/root");

    expect(result).toEqual(report);
  });
});
