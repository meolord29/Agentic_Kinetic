#!/usr/bin/env node
// deploy/migrate.mjs — applies deploy/db/migrations/*.sql in order, tracked in app._migrations.
import { readFileSync, readdirSync } from "node:fs";
import { Client } from "pg";

const url = process.env.DATABASE_URL;
if (!url) {
  console.error("migrate: DATABASE_URL is required");
  process.exit(1);
}

const client = new Client({ connectionString: url });
await client.connect();

await client.query(`
  CREATE TABLE IF NOT EXISTS app._migrations (
    name text PRIMARY KEY,
    applied_at timestamptz NOT NULL DEFAULT now()
  )
`);

const dir = new URL("./db/migrations/", import.meta.url);
const files = readdirSync(dir).filter((f) => f.endsWith(".sql")).sort();

for (const file of files) {
  const { rowCount } = await client.query("SELECT 1 FROM app._migrations WHERE name = $1", [file]);
  if (rowCount) {
    console.log(`migrate: skip ${file} (applied)`);
    continue;
  }
  const sql = readFileSync(new URL(`./db/migrations/${file}`, import.meta.url), "utf8");
  await client.query(sql);
  await client.query("INSERT INTO app._migrations (name) VALUES ($1)", [file]);
  console.log(`migrate: applied ${file}`);
}

await client.end();
console.log("migrate: done");
