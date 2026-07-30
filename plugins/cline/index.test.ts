import { describe, expect, it } from "vitest";
import { fileURLToPath } from "node:url";
import path from "node:path";
import type { AgentTool } from "@cline/sdk";
import { plugin, type SetupApi, type SetupContext } from "./index.ts";

const PLUGIN_DIR = path.dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = path.resolve(PLUGIN_DIR, "..", "..");

async function registerTools(workspaceRootPath: string | undefined) {
  const tools: AgentTool[] = [];
  const api: SetupApi = {
    registerTool: (tool: AgentTool) => {
      tools.push(tool);
    },
    registerCommand: () => {},
    registerRule: () => {},
    registerMessageBuilder: () => {},
    registerProvider: () => {},
    registerAutomationEventType: () => {},
    registerMcpServer: () => {},
  };
  const ctx: SetupContext = {
    workspaceInfo: workspaceRootPath ? { rootPath: workspaceRootPath } : undefined,
  };
  await plugin.setup?.(api, ctx);
  return tools;
}

function findTool(tools: AgentTool[], name: string): AgentTool {
  const tool = tools.find((t) => t.name === name);
  if (!tool) throw new Error(`tool ${name} was not registered`);
  return tool;
}

describe("cadre plugin", () => {
  it("declares the tools capability and registers exactly one tool: agents_select", async () => {
    expect(plugin.manifest.capabilities).toEqual(["tools"]);

    const tools = await registerTools(REPO_ROOT);
    expect(tools.map((t) => t.name)).toEqual(["agents_select"]);
    expect(tools[0].description).toMatch(/plan only/i);
    expect(tools[0].description).toMatch(/never invokes agents/i);
    // The Cline plugin API has no spawn/team primitive available to a
    // registered tool's execute() (see runner-adapters.md's "## Cline"
    // section); the description must say so rather than imply this tool
    // dispatches anything.
    expect(tools[0].description).toMatch(/cannot.*dispatch/i);
    expect(tools[0].description).toMatch(/runner-adapters\.md/);
  });

  it("agents_select returns a real dispatch plan for this repository", async () => {
    const tools = await registerTools(REPO_ROOT);
    const tool = findTool(tools, "agents_select");

    const result = (await tool.execute(
      { task: "Review README changes", files: "README.md", classification: "internal" },
      {} as never,
    )) as Record<string, unknown>;

    expect(result.error).toBeUndefined();
    expect(result).toHaveProperty("status");
    expect(result).toHaveProperty("agents");
    expect(result).toHaveProperty("matched_routes");
  });

  it("agents_select honors an explicit taskId in the returned plan", async () => {
    const tools = await registerTools(REPO_ROOT);
    const tool = findTool(tools, "agents_select");

    const result = (await tool.execute(
      {
        task: "Review README changes",
        files: "README.md",
        classification: "internal",
        taskId: "PLUGIN-TEST-TASK-ID",
      },
      {} as never,
    )) as Record<string, unknown>;

    expect(result.error).toBeUndefined();
    expect(result.task_id).toBe("PLUGIN-TEST-TASK-ID");
  });

  it("agents_select returns needs-triage for a scope with no matching route", async () => {
    const tools = await registerTools(REPO_ROOT);
    const tool = findTool(tools, "agents_select");

    // An explicit file with no keyword/path match in routing.yaml, and task text with
    // no routable keywords either, gives the selector nothing to route on. Pinning
    // --files (rather than omitting it) avoids the selector's own git-status fallback,
    // which would otherwise make this depend on the caller's dirty working tree.
    const result = (await tool.execute(
      { task: "xyzzy plugh", files: "no-such-extension.zzz" },
      {} as never,
    )) as Record<string, unknown>;

    expect(result.error).toBeUndefined();
    expect(result.status).toBe("needs-triage");
  });

  it("agents_select surfaces a real CLI failure as a structured error, not a throw", async () => {
    const tools = await registerTools(REPO_ROOT);
    const tool = findTool(tools, "agents_select");

    // select_agents.py rejects --base combined with --files with a non-zero exit;
    // this exercises the execFile non-zero-exit branch of the shared catch block
    // (distinct from the JSON.parse-failure branch and the missing-rootPath guard),
    // and incidentally covers the --base flag, which no other test passes.
    const result = (await tool.execute(
      { task: "test", files: "README.md", base: "main" },
      {} as never,
    )) as Record<string, unknown>;

    expect(typeof result.error).toBe("string");
    expect(result.error).toMatch(/--base cannot be combined with --files/);
  });

  it("agents_select returns a structured error when the workspace root could not be resolved", async () => {
    const tools = await registerTools(undefined);
    const tool = findTool(tools, "agents_select");

    const result = (await tool.execute({ task: "anything" }, {} as never)) as Record<
      string,
      unknown
    >;

    expect(typeof result.error).toBe("string");
    expect(result.error).toMatch(/workspace root/i);
  });

  it("agents_select result is fully re-serializable (sanitizeToolResult guards against cycles)", async () => {
    const tools = await registerTools(REPO_ROOT);
    const tool = findTool(tools, "agents_select");

    const result = (await tool.execute(
      { task: "Review README changes", files: "README.md", classification: "internal" },
      {} as never,
    )) as Record<string, unknown>;

    // The sanitizeToolResult wrapper must produce a result that can be
    // round-tripped through JSON.stringify without throwing — this is the
    // contract that protects against downstream SDK hooks injecting circular
    // references (e.g., Error objects with e.error === e).
    expect(() => JSON.stringify(result)).not.toThrow();

    // And the round-trip must preserve the data.
    const reparsed = JSON.parse(JSON.stringify(result));
    expect(reparsed).toEqual(result);
  });

  it("agents_select result is a plain object with no hidden properties", async () => {
    const tools = await registerTools(REPO_ROOT);
    const tool = findTool(tools, "agents_select");

    const result = (await tool.execute(
      { task: "Review README changes", files: "README.md", classification: "internal" },
      {} as never,
    )) as Record<string, unknown>;

    // sanitizeToolResult re-parses through JSON, which strips functions,
    // symbols, and undefined values. The result must be a plain object.
    expect(Object.getPrototypeOf(result)).toBe(Object.prototype);
  });
});
