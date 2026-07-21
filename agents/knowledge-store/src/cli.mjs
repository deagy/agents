#!/usr/bin/env node
import { loadConfig } from './config.mjs';
import { openStore, storeStats } from './database.mjs';
import { ingestFile, searchStore, stableQueryId } from './service.mjs';

function parseArgs(argv) {
  const [command, ...rest] = argv;
  const options = {};
  for (let index = 0; index < rest.length; index += 1) {
    const item = rest[index];
    if (!item.startsWith('--')) throw new Error(`Unexpected argument: ${item}`);
    const key = item.slice(2).replaceAll('-', '_');
    const value = rest[index + 1];
    if (!value || value.startsWith('--')) options[key] = true;
    else { options[key] = value; index += 1; }
  }
  return { command, options };
}

function usage() {
  return `Usage:
  node src/cli.mjs init [--config <path>]
  node src/cli.mjs ingest --input <file> [--source <name>] [--classification <level>] [--config <path>]
  node src/cli.mjs search --query <text> --classification <level> [--top <n>] [--source <name>] [--config <path>]
  node src/cli.mjs stats [--config <path>]`;
}

async function main() {
  const { command, options } = parseArgs(process.argv.slice(2));
  if (!command || options.help) { console.log(usage()); return; }
  const config = loadConfig(options.config);
  const db = openStore(config.database);
  try {
    if (command === 'init') {
      console.log(JSON.stringify({ status: 'initialized', database: config.database }, null, 2));
      return;
    }
    if (command === 'ingest') {
      if (!options.input) throw new Error('--input is required');
      const result = await ingestFile(db, config, {
        input: options.input,
        source: options.source ?? 'chat-export',
        classification: options.classification ?? config.ingestion.default_classification
      });
      console.log(JSON.stringify(result, null, 2));
      return;
    }
    if (command === 'search') {
      if (!options.query) throw new Error('--query is required');
      if (!options.classification) throw new Error('--classification is required');
      const results = await searchStore(db, config, options.query, options);
      console.log(JSON.stringify({ query_id: stableQueryId(options.query), results }, null, 2));
      return;
    }
    if (command === 'stats') {
      console.log(JSON.stringify(storeStats(db), null, 2));
      return;
    }
    throw new Error(`Unknown command: ${command}`);
  } finally {
    db.close();
  }
}

main().catch((error) => {
  console.error(error.message);
  process.exitCode = 1;
});
