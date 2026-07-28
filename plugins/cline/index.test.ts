import { describe, expect, it } from "vitest";
import { fileURLToPath } from "node:url";
import path from "node:path";
import type { AgentTool } from "@cline/sdk";
import { plugin } from "./index.ts";

const PLUGIN_DIR = path.dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = path.resolve(PLUGIN_DIR, "..", "..");

async function registerTools(workspaceRootPath: string | undefined) {
  const tools: AgentTool[] = [];
  const api = {
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
  const ctx = {
    workspaceInfo: workspaceRootPath ? { rootPath: workspaceRootPath } : undefined,
  };
  await plugin.setup?.(api as never, ctx as never);
  return tools;
}

function findTool(tools: AgentTool[], name: string): AgentTool {
  const tool = tools.find((t) => t.name === name);
  if (!tool) throw new Error(`tool ${name} was not registered`);
  return tool;
}

describe("secure-cloud-agents plugin", () => {
  it("registers exactly one tool: agents_select", async () => {
    const tools = await registerTools(REPO_ROOT);
    expect(tools.map((t) => t.name)).toEqual(["agents_select"]);
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
});
