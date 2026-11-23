"""Generate embeddings.json for the quotes site.

Run:  python site/scripts/build_embeddings.py
Outputs: site/embeddings.json  {quote, author, vector}[]
"""
import csv
import json
from pathlib import Path

from sentence_transformers import SentenceTransformer

ROOT = Path(__file__).resolve().parents[2]
CSV_PATH = ROOT / "resources" / "quotes.csv"
OUT_PATH = Path(__file__).resolve().parents[1] / "embeddings.json"
MODEL = "sentence-transformers/all-MiniLM-L6-v2"


def main() -> None:
    rows = []
    with open(CSV_PATH, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            quote = row["quote"].strip().strip('"')
            author = row["author"].strip()
            if quote:
                rows.append({"quote": quote, "author": author})

    model = SentenceTransformer(MODEL)
    vectors = model.encode(
        [f'{r["quote"]} — {r["author"]}' for r in rows],
        normalize_embeddings=True,
    ).tolist()

    data = [
        {**r, "vector": v}
        for r, v in zip(rows, vectors)
    ]
    OUT_PATH.write_text(json.dumps(data), encoding="utf-8")
    print(f"Wrote {len(data)} embeddings to {OUT_PATH}")


if __name__ == "__main__":
    main()
