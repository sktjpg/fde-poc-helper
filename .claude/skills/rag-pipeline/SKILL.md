---
name: rag-pipeline
description: "How to add retrieval-augmented generation to this codebase - ingestion, chunking, hybrid retrieval (BM25 plus vectors), reranking, grounded answers with citations, and retrieval evaluation. Use when a requirement involves answering from documents, a knowledge base, PDFs, search, embeddings or citations."
---

# RAG pipeline

No retrieval code ships in the skeleton: build only the stages the requirement needs.
`rank-bm25` is installed; embeddings and a vector store are chosen per exercise.

## Start with the cheapest thing that works

| Corpus                                   | Approach                                   |
|------------------------------------------|--------------------------------------------|
| Fits comfortably in the context window   | No retrieval: put the documents in the prompt |
| Exact terms matter (ids, codes, names)   | Lexical (BM25)                             |
| Paraphrased, conceptual questions        | Embeddings                                 |
| Both, or quality matters                 | Hybrid + reciprocal rank fusion, then rerank |

Say which row applies and why. "The corpus is three short documents, so I pass them whole;
retrieval would add failure modes without a benefit" is a strong answer.

## Where the pieces go

```
domain/models.py      Chunk(id, document_id, text, metadata), RetrievedChunk(chunk, score)
domain/ports.py       Retriever.retrieve(query, k) -> list[RetrievedChunk]
                      Embedder.embed(texts) -> list[list[float]]   (only if vectors are used)
adapters/retrieval/   bm25_retriever.py, vector_retriever.py, hybrid_retriever.py, reranker.py
services/rag_service.py   retrieve -> build context -> generate -> validate citations
scripts/ or a CLI     ingestion: parse -> chunk -> (embed) -> index
```

The service depends on the `Retriever` port only, so BM25, vectors and hybrid are
interchangeable and the service is tested with a fake retriever.

## Stage notes

- Parsing: keep the source structure (titles, sections, page numbers) as metadata.
- Chunking: split on structure first (headings, paragraphs), then by size with a small
  overlap. Justify the size by the content: an FAQ entry or a clause is one chunk; long
  prose about 200 to 500 tokens. Never split mid-sentence or mid-table.
- Metadata on every chunk: document id, title, section, page, date, access scope. It is
  what makes filtering and citations possible.
- Hybrid: run lexical and vector retrieval independently and fuse the rankings with
  reciprocal rank fusion, `score(d) = sum(1 / (60 + rank_i(d)))`. It needs no score
  normalisation between the two systems.
- Reranking: retrieve wide (top 20 to 50), rerank, keep few (3 to 8). More context is not
  better: it costs tokens and dilutes the answer.
- Context construction: each chunk delimited and labelled with its id; instructions outside
  the delimiters. Retrieved text is untrusted data (see `llm-security`).
- Generation: instruct the model to answer only from the provided chunks, to cite chunk
  ids, and to say it does not know when the chunks do not contain the answer.
- Validate the output: every cited id must be one that was actually retrieved; otherwise
  reject or retry once.
- Access control is enforced at retrieval time with metadata filters, never by asking the
  model to withhold.

## Evaluation

Evaluate retrieval separately from generation, or you cannot tell which one failed.

- Retrieval, over a labelled set of (question, relevant chunk ids): Recall@K (is the
  evidence in the top K at all), MRR (how high the first relevant hit is), Precision@K,
  NDCG when relevance is graded.
- Generation, in the golden dataset: expected facts present, forbidden facts absent,
  citations valid, and an explicit "not in the documents" case that must produce a refusal
  rather than an invented answer.

If Recall@K is low no prompt will fix the answers: fix chunking or retrieval first.

## What to say aloud

"I separate retrieval quality from generation quality. Retrieval is hybrid because exact
identifiers need lexical matching and paraphrases need embeddings; the answer must cite
retrieved chunks and I validate that the citations exist."
