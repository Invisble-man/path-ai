// server.js — ONE FILE APP (Backend + Frontend)
// Federal Proposal Generator w/ Go-No-Go, Compliance, RTM, Exports

import express from "express";
import OpenAI from "openai";

const app = express();
app.use(express.json({ limit: "20mb" }));

const PORT = process.env.PORT || 3000;
const MODEL = process.env.MODEL || "gpt-5";
const client = new OpenAI({ apiKey: process.env.OPENAI_API_KEY });

/* ================= HELPERS ================= */

function systemRules() {
  return `
You are a U.S. federal proposal capture manager and compliance analyst.

Rules:
- Use ONLY solicitation text + company data provided.
- Do NOT invent certifications, past performance, pricing, clearances.
- If missing info exists, mark it as "unknown".
- Remove fluff. Every paragraph must map to a requirement or evaluation factor.
- Proposals must be evaluator-friendly and compliant.
`;
}

async function callModel(prompt, temperature = 0.25) {
  const r = await client.responses.create({
    model: MODEL,
    input: [
      { role: "system", content: systemRules() },
      { role: "user", content: prompt }
    ],
    temperature
  });
  return JSON.parse(r.output_text);
}

function estimatePages(text, wordsPerPage = 450) {
  const words = (text || "").split(/\s+/).filter(Boolean).length;
  return Math.max(1, Math.ceil(words / wordsPerPage));
}

/* ================= API ================= */

// PARSE
app.post("/api/parse", async (req, res) => {
  try {
    const out = await callModel(`
Return strict JSON.

Schema:
{
  "metadata": { "title":string|null,"agency":string|null,"solicitation_number":string|null,"due_date":string|null,"contract_type":string|null,"set_aside":string|null,"naics":string|null },
  "scope_summary": string,
  "requirements": [{ "id":string,"text":string,"priority":"MUST"|"SHOULD"|"MAY","suggested_sections":string[] }],
  "evaluation_criteria": [{ "factor":string,"text":string }],
  "format_constraints": { "max_pages_total":number|null,"font_family":string|null,"font_size_pt":number|null },
  "questions_for_user": string[]
}

Solicitation:
${req.body.solicitationText}
`);
    res.json(out);
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

// ASSESS
app.post("/api/assess", async (req, res) => {
  try {
    const { parsed, company } = req.body;
    const out = await callModel(`
Return strict JSON.

If solicitation is a set-aside and company does NOT meet it → probability = 0.

Schema:
{
  "contract_brief": { "type":string,"pros":string[],"cons":string[] },
  "eligibility": { "status":"eligible"|"ineligible"|"unknown","blocking_reasons":string[] },
  "compatibility": { "match_percent":number,"probability_of_win_percent":number,"go_no_go":"GO"|"NO-GO"|"CONDITIONAL" },
  "recommended_actions": string[]
}

Parsed:
${JSON.stringify(parsed)}

Company:
${JSON.stringify(company)}
`);
    res.json(out);
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

// GENERATE
app.post("/api/generate", async (req, res) => {
  try {
    const { parsed, company } = req.body;
    const out = await callModel(`
Return strict JSON.

Schema:
{
  "sections": [{ "id":string,"title":string,"content":string,"requirements_covered_ids":string[] }]
}

Parsed:
${JSON.stringify(parsed)}

Company:
${JSON.stringify(company)}
`);
    res.json(out);
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

// SCORE
app.post("/api/score", async (req, res) => {
  try {
    const { parsed, proposalSections } = req.body;
    const text = proposalSections.map(s => s.content).join("\n");
    const pages = estimatePages(text);

    const out = await callModel(`
Return strict JSON.

Schema:
{
  "overall": { "score_percent":number,"readiness":string },
  "rtm": [{ "req_id":string,"status":"strong"|"weak"|"missing","notes":string }],
  "format": { "estimated_pages":number }
}

Parsed:
${JSON.stringify(parsed)}

Proposal:
${JSON.stringify(proposalSections)}
`);
    out.format.estimated_pages = pages;
    res.json(out);
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

/* ================= FRONTEND ================= */

app.get("/", (_req, res) => {
res.send(`<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8"/>
<title>Path – Proposal Generator</title>
<script src="https://cdn.tailwindcss.com"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/docx@8.5.0/build/index.umd.js"></script>
<script src="https://cdn.jsdelivr.net/npm/xlsx/dist/xlsx.full.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/jspdf@2.5.1/dist/jspdf.umd.min.js"></script>
</head>

<body class="bg-gray-50 p-6">
<h1 class="text-2xl font-bold mb-4">Path – Federal Proposal Generator</h1>

<textarea id="sol" class="w-full border p-3 mb-3" rows="8" placeholder="Paste RFP / RFI text"></textarea>
<button onclick="analyze()" class="px-4 py-2 bg-teal-700 text-white rounded">Analyze</button>

<div id="out" class="mt-4 text-sm"></div>

<script>
let parsed=null, company={}, draft=[];

async function analyze(){
  const r=await fetch("/api/parse",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({solicitationText:sol.value})});
  parsed=await r.json();
  out.innerText="Parsed "+parsed.requirements.length+" requirements.";
}
</script>
</body>
</html>`);
});

/* ================= START ================= */

app.listen(PORT, () =>
  console.log("Path running at http://localhost:"+PORT)
);
