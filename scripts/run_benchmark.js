#!/usr/bin/env node
/**
 * Benchmark Runner: Führt Multi-Modell-Vergleich nur mit verfügbaren API-Keys aus.
 * Provider ohne gesetzten Key werden automatisch übersprungen.
 */

const { execSync } = require("fs") && require("child_process");
const fs = require("fs");
const path = require("path");

// .env laden (ohne externe Abhängigkeit)
const envFile = path.join(__dirname, "..", ".env");
if (fs.existsSync(envFile)) {
  fs.readFileSync(envFile, "utf-8")
    .split("\n")
    .forEach((line) => {
      const trimmed = line.trim();
      if (!trimmed || trimmed.startsWith("#")) return;
      const idx = trimmed.indexOf("=");
      if (idx > 0) {
        const key = trimmed.slice(0, idx).trim();
        const val = trimmed.slice(idx + 1).trim();
        if (!process.env[key]) process.env[key] = val;
      }
    });
}

const PROVIDERS = [
  {
    envKey: "OPENAI_API_KEY",
    id: "openai:gpt-4o-mini",
    label: "Frontier – OpenAI gpt-4o-mini",
  },
  {
    envKey: "MISTRAL_API_KEY",
    id: "mistral:mistral-large-latest",
    label: "Europäisch – Mistral Large",
  },
  {
    envKey: "GROQ_API_KEY",
    id: "groq:llama-3.3-70b-versatile",
    label: "Open-Source – Llama 3.3 70B (Groq)",
  },
];

const available = PROVIDERS.filter((p) => process.env[p.envKey]);
const skipped = PROVIDERS.filter((p) => !process.env[p.envKey]);

if (available.length === 0) {
  console.error(
    "\n❌ Kein API-Key gefunden. Mindestens OPENAI_API_KEY wird benötigt.\n"
  );
  process.exit(1);
}

console.log("\n🤖 BENCHMARK – Multi-Modell-Vergleich");
console.log(`   Aktive Provider (${available.length}):`);
available.forEach((p) => console.log(`   ✅ ${p.label}`));
if (skipped.length > 0) {
  console.log(`   Übersprungen (Key fehlt):`);
  skipped.forEach((p) => console.log(`   ⚪ ${p.label}  →  ${p.envKey}`));
}
console.log("");

// Temporäre YAML mit nur den verfügbaren Providern erzeugen
const configPath = path.join(
  __dirname,
  "..",
  "evals",
  "benchmark",
  "model_comparison.yaml"
);
const baseConfig = fs.readFileSync(configPath, "utf-8");

const providerBlock = available
  .map(
    (p) =>
      `  - id: ${p.id}\n    label: "${p.label}"\n    config:\n      temperature: 0`
  )
  .join("\n\n");

// Provider-Block im YAML ersetzen (alles zwischen "providers:" und "prompts:")
const tempConfig = baseConfig.replace(
  /^providers:[\s\S]*?(?=^prompts:)/m,
  `providers:\n${providerBlock}\n\n`
);

const tmpPath = path.join(__dirname, "..", ".benchmark_tmp.yaml");
fs.writeFileSync(tmpPath, tempConfig);

try {
  execSync(
    `npx promptfoo@latest eval --no-cache --config "${tmpPath}" --output benchmark_results.json`,
    { stdio: "inherit" }
  );
  execSync(
    `node "${path.join(__dirname, "cost_report.js")}" benchmark_results.json`,
    { stdio: "inherit" }
  );
} finally {
  fs.unlinkSync(tmpPath);
}
