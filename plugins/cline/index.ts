import { execFile } from "node:child_process";
import { promisify } from "node:util";
import { z } from "zod";
import { type AgentPlugin, createTool } from "@cline/sdk";

const execFileAsync = promisify(execFile);

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
type SetupApi = Parameters<SetupFn>[0];
type SetupContext = Parameters<SetupFn>[1];

const setup = (api: SetupApi, ctx: SetupContext) => {
  const rootPath = ctx.workspaceInfo?.rootPath;

  api.registerTool(
    createTool({
      name: "agents_select",
      description:
        "Get a deterministic, reviewable agent dispatch plan from this repository's Secure Cloud Agents catalog " +
        "(routes, primary/reviewer/support roles, quality gates). Plan only: never invokes agents, retrieves " +
        "knowledge, merges, deploys, or mutates infrastructure or approvals. Requires the current workspace to " +
        "be a checkout of the deagy/agents repository (or a project with its own catalog.yaml).",
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
            "./bin/agents",
            buildSelectArgs(input, rootPath),
            { cwd: rootPath },
          );
          return JSON.parse(stdout) as Record<string, unknown>;
        } catch (caught) {
          const err = caught as { message?: string; stderr?: string };
          return {
            error: err.message ?? "agents select failed",
            stderr: err.stderr,
          };
        }
      },
    }),
  );
};

const plugin: AgentPlugin = {
  name: "secure-cloud-agents",
  manifest: { capabilities: ["tools"] },
  setup,
};

export { plugin };
export default plugin;
