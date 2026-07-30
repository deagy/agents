import { execFile } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { promisify } from "node:util";
import { z } from "zod";
import { type AgentPlugin, createTool } from "@cline/sdk";
import { safeJsonStringify } from "@cline/shared";

const execFileAsync = promisify(execFile);

// Resolved from this module's own location, not the target workspace: the
// `cadre` CLI lives at <this plugin's checkout>/bin/cadre regardless of which
// project's rootPath the tool is invoked against. Resolving it relative to
// rootPath instead (as a bare "./bin/cadre" with `cwd: rootPath`) only works
// when rootPath happens to be this repository itself, and fails closed with
// ENOENT in every other consumer project.
const PLUGIN_DIR = path.dirname(fileURLToPath(import.meta.url));
const CADRE_BIN = path.resolve(PLUGIN_DIR, "..", "..", "bin", "cadre");

const AgentsSelectInputSchema = z.object({
  task: z
    .string()
    .describe("Task objective used for deterministic routing (required)."),
  files: z
    .string()
    .optional()
    .describe("Changed path, or comma-separated paths, to scope the plan to."),
  base: z
    .string()
    .optional()
    .describe("Git base ref used with <base>...HEAD for committed changes."),
  taskId: z
    .string()
    .optional()
    .describe("Stable caller-supplied task identifier. Omit to let the selector derive one."),
  classification: z
    .string()
    .optional()
    .describe("Authorized knowledge classification for this task, if known."),
  requireSdlc: z
    .boolean()
    .optional()
    .describe("Fail instead of degrading to standalone mode if Agentic SDLC isn't available."),
});

type AgentsSelectInput = z.infer<typeof AgentsSelectInputSchema>;

interface AgentsSelectError {
  error: string;
  stderr?: string;
}

function buildSelectArgs(input: AgentsSelectInput, rootPath: string): string[] {
  const args = ["select", "--root", rootPath, "--task", input.task];
  if (input.files) args.push("--files", input.files);
  if (input.base) args.push("--base", input.base);
  if (input.taskId) args.push("--task-id", input.taskId);
  if (input.classification) args.push("--classification", input.classification);
  if (input.requireSdlc) args.push("--require-sdlc");
  return args;
}

type SetupFn = NonNullable<AgentPlugin["setup"]>;
export type SetupApi = Parameters<SetupFn>[0];
export type SetupContext = Parameters<SetupFn>[1];
export type { AgentsSelectInput, AgentsSelectError };

/**
 * Sanitize a tool result to ensure it is fully JSON-serializable without
 * circular references, hidden properties, or non-JSON values (functions,
 * symbols, undefined). Uses the SDK's safeJsonStringify which detects and
 * replaces cycles with "[Circular]" rather than throwing.
 */
function sanitizeToolResult(input: unknown): Record<string, unknown> | AgentsSelectError {
  try {
    return JSON.parse(safeJsonStringify(input)) as Record<string, unknown>;
  } catch {
    return { error: "agents_select failed: result could not be serialized" };
  }
}

const setup = (api: SetupApi, ctx: SetupContext) => {
  const rootPath = ctx.workspaceInfo?.rootPath;

  api.registerTool(
    createTool({
      name: "agents_select",
      description:
        "Get a deterministic, reviewable agent dispatch plan from this repository's Cadre catalog " +
        "(routes, primary/reviewer/support roles, quality gates). Plan only: never invokes agents, retrieves " +
        "knowledge, merges, deploys, or mutates infrastructure or approvals. Requires the current workspace to " +
        "be a checkout of the deagy/cadre repository (or a project with its own catalog.yaml). This plugin " +
        "does not (and, with the Cline plugin API as currently published, cannot) dispatch the selected " +
        "role(s) itself — a Cline plugin's setup(api, ctx) only exposes registerTool/registerCommand/etc., " +
        "not the session's spawn-agent or team primitives. After calling this tool, the orchestrating Cline " +
        "session must dispatch manually: see the \"## Cline\" section of " +
        ".agents/skills/run-agent-orchestration/references/runner-adapters.md for the current manual-" +
        "injection workaround and /team limitations.",
      inputSchema: AgentsSelectInputSchema,
      execute: async (input: AgentsSelectInput): Promise<Record<string, unknown> | AgentsSelectError> => {
        if (!rootPath) {
          return {
            error:
              "Could not resolve the workspace root from the host session; agents_select requires a known " +
              "workspace root and will not fall back to the process's current directory.",
          };
        }

        try {
          const { stdout } = await execFileAsync(
            CADRE_BIN,
            buildSelectArgs(input, rootPath),
            { cwd: rootPath },
          );
          return sanitizeToolResult(JSON.parse(stdout));
        } catch (caught) {
          const err = caught as { message?: string; stderr?: string };
          return sanitizeToolResult({
            error: [err.stderr?.trim(), err.message].filter(Boolean).join("\n") || "agents_select failed",
            stderr: err.stderr,
          }) as AgentsSelectError;
        }
      },
    }),
  );
};

const plugin: AgentPlugin = {
  name: "cadre",
  manifest: { capabilities: ["tools"] },
  setup,
};

export { plugin };
export default plugin;
