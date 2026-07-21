#!/usr/bin/env node
import fs from 'node:fs';
import path from 'node:path';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { buildDispatchPlan } from './build-dispatch-plan.mjs';
import { loadCatalog, loadRouting } from './routing.mjs';

const orchestrationRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const agentsRoot = path.resolve(orchestrationRoot, '..');
const repositoryRoot = path.resolve(agentsRoot, '..');

function parseArgs(argv) {
  const options = {};
  for (let index = 0; index < argv.length; index += 1) {
    const item = argv[index];
    if (!item.startsWith('--')) throw new Error(`Unexpected argument: ${item}`);
    const key = item.slice(2).replaceAll('-', '_');
    const value = argv[index + 1];
    if (!value || value.startsWith('--')) options[key] = true;
    else {
      if (options[key] === undefined) options[key] = value;
      else options[key] = [...(Array.isArray(options[key]) ? options[key] : [options[key]]), value];
      index += 1;
    }
  }
  return options;
}

function runGit(args) {
  const result = spawnSync('git', args, { cwd: repositoryRoot, encoding: 'utf8' });
  if (result.status !== 0) throw new Error(result.stderr.trim() || `git ${args.join(' ')} failed`);
  return result.stdout;
}

function discoverChangedFiles(base) {
  if (base) {
    return {
      source: `git-diff:${base}...HEAD`,
      files: runGit(['diff', '--name-only', `${base}...HEAD`]).split(/\r?\n/).filter(Boolean)
    };
  }
  const lines = runGit(['status', '--short']).split(/\r?\n/).filter(Boolean);
  return {
    source: 'git-status',
    files: lines.map((line) => {
      const value = line.slice(3).trim();
      return value.includes(' -> ') ? value.split(' -> ').at(-1) : value;
    })
  };
}

function explicitFiles(value) {
  if (!value) return null;
  const values = Array.isArray(value) ? value : [value];
  return [...new Set(values.flatMap((entry) => entry.split(',')).map((entry) => entry.trim()).filter(Boolean))];
}

function usage() {
  return `Usage:
  node src/select-agents.mjs --task <text> [--files <path[,path]>] [--base <ref>]
    [--task-id <id>] [--classification <level>] [--source <knowledge-source>]
    [--top <n>] [--output <file>]`;
}

function main() {
  const options = parseArgs(process.argv.slice(2));
  if (options.help) { console.log(usage()); return; }
  if (!options.task || typeof options.task !== 'string') throw new Error('--task is required');
  const suppliedFiles = explicitFiles(options.files);
  const changes = suppliedFiles
    ? { source: 'explicit', files: suppliedFiles }
    : discoverChangedFiles(options.base);
  const config = loadRouting(path.join(orchestrationRoot, 'routing.yaml'));
  const catalog = loadCatalog(path.join(agentsRoot, 'catalog.yaml'));
  const plan = buildDispatchPlan(config, catalog, {
    task: options.task,
    taskId: options.task_id,
    base: options.base,
    changedFiles: changes.files.map((file) => file.replaceAll('\\', '/')),
    changedFileSource: changes.source,
    classification: options.classification,
    source: options.source,
    top: options.top
  });
  const serialized = `${JSON.stringify(plan, null, 2)}\n`;
  if (options.output) {
    const outputPath = path.resolve(process.cwd(), options.output);
    fs.mkdirSync(path.dirname(outputPath), { recursive: true });
    fs.writeFileSync(outputPath, serialized, 'utf8');
  } else {
    process.stdout.write(serialized);
  }
}

try {
  main();
} catch (error) {
  console.error(error.message);
  process.exitCode = 1;
}
