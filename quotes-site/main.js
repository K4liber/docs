import { pipeline } from "https://cdn.jsdelivr.net/npm/@xenova/transformers@2.17.2";

const searchEl = document.getElementById("search");
const statusEl = document.getElementById("status");
const resultsEl = document.getElementById("results");
const pagerEl = document.getElementById("pager");
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
    return { item, idx: i, score: 0.75 * sem + 0.25 * kw, sem, kw };
  });

  return scored.sort((a, b) => b.score - a.score);
}

// ---------- render ----------
const PAGE_SIZE = 12;
// default view: dataset order, newest first (newest rows are appended at the end of the CSV)
const defaultResults = () =>
  quotes.map((item, idx) => ({ item, idx, score: 1, sem: 1, kw: 0 })).reverse();
let currentResults = defaultResults();
let page = 0;

function makeCard({ item, idx, score, sem, kw }) {
  const node = cardTpl.content.cloneNode(true);
  node.querySelector(".index").textContent = `#${idx + 1}`;
  node.querySelector("blockquote").textContent = item.quote;
  node.querySelector("cite").textContent = `— ${item.author}`;
  const citeEl = node.querySelector("cite");
  const scoreEl = document.createElement("span");
    scoreEl.className = "score";
  scoreEl.title = `semantic ${sem.toFixed(2)} / keyword ${kw.toFixed(2)}`;
  scoreEl.textContent = score.toFixed(2);
  citeEl.prepend(scoreEl);
  return node;
}

function render() {
  resultsEl.innerHTML = "";
  const start = page * PAGE_SIZE;
  const slice = currentResults.slice(start, start + PAGE_SIZE);
  for (const r of slice) resultsEl.appendChild(makeCard(r));
  if (!resultsEl.children.length) {
    const li = document.createElement("li");
    li.className = "card";
    li.textContent = "Nothing matching — try rephrasing.";
    resultsEl.appendChild(li);
  }
  renderPager();
}

function renderPager() {
  pagerEl.innerHTML = "";
  const pages = Math.ceil(currentResults.length / PAGE_SIZE);
  if (pages <= 1) return;

  const mk = (label, target, opts = {}) => {
    const b = document.createElement("button");
    b.textContent = label;
    b.disabled = opts.disabled || false;
    if (opts.active) b.classList.add("active");
    b.addEventListener("click", () => {
      page = target;
      render();
      if (typeof window.scrollTo === "function") {
        window.scrollTo({ top: 0, behavior: "smooth" });
      }
    });
    pagerEl.appendChild(b);
  };

  mk("‹", page - 1, { disabled: page === 0 });

  const window = 2; // pages shown around current
  const range = new Set([0, pages - 1]);
  for (let p = page - window; p <= page + window; p++) {
    if (p >= 0 && p < pages) range.add(p);
  }
  const sorted = [...range].sort((a, b) => a - b);
  let prev = -2;
  for (const p of sorted) {
    if (p - prev > 1) pagerEl.appendChild(Object.assign(document.createElement("span"), { textContent: "…", className: "ellipsis" }));
    mk(p + 1, p, { active: p === page });
    prev = p;
  }

  mk("›", page + 1, { disabled: page >= pages - 1 });
}

// default view: show all, newest first
render();

// ---------- events ----------
let timer;
searchEl.addEventListener("input", () => {
  clearTimeout(timer);
  const q = searchEl.value.trim();
  if (!q) {
    currentResults = defaultResults();
    page = 0;
    render();
    return;
  }
  statusEl.textContent = "searching…";
  timer = setTimeout(async () => {
    currentResults = await search(q);
    page = 0;
    render();
    statusEl.textContent = `${quotes.length} quotes ready`;
  }, 250);
});
