import { createHash } from 'node:crypto';
import { classifyRisks, applyCrossStack } from './risk-classifier.mjs';
import { matchRoutes } from './routing.mjs';

const classifications = new Set(['public', 'internal', 'confidential', 'restricted']);

function unique(values) {
  return [...new Set(values)];
}

function ordered(values, catalog) {
  const positions = new Map(catalog.map((agent, index) => [agent, index]));
  return unique(values).sort((left, right) => positions.get(left) - positions.get(right));
}

function reasons(match) {
  return {
    keywords: match.reasons.keywords,
    paths: match.reasons.paths
  };
}

function selectWorkflow(routeIds, riskIds, hasAgents) {
  if (!hasAgents) return 'needs-triage';
  if (riskIds.includes('production')) return 'production-release';
  if (routeIds.includes('knowledge-store') && routeIds.every((id) => ['knowledge-store', 'documentation', 'testing'].includes(id))) {
    return 'knowledge-ingestion';
  }
  if (routeIds.includes('infrastructure') && !routeIds.some((id) => ['frontend', 'backend', 'pipeline'].includes(id))) {
    return 'infrastructure-change';
  }
  if (routeIds.includes('pipeline') && !routeIds.some((id) => ['frontend', 'backend', 'infrastructure'].includes(id))) {
    return 'pipeline-change';
  }
  return 'new-service';
}

function buildHumanGates(risks) {
  const descriptions = {
    'persistent-database-migration': 'An authorized human must approve persistent database migrations.',
    'production-change': 'An authorized human must approve the exact production change and target.',
    'destructive-action': 'An authorized human must approve the exact destructive action and recovery plan.'
  };
  return unique(risks.map((risk) => risk.rule.human_gate).filter(Boolean)).map((id) => ({
    id,
    required: true,
    reason: descriptions[id] ?? 'An authorized human decision is required.'
  }));
}

function buildKnowledgeContext(config, selectedAgents, input) {
  if (!selectedAgents.length) return { status: 'not-applicable', requests: [] };
  if (!input.classification) {
    return {
      status: 'authorization-required',
      reason: 'Provide an authorized classification and scope before retrieval.',
      requests: []
    };
  }
  if (!classifications.has(input.classification)) {
    throw new Error(`Invalid classification: ${input.classification}`);
  }
  const requests = selectedAgents.map((agent) => {
    const focus = config.knowledge_focus[agent];
    if (!focus) throw new Error(`Missing knowledge focus for selected agent: ${agent}`);
    const query = `Task: ${input.task}. Retrieve ${focus}.`;
    const args = [
      'run', 'knowledge-store', '--', 'context',
      '--agent', agent,
      '--task-id', input.taskId,
      '--query', query,
      '--classification', input.classification,
      '--top', String(input.top ?? 5)
    ];
    if (input.source) args.push('--source', input.source);
    return {
      agent,
      query,
      invocation: {
        cwd: 'agents/knowledge-store',
        executable: 'npm',
        args
      }
    };
  });
  return {
    status: 'planned',
    classification: input.classification,
    source_filter: input.source ?? null,
    requests
  };
}

function validateAgents(groups, catalog) {
  const known = new Set(catalog);
  for (const agent of [...groups.primary, ...groups.reviewers, ...groups.support]) {
    if (!known.has(agent)) throw new Error(`Routing selected an unknown agent: ${agent}`);
  }
}

export function buildDispatchPlan(config, catalog, input) {
  const matchedRoutes = matchRoutes(config, input.task, input.changedFiles);
  const matchedRisks = classifyRisks(config, input.task, input.changedFiles);
  const primary = matchedRoutes.flatMap((match) => match.rule.primary ?? []);
  const reviewers = matchedRoutes.flatMap((match) => match.rule.reviewers ?? []);
  const support = matchedRoutes.flatMap((match) => match.rule.support ?? []);
  for (const risk of matchedRisks) {
    primary.push(...(risk.rule.primary ?? []));
    reviewers.push(...(risk.rule.reviewers ?? []));
    support.push(...(risk.rule.support ?? []));
  }
  support.push(...applyCrossStack(config, matchedRoutes));

  const groups = {
    primary: ordered(primary, catalog),
    reviewers: ordered(reviewers, catalog),
    support: ordered(support, catalog)
  };
  groups.reviewers = groups.reviewers.filter((agent) => !groups.primary.includes(agent));
  groups.support = groups.support.filter((agent) => !groups.primary.includes(agent) && !groups.reviewers.includes(agent));
  validateAgents(groups, catalog);

  const selectedAgents = ordered([...groups.primary, ...groups.reviewers, ...groups.support], catalog);
  const hasAgents = selectedAgents.length > 0;
  const workflow = selectWorkflow(
    matchedRoutes.map((route) => route.id),
    matchedRisks.map((risk) => risk.id),
    hasAgents
  );
  const taskId = input.taskId ?? `local-${createHash('sha256').update(`${input.task}\n${input.changedFiles.join('\n')}`).digest('hex').slice(0, 12)}`;
  const normalizedInput = { ...input, taskId };

  return {
    schema_version: 1,
    task_id: taskId,
    generated_at: new Date().toISOString(),
    status: hasAgents ? 'ready' : 'needs-triage',
    workflow,
    inputs: {
      task: input.task,
      base: input.base ?? null,
      changed_file_source: input.changedFileSource,
      changed_files: input.changedFiles,
      classification: input.classification ?? null,
      source_filter: input.source ?? null
    },
    matched_routes: matchedRoutes.map((match) => ({ id: match.id, reasons: reasons(match) })),
    matched_risks: matchedRisks.map((match) => ({ id: match.id, reasons: reasons(match) })),
    agents: groups,
    human_gates: buildHumanGates(matchedRisks),
    knowledge_context: buildKnowledgeContext(config, selectedAgents, normalizedInput)
  };
}
