import test from 'node:test';
import assert from 'node:assert/strict';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { spawnSync } from 'node:child_process';
import { buildDispatchPlan } from '../src/build-dispatch-plan.mjs';
import { globToRegex, loadCatalog, loadRouting } from '../src/routing.mjs';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const agentsRoot = path.resolve(root, '..');
const config = loadRouting(path.join(root, 'routing.yaml'));
const catalog = loadCatalog(path.join(agentsRoot, 'catalog.yaml'));

function plan(overrides = {}) {
  return buildDispatchPlan(config, catalog, {
    task: 'Change the application',
    changedFiles: [],
    changedFileSource: 'test',
    ...overrides
  });
}

test('glob matching supports root and nested paths', () => {
  assert.equal(globToRegex('**/*.go').test('main.go'), true);
  assert.equal(globToRegex('**/*.go').test('services/api/main.go'), true);
  assert.equal(globToRegex('terraform/**').test('terraform/modules/vm/main.tf'), true);
  assert.equal(globToRegex('.gitlab-ci.yml').test('.gitlab-ci.yml'), true);
  assert.equal(globToRegex('**/*.go').test('main.ts'), false);
});

test('selects frontend and backend agents with cross-stack coordination', () => {
  const result = plan({
    task: 'Add a React upload form backed by a PostgreSQL API',
    changedFiles: ['frontend/src/Upload.tsx', 'services/upload/main.go'],
    classification: 'internal',
    taskId: 'APP-42'
  });
  assert.equal(result.status, 'ready');
  assert.equal(result.workflow, 'new-service');
  assert.deepEqual(result.agents.primary, ['frontend-engineer', 'backend-engineer']);
  assert.ok(result.agents.reviewers.includes('test-engineer'));
  assert.ok(result.agents.reviewers.includes('code-reviewer'));
  assert.ok(result.agents.support.includes('application-engineer'));
  assert.equal(result.knowledge_context.status, 'planned');
  assert.ok(result.knowledge_context.requests.some((request) => request.agent === 'frontend-engineer'));
  assert.ok(result.knowledge_context.requests.every((request) => request.invocation.args.includes('APP-42')));
  assert.ok(result.knowledge_context.requests.every((request) => !/[\r\n]/.test(request.query)));
});

test('adds security roles for authentication work', () => {
  const result = plan({
    task: 'Add OIDC authentication and session handling to the React frontend',
    changedFiles: ['frontend/src/auth/session.ts']
  });
  assert.ok(result.agents.primary.includes('frontend-engineer'));
  assert.ok(result.agents.support.includes('threat-modeler'));
  assert.ok(result.agents.reviewers.includes('security-reviewer'));
  assert.equal(result.knowledge_context.status, 'authorization-required');
});

test('selects infrastructure workflow and independent review', () => {
  const result = plan({
    task: 'Update Terraform for a Proxmox worker VM',
    changedFiles: ['terraform/modules/worker/main.tf']
  });
  assert.equal(result.workflow, 'infrastructure-change');
  assert.deepEqual(result.agents.primary, ['infrastructure-provisioner']);
  assert.deepEqual(result.agents.reviewers, ['infrastructure-reviewer']);
});

test('adds human gates for production database migrations', () => {
  const result = plan({
    task: 'Run a production database migration that alters the users table',
    changedFiles: ['services/users/migrations/0042_users.sql']
  });
  assert.equal(result.workflow, 'production-release');
  assert.ok(result.agents.primary.includes('backend-engineer'));
  assert.ok(result.agents.support.includes('release-engineer'));
  assert.deepEqual(
    result.human_gates.map((gate) => gate.id),
    ['persistent-database-migration', 'production-change']
  );
});

test('returns needs-triage instead of guessing', () => {
  const result = plan({
    task: 'Investigate an unexplained issue',
    changedFiles: ['unknown/file.xyz']
  });
  assert.equal(result.status, 'needs-triage');
  assert.equal(result.workflow, 'needs-triage');
  assert.deepEqual(result.agents, { primary: [], reviewers: [], support: [] });
});

test('CLI emits a valid plan for explicit files', () => {
  const result = spawnSync(process.execPath, [
    path.join(root, 'src', 'select-agents.mjs'),
    '--task', 'Change the GitLab pipeline runner configuration',
    '--files', '.gitlab-ci.yml',
    '--classification', 'internal',
    '--task-id', 'CI-7'
  ], { cwd: path.resolve(agentsRoot, '..'), encoding: 'utf8' });
  assert.equal(result.status, 0, result.stderr);
  const output = JSON.parse(result.stdout);
  assert.equal(output.task_id, 'CI-7');
  assert.equal(output.workflow, 'pipeline-change');
  assert.ok(output.agents.primary.includes('cicd-engineer'));
  assert.ok(output.agents.reviewers.includes('pipeline-security-reviewer'));
});
