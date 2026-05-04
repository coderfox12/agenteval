#!/usr/bin/env node
/**
 * Wirtschaftlichkeits-Report
 * Analysiert Token-Verbrauch, Kosten (USD) und Latenz aus einem beliebigen
 * promptfoo-Eval-Output. Keine eigene Testsuite nötig – einfach auf jedes
 * vorhandene Eval-Ergebnis anwenden (Funktionalität, Sicherheit, Compliance).
 *
 * Verwendung:
 *   npx promptfoo eval --config evals/security_eval.yaml --output results.json
 *   node scripts/cost_report.js results.json
 *
 *   npx promptfoo eval --config evals/compliance_eval.yaml --output results.json
 *   node scripts/cost_report.js results.json
 */

const fs = require("fs");
const path = require("path");

// ─── Konfiguration ─────────────────────────────────────────────────────────────

// OpenAI Preise (Stand: 2025) in USD pro 1.000 Tokens
const MODEL_PRICES = {
  "gpt-4o-mini":   { input: 0.00015, output: 0.0006 },  // $0.15 / $0.60 per 1M
  "gpt-4o":        { input: 0.0025,  output: 0.01   },  // $2.50 / $10.00 per 1M
  "gpt-4-turbo":   { input: 0.01,    output: 0.03   },
  "gpt-3.5-turbo": { input: 0.0005,  output: 0.0015 },
};

// ─── Hilfsfunktionen ──────────────────────────────────────────────────────────

function percentile(arr, p) {
  if (arr.length === 0) return 0;
  const sorted = [...arr].sort((a, b) => a - b);
  const idx = Math.ceil((p / 100) * sorted.length) - 1;
  return sorted[Math.max(0, idx)];
}

function formatUSD(usd) {
  return `$${usd.toFixed(6)}`;
}

function formatMs(ms) {
  return ms >= 1000 ? `${(ms / 1000).toFixed(2)}s` : `${Math.round(ms)}ms`;
}

function extractModelName(providerName) {
  if (!providerName) return "unknown";
  const match = providerName.match(/gpt-[\w.-]+/i);
  return match ? match[0].toLowerCase() : providerName;
}

// ─── Hauptfunktion ────────────────────────────────────────────────────────────

function generateReport(resultsPath) {
  if (!fs.existsSync(resultsPath)) {
    console.error(`\n❌ Datei nicht gefunden: ${resultsPath}`);
    console.error("   Führe zuerst aus:");
    console.error("   npx promptfoo eval --config evals/economics_eval.yaml --output results.json\n");
    process.exit(1);
  }

  const raw = JSON.parse(fs.readFileSync(resultsPath, "utf-8"));

  // promptfoo speichert Ergebnisse in results.results (Array)
  const tests = raw?.results?.results ?? raw?.results ?? [];

  if (tests.length === 0) {
    console.error("❌ Keine Test-Ergebnisse gefunden.");
    process.exit(1);
  }

  // ─── Daten sammeln ──────────────────────────────────────────────────────────

  const byModel = {};
  const globalLatencies = [];
  let globalCostUSD = 0;
  let globalInputTokens = 0;
  let globalOutputTokens = 0;
  let passCount = 0;
  let failCount = 0;

  for (const test of tests) {
    const modelName = extractModelName(test.provider?.id ?? test.provider ?? "");
    const latency = test.latencyMs ?? 0;
    const success = test.success ?? test.pass ?? false;

    // Token-Daten aus promptfoo response
    const inputTokens  = test.response?.tokenUsage?.prompt     ?? 0;
    const outputTokens = test.response?.tokenUsage?.completion ?? 0;

    // Kosten: promptfoo berechnet cost in USD wenn bekannt
    let costUSD = test.cost ?? 0;

    // Fallback: manuell berechnen wenn cost fehlt
    if (costUSD === 0 && (inputTokens > 0 || outputTokens > 0)) {
      const prices = MODEL_PRICES[modelName] ?? MODEL_PRICES["gpt-4o-mini"];
      costUSD = (inputTokens / 1000) * prices.input + (outputTokens / 1000) * prices.output;
    }

    // Globale Akkumulation
    globalCostUSD      += costUSD;
    globalInputTokens  += inputTokens;
    globalOutputTokens += outputTokens;
    if (latency > 0) globalLatencies.push(latency);
    if (success) passCount++; else failCount++;

    // Pro-Modell-Akkumulation
    if (!byModel[modelName]) {
      byModel[modelName] = {
        costUSD: 0, inputTokens: 0, outputTokens: 0,
        latencies: [], pass: 0, fail: 0, tests: []
      };
    }
    byModel[modelName].costUSD      += costUSD;
    byModel[modelName].inputTokens  += inputTokens;
    byModel[modelName].outputTokens += outputTokens;
    if (latency > 0) byModel[modelName].latencies.push(latency);
    if (success) byModel[modelName].pass++; else byModel[modelName].fail++;
    byModel[modelName].tests.push({
      description: test.description ?? test.vars?.user_input?.slice(0, 60) ?? "–",
      costUSD, inputTokens, outputTokens, latency, success,
      complexity: test.metadata?.complexity ?? "–"
    });
  }

  // ─── Ausgabe ────────────────────────────────────────────────────────────────

  const sep   = "─".repeat(70);
  const title = "=".repeat(70);

  console.log(`\n${title}`);
  console.log("  WIRTSCHAFTLICHKEITS-REPORT  |  promptfoo Eval");
  console.log(`  Datei: ${path.basename(resultsPath)}`);
  console.log(title);

  // ─── Gesamt-Übersicht ───────────────────────────────────────────────────────
  console.log("\n📊 GESAMT-ÜBERSICHT");
  console.log(sep);
  console.log(`  Tests gesamt:        ${tests.length}  (✅ ${passCount} bestanden, ❌ ${failCount} fehlgeschlagen)`);
  console.log(`  Input-Tokens:        ${globalInputTokens.toLocaleString()}`);
  console.log(`  Output-Tokens:       ${globalOutputTokens.toLocaleString()}`);
  console.log(`  Tokens gesamt:       ${(globalInputTokens + globalOutputTokens).toLocaleString()}`);
  console.log(`  Gesamtkosten:        ${formatUSD(globalCostUSD)}`);
  console.log(`  Ø Kosten / Test:     ${formatUSD(globalCostUSD / tests.length)}`);

  if (globalLatencies.length > 0) {
    const avgLat = globalLatencies.reduce((a, b) => a + b, 0) / globalLatencies.length;
    console.log(`\n⏱  LATENZ-STATISTIKEN (alle Modelle)`);
    console.log(sep);
    console.log(`  Durchschnitt:        ${formatMs(avgLat)}`);
    console.log(`  Minimum:             ${formatMs(Math.min(...globalLatencies))}`);
    console.log(`  Maximum:             ${formatMs(Math.max(...globalLatencies))}`);
    console.log(`  P50 (Median):        ${formatMs(percentile(globalLatencies, 50))}`);
    console.log(`  P95:                 ${formatMs(percentile(globalLatencies, 95))}`);
  }

  // ─── Pro-Modell-Aufschlüsselung ───────────────────────────────��─────────────
  if (Object.keys(byModel).length > 1) {
    console.log(`\n🤖 AUFSCHLÜSSELUNG NACH MODELL`);
    console.log(sep);

    for (const [model, data] of Object.entries(byModel)) {
      const totalTests = data.pass + data.fail;
      const avgLat = data.latencies.length > 0
        ? data.latencies.reduce((a, b) => a + b, 0) / data.latencies.length : 0;

      console.log(`\n  Modell: ${model}`);
      console.log(`    Tests:           ${totalTests}  (✅ ${data.pass} / ❌ ${data.fail})`);
      console.log(`    Input-Tokens:    ${data.inputTokens.toLocaleString()}`);
      console.log(`    Output-Tokens:   ${data.outputTokens.toLocaleString()}`);
      console.log(`    Kosten:          ${formatUSD(data.costUSD)}`);
      if (data.latencies.length > 0) {
        console.log(`    Ø Latenz:        ${formatMs(avgLat)}`);
        console.log(`    P95 Latenz:      ${formatMs(percentile(data.latencies, 95))}`);
      }
    }
  }

  // ─── Pro-Test-Aufschlüsselung ──────────────────────────────────────��────────
  console.log(`\n📋 AUFSCHLÜSSELUNG PRO TEST`);
  console.log(sep);
  console.log(
    "  " +
    "Beschreibung".padEnd(45) +
    "Komp.".padEnd(7) +
    "Tokens".padEnd(10) +
    "Kosten (USD)".padEnd(14) +
    "Latenz".padEnd(10) +
    "OK?"
  );
  console.log("  " + "─".repeat(88));

  const allTests = Object.values(byModel).flatMap(m => m.tests);
  for (const t of allTests) {
    const desc = (t.description ?? "").slice(0, 43).padEnd(45);
    const comp = (t.complexity ?? "–").padEnd(7);
    const toks = `${t.inputTokens}+${t.outputTokens}`.padEnd(10);
    const cost = `$${t.costUSD.toFixed(5)}`.padEnd(14);
    const lat  = formatMs(t.latency).padEnd(10);
    const ok   = t.success ? "✅" : "❌";
    console.log(`  ${desc}${comp}${toks}${cost}${lat}${ok}`);
  }

  // ─── Hochrechnung ────────────────────────────────────────────────────────────
  const avgCostPerTest = globalCostUSD / tests.length;
  console.log(`\n💡 HOCHRECHNUNGEN (basierend auf Ø ${formatUSD(avgCostPerTest)} / Test)`);
  console.log(sep);
  const scenarios = [
    { label: "1.000 Tests/Tag",       n: 1000    },
    { label: "10.000 Tests/Tag",      n: 10000   },
    { label: "100.000 Tests/Monat",   n: 100000  },
    { label: "1.000.000 Tests/Monat", n: 1000000 },
  ];
  for (const s of scenarios) {
    console.log(`  ${s.label.padEnd(30)} → $${(avgCostPerTest * s.n).toFixed(2)}`);
  }

  console.log(`\n${title}\n`);
}

// ─── Einstiegspunkt ───────────────────────────────────────────────────────────

const resultsFile = process.argv[2] ?? path.join(__dirname, "..", "results.json");
generateReport(path.resolve(resultsFile));
