import fs from 'node:fs';

function escapeRegex(value) {
  return value.replace(/[|\\{}()[\]^$+?.]/g, '\\$&');
}

export function globToRegex(pattern) {
  const normalized = pattern.replaceAll('\\', '/');
  let expression = '^';
  for (let index = 0; index < normalized.length; index += 1) {
    const character = normalized[index];
    if (character === '*' && normalized[index + 1] === '*') {
      index += 1;
      if (normalized[index + 1] === '/') {
        index += 1;
        expression += '(?:.*/)?';
      } else {
        expression += '.*';
      }
    } else if (character === '*') {
      expression += '[^/]*';
    } else if (character === '?') {
      expression += '[^/]';
    } else {
      expression += escapeRegex(character);
    }
  }
  return new RegExp(`${expression}$`, 'i');
}

function keywordMatches(text, keyword) {
  const escaped = escapeRegex(keyword.toLowerCase()).replaceAll('\\ ', '\\s+');
  return new RegExp(`(^|[^a-z0-9])${escaped}([^a-z0-9]|$)`, 'i').test(text);
}

export function matchRule(rule, taskText, changedFiles) {
  const normalizedTask = taskText.toLowerCase();
  const matchedKeywords = (rule.keywords ?? []).filter((keyword) => keywordMatches(normalizedTask, keyword));
  const matchedPaths = [];
  for (const pattern of rule.paths ?? []) {
    const matcher = globToRegex(pattern);
    for (const file of changedFiles) {
      if (matcher.test(file.replaceAll('\\', '/'))) matchedPaths.push({ pattern, file });
    }
  }
  return {
    matched: matchedKeywords.length > 0 || matchedPaths.length > 0,
    keywords: matchedKeywords,
    paths: matchedPaths
  };
}

export function loadRouting(filePath) {
  const config = JSON.parse(fs.readFileSync(filePath, 'utf8'));
  if (config.version !== 1 || !Array.isArray(config.routes) || !Array.isArray(config.risk_rules)) {
    throw new Error('routing.yaml must contain version 1 routes and risk_rules');
  }
  const ids = [...config.routes, ...config.risk_rules].map((rule) => rule.id);
  if (new Set(ids).size !== ids.length) throw new Error('Routing and risk rule IDs must be unique');
  return config;
}

export function loadCatalog(filePath) {
  const content = fs.readFileSync(filePath, 'utf8');
  const agents = [];
  for (const line of content.split(/\r?\n/)) {
    const match = line.match(/^  ([a-z0-9-]+):\s*$/);
    if (match) agents.push(match[1]);
  }
  if (!agents.length) throw new Error('No agents found in catalog.yaml');
  return agents;
}

export function matchRoutes(config, taskText, changedFiles) {
  return config.routes.flatMap((route) => {
    const reasons = matchRule(route, taskText, changedFiles);
    return reasons.matched ? [{ id: route.id, reasons, rule: route }] : [];
  });
}
