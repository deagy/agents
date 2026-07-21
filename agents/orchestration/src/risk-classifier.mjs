import { matchRule } from './routing.mjs';

export function classifyRisks(config, taskText, changedFiles) {
  return config.risk_rules.flatMap((risk) => {
    const reasons = matchRule(risk, taskText, changedFiles);
    return reasons.matched ? [{ id: risk.id, reasons, rule: risk }] : [];
  });
}

export function applyCrossStack(config, matchedRoutes) {
  const crossStack = config.cross_stack;
  if (!crossStack) return [];
  const relevant = matchedRoutes.filter((route) => crossStack.route_ids.includes(route.id));
  if (relevant.length < crossStack.minimum_matches) return [];
  return crossStack.support ?? [];
}
