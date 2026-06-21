# LoDRAG

> A sustainable, transparent, and configurable local pipeline for knowledge-grounded semantic search over literary texts.

LoDRAG is a local-first pipeline that enriches a textual corpus with structured information from **Wikidata** and answers natural-language queries through a **locally executed LLM**, with no dependency on external cloud services. It is designed around three principles: **sustainability** (runs on commodity, GPU-free hardware), **transparency** (entity reconciliation is deterministic and fully traceable), and **configurability** (a human-defined schema and an interchangeable component stack that can be tuned to the corpus at hand).


---

## Key Features

- **Wikidata-grounded retrieval** — entities and relations extracted from the text are reconciled against Wikidata
- **Deterministic, auditable reconciliation** — a six-factor scoring function ranks candidate entities; the full score breakdown is persisted alongside each paragraph, so every decision can be inspected after the fact.
- **Human-in-the-loop schema** — a declarative `schema.json` defines the entity classes, the Wikidata QIDs/PIDs of interest, and the accepted authority files; adapting the system to a new corpus means editing a file, not the code.
- **Authority control** — only entities bearing identifiers certified by national libraries and archives (VIAF, GND, SBN, …) are validated, treating reconciliation as an act of scientific validation.
- **Fully local execution** — extraction, embedding, vector store, and generation all run on CPU via open-source components.

---

## Architecture

The pipeline has two phases: an offline **ingest & enrichment** phase that builds the index, and a runtime **query & synthesis** phase.

**Ingest (in execution order):**
1. **Segmentation** — the text is normalized and split into paragraphs (the unit of extraction and retrieval).
2. **Optional simplification** — the local LLM can rewrite archaic/complex prose into explicit SVO sentences to aid extraction (the original text is what gets indexed).
3. **Entity & relation extraction** — a zero-shot model (GLiNER2) extracts entities and relations using natural-language labels from the schema.
4. **Reconciliation** — each mention is matched to Wikidata via the deterministic six-factor ranking.
5. **Description retrieval** — canonical labels, descriptions, and schema-relevant properties are fetched from Wikidata.
6. **Embedding & storage** — paragraphs are embedded and stored with their reconciliation metadata in the vector store.

**Query:** the question is embedded, the closest paragraphs are retrieved (cosine similarity, with a strict distance threshold), and the original text plus the structured Wikidata context is passed to the local LLM, which synthesizes a grounded answer or declares the context insufficient rather than hallucinating.

### Component Stack

| Role | Component |
|------|-----------|
| Orchestration | FastAPI |
| Entity & relation extraction | GLiNER2 (multilingual) |
| Sentence embeddings & Vector store| ChromaDB |
| Local LLM | llama.cpp |

Models for sentence embeddings and LLM summarization are interchangeable and selectable by `config/model.json` configuration file.

---

## Requirements

- Python 3.10+
- No GPU required (CPU-only inference)
- A GGUF model file for the local LLM (see *Models* below)
- ~16 GB RAM recommended 

---

## Installation

```bash
# 1. Clone the repository
git clone https://github.com/logo94/LoDRAG.git
cd LoDRAG

# 2. Create and activate a virtual environment
python -m venv venv
source venv/bin/activate        # on Windows: venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt
```


---

## Configuration

The pipeline is driven by declarative configuration files loaded at startup:


| File | Purpose |
|------|---------|
| `schema.json` | Entity classes, Wikidata QIDs/PIDs, accepted authority properties |
| `enriched_schema.json` | Auto-generated at startup from `schema.json` (labels/aliases fetched from Wikidata) |
| `prompts.json` | System prompts for the simplification and synthesis tasks |
| `models.json` | Model identifiers and runtime parameters |
| `config.json` | Global pipeline settings (thresholds, language, …) |

`enriched_schema.json` is derived automatically — you edit `schema.json`, the system fetches the ontological context from Wikidata at startup.

Example `schema.json` entry:

```json
{
  "Person": {
    "description": "A historical or fictional individual",
    "qids": ["Q5"],
    "pids": ["P19", "P569", "P570"]
  }
}
```

---

## Running


```bash
uvicorn main:app --host 127.0.0.1 --port 1500
```

Then open the web interface at `https://127.0.0.1:1500` 

### Workflow

1. **Create a project** — choose an ID, collection name, and document language.
2. **Test / Ingest** — paste text or upload a file; "Run Test" shows extracted entities, accepted/rejected reconciliations with scores, and graph relations without writing to the store.
3. **Analysis** — browse the reconciled entities and relations of stored documents.
4. **Query** — ask a natural-language question and receive an LLM synthesis grounded in the retrieved, reconciled context.

---

## API


| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/config/{name}` | Retrieve a config file (`schema`, `enriched_schema`, `prompts`, `config`, `models`, `projects`) |
| `PUT` | `/api/config/{name}` | Update a config file |
| `POST` | `/api/ingest/test` | Dry-run extraction & reconciliation on a text |
| `POST` | `/api/ingest/upload` | Ingest a file into a project |
| `POST` | `/api/query` | Query a project (streamed response) |
| `GET` | `/api/projects/entries` | Paginated stored entries of a project |

Interactive API docs are available at `/docs` (FastAPI Swagger UI).

---

## Acknowledgments

Built on open-source components: [FastAPI](https://fastapi.tiangolo.com/), [GLiNER2](https://github.com/fastino-ai/GLiNER2), [ChromaDB](https://www.trychroma.com/), [llama.cpp](https://github.com/ggerganov/llama.cpp), [sentence-transformers](https://www.sbert.net/), and the [Wikidata](https://www.wikidata.org/) knowledge base.