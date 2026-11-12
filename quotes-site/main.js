import { pipeline } from "https://cdn.jsdelivr.net/npm/@xenova/transformers@2.17.2";

const searchEl = document.getElementById("search");
const statusEl = document.getElementById("status");
const resultsEl = document.getElementById("results");
const cardTpl = document.getElementById("card");

// ---------- data ----------
const quotes = await fetch("./embeddings.json").then((r) => r.json());
const vectors = quotes.map((q) => q.vector); // normalized, 384-dim

// ---------- model ----------
const extractor = await pipeline("feature-extraction", "Xenova/all-MiniLM-L6-v2", {
  quantized: true,
});
searchEl.disabled = false;
statusEl.textContent = `${quotes.length} quotes ready`;
searchEl.focus();

// ---------- keyword score (token overlap, author boost) ----------
const STOP = new Set(["the", "a", "an", "of", "to", "and", "in", "is", "it", "that", "for", "on", "with", "as", "be", "are"]);

function tokenize(s) {
  return s.toLowerCase().split(/[^a-z0-9']+/).filter((t) => t && !STOP.has(t));
}

function keywordScore(query, item) {
  const qTokens = tokenize(query);
  if (!qTokens.length) return 0;
  const text = `${item.quote} ${item.author}`.toLowerCase();
  let score = 0;
  for (const t of qTokens) {
    if (item.author.toLowerCase().includes(t)) score += 1.5;
    else if (text.includes(t)) score += 1;
  }
  return score / (qTokens.length * 1.5); // normalize to [0, 1]
}

// ---------- cosine similarity (vectors are already normalized) ----------
function cosine(a, b) {
  let dot = 0;
  for (let i = 0; i < a.length; i++) dot += a[i] * b[i];
  return dot;
}

// ---------- hybrid search ----------
async function search(query) {
  const output = await extractor(query, { pooling: "mean", normalize: true });
  const qVec = Array.from(output.data);

  const scored = quotes.map((item, i) => {
    const sem = cosine(qVec, vectors[i]); // ~[-1, 1], mostly [0, 1]
    const kw = keywordScore(query, item);
    return { item, score: 0.75 * sem + 0.25 * kw, sem, kw };
  });

  return scored.sort((a, b) => b.score - a.score);
}

// ---------- render ----------
function render(scored) {
  resultsEl.innerHTML = "";
  const top = scored.slice(0, 12);
  for (const { item, score, sem, kw } of top) {
    if (score < 0.15) break; // drop irrelevant tail
    const node = cardTpl.content.cloneNode(true);
    node.querySelector("blockquote").textContent = item.quote;
    node.querySelector("cite").textContent = `— ${item.author}`;
    const citeEl = node.querySelector("cite");
    const scoreEl = document.createElement("span");
    scoreEl.className = "score";
    scoreEl.title = `semantic ${sem.toFixed(2)} / keyword ${kw.toFixed(2)}`;
    scoreEl.textContent = score.toFixed(2);
    citeEl.prepend(scoreEl);
    resultsEl.appendChild(node);
  }
  if (!resultsEl.children.length) {
    const li = document.createElement("li");
    li.className = "card";
    li.textContent = "Nothing matching — try rephrasing.";
    resultsEl.appendChild(li);
  }
}

// default view: show all, most recent first (dataset order)
render(quotes.map((item) => ({ item, score: 1, sem: 1, kw: 0 })));

// ---------- events ----------
let timer;
searchEl.addEventListener("input", () => {
  clearTimeout(timer);
  const q = searchEl.value.trim();
  if (!q) {
    render(quotes.map((item) => ({ item, score: 1, sem: 1, kw: 0 })));
    return;
  }
  statusEl.textContent = "searching…";
  timer = setTimeout(async () => {
    render(await search(q));
    statusEl.textContent = `${quotes.length} quotes ready`;
  }, 250);
});
