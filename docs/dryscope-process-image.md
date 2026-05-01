# dryscope Process Image Brief

Use this document when creating the dryscope process image with ChatGPT Images
2.0 or another image model.

## Preamble For The Diagram Agent

Create an engineering process diagram, not a marketing illustration and not a
textual flowchart. Treat this file as the source of truth for the diagram.

Return a single finished image. Do not output Mermaid, SVG code, ASCII art, a
diagram description, or multiple disconnected mini-diagrams.

The diagram must explain how dryscope narrows a large repository into a focused
set of code and documentation findings that a human developer, coding agent, or
stronger model can review before cleanup. The image should be accurate enough
that a dryscope maintainer recognizes the current system, and clear enough that
a technically literate reader can understand the main moving parts without
reading the repository.

## Diagram Goal

Show dryscope as a repository-narrowing tool for AI-assisted cleanup:

- It reads a repository; it does not rewrite code or docs.
- It finds repeated implementation shapes in code.
- It finds document-level intent overlap through Docs Map.
- It finds section-level documentation redundancy through Section Match.
- It can use optional LLM review stages to reduce noise and add judgment.
- It produces shortlists, reports, and JSON outputs for humans and agents.

The diagram should communicate this core idea:

> Large repo in -> focused code/docs findings out.

Avoid language that implies dryscope is a final refactor oracle, a generic
linter, or a tool that automatically edits the target repo.

## Preferred Composition

Use one strong left-to-right engineering diagram.

Recommended layout:

1. Top: title and short subtitle.
2. Left: repository inputs and configuration.
3. Middle: two main process lanes, Code and Docs.
4. Right: review/narrowing outputs.
5. Bottom: shared services and storage boundaries.

The two process lanes should be visually parallel but not identical. Code Match
and Docs Map/Section Match solve related narrowing problems at different levels.

## Title

Use a two-line title:

```text
dryscope
How a Large Repo Becomes Focused Cleanup Context
```

Make `dryscope` clearly larger than the subtitle. The subtitle should feel like
an explanatory caption, not an equal-weight headline.

## Visual Style

Use a serious modern engineering-diagram style:

- light background
- precise lane layout
- crisp boxes, arrows, gates, and artifact cards
- muted but distinct colors
- readable technical labels
- sparse text inside each node
- subtle depth only where it improves hierarchy

Suggested color system:

- Code lane: cool blue
- Docs lane: green or teal
- Optional LLM review: amber
- Shared services/storage: neutral gray
- Outputs/artifacts: violet or indigo

Avoid:

- humanoid robots
- glowing brains
- magic sparkle AI imagery
- dark neon DevOps style
- generic corporate workflow art
- dense paragraphs inside boxes
- tiny labels
- decorative icons that do not clarify the process

Text readability matters more than preserving every secondary note. If the
diagram becomes crowded, keep the lane and stage labels accurate and remove
small body text before shrinking type. The final image should remain readable
at typical README or documentation width.

## Process Overview

The diagram should show these major inputs:

- **Target Repository**
- **Source Code**: Python, Go, Java, JavaScript, JSX, TypeScript, TSX
- **Documentation**: Markdown, MDX, RST, AsciiDoc, TXT
- **Configuration**: defaults -> `.dryscope.toml` -> CLI flags
- **Project Profiles**: Django and pytest-factories exclusions

The diagram should show dryscope producing these major outputs:

- **Code Match Findings**
- **Code Review Shortlist**
- **Docs Map**
- **Section Match Recommendations**
- **Doc Pair Review**
- **Docs Report Pack**
- **Unified JSON `findings[]`**
- **Terminal Output**

Accuracy constraints:

- Do not show a vector database, vector store, FAISS, PGVector, Pinecone, or
  any storage layer for vectors. dryscope computes embeddings and uses a SQLite
  cache for reuse; it does not persist vectors in a vector database.
- Do not show dryscope rewriting files in the target repository.
- Do not show docs reports as a replacement source of truth for the target
  repository.
- Do not collapse Docs Map into a generic similarity graph. Docs Map is a
  descriptor, taxonomy, topic/facet, diagnostic, and consolidation-cluster
  workflow.

## Code Lane

Show the Code lane as a deterministic candidate-generation pipeline with an
optional review stage.

Required stages:

1. **Parse Source**
   - tree-sitter parser
   - extracts functions, classes, methods, constructors, and function-valued declarations

2. **Normalize Code Units**
   - strips comments and docstrings
   - replaces identifiers and literals with placeholders
   - preserves structural shape

3. **Embed Units**
   - API embeddings through LiteLLM or local sentence-transformers

4. **Similarity Engine**
   - hybrid cosine plus token Jaccard
   - size-ratio filtering

5. **Cluster Candidates**
   - Union-Find clustering
   - exact, near-identical, and structural candidates

6. **Code Match**
   - ranked duplicate-code candidate clusters

7. **Code Review** `(optional)`
   - optional LLM review
   - classifies `refactor`, `review`, or `noise`

8. **Escalation Policy**
   - keeps `review`
   - keeps higher-value `refactor`
   - drops low-priority verified matches

9. **Code Output**
   - terminal report
   - JSON findings

Show Code Review as optional and cost-bearing, not required for basic Code
Match.

## Docs Lane

Show the Docs lane as two complementary views:

- **Section Match**: microscopic, section-level repetition.
- **Docs Map**: macroscopic, document/corpus-level intent overlap.

### Section Match Path

Required stages:

1. **Chunk Documents**
   - heading-based sections
   - line tracking
   - plaintext paragraph chunks where needed

2. **Embed Sections**
   - API embeddings or local sentence-transformers

3. **Filter Noise**
   - short sections
   - boilerplate headings
   - optional intra-document mode

4. **Section Match**
   - hybrid similarity over sections
   - repeated configuration, deployment, setup, or reference sections

5. **Recommendations**
   - consolidate
   - link
   - brief reference
   - keep when intentional

Make clear that Section Match can identify repeated sections even when the
overall documents have different purposes.

### Docs Map Path

Required stages:

1. **Document Descriptors**
   - LLM profiles title, summary, aboutness labels, reader intents, doc role,
     audience, lifecycle, content type, surface, canonicality, and evidence

2. **Canonical Label Taxonomy**
   - deterministic exact/fuzzy normalization
   - optional LLM canonicalization
   - document coverage and aliases

3. **Docs Map**
   - topic tree
   - facets
   - diagnostics
   - consolidation clusters

4. **Intent Pair Evidence**
   - embeds canonical labels, not whole documents
   - finds related document pairs

5. **Doc Pair Review** `(optional, cost-capped)`
   - LLM relationship review
   - topic-level actions
   - selected related pairs only

Make clear that Docs Map finds intent overlap even when text is not copied.
Do not depict Docs Map as just "document embedding" or "similarity graph";
those labels are too generic and miss the taxonomy/reporting work.

## Shared Services And Storage

Show these as a support layer below the main lanes, not as the main workflow.

Required storage/service blocks:

- **Config Merge**
  - defaults
  - `.dryscope.toml`
  - CLI overrides

- **Embedding / Review Cache**
  - SQLite cache at `~/.cache/dryscope/cache.db`
  - stores embeddings and LLM review results
  - reusable acceleration state
  - support layer, not source repository content
  - not a vector database

- **LLM Backend**
  - LiteLLM providers
  - `claude -p`
  - `codex exec`
  - Ollama

- **Run Store**
  - `.dryscope/runs/<run-id>/`
  - resumable docs stage artifacts
  - `report.md`
  - `report.html`
  - `report.json`
  - `.dryscope/latest`
  - generated report/run output, not authoritative repo source
  - cleanup: keep newest, keep since date, keep last N days; dry-run by default

- **Cleanup**
  - keep newest N runs
  - keep since date
  - keep last N days
  - dry-run by default

Storage boundary accuracy:

- The target repository is the input source.
- The cache is reusable acceleration state.
- `.dryscope/runs/<run-id>/` is generated docs report output and resumable stage state.
- dryscope does not make the generated report a replacement source of truth for the target repository.
- dryscope has no vector-store service. If a storage cylinder is shown for
  embeddings, label it SQLite Cache, not Vector Store.

## Output Model

Show these outputs at the right side or lower-right:

- **Terminal Output**
  - readable ranked findings

- **Unified JSON**
  - `findings[]`
  - `mode: "code"` or `mode: "docs"`
  - intended for agents and scripts

- **Docs Report Pack**
  - `report.md`
  - `report.html`
  - `report.json`
  - same top-level section order

- **Report Sections**
  - Run Overview
  - Docs Map
  - Docs Map Clusters
  - Section Match
  - optional Doc Pair Review
  - Docs Map Taxonomy
  - Methodology

For output cards, prefer concrete labels:

- `Code Match Findings`
- `Code Review Shortlist`
- `Section Match Recommendations`
- `Docs Map`
- `Doc Pair Review`
- `Docs Report Pack: report.md / report.html / report.json`
- `Unified JSON findings[]`
- `Terminal Output`

- **Focused Cleanup Context**
  - smaller work batches
  - files, sections, clusters, and reasons
  - suitable for human review or agent follow-up

Do not show EPUB or unrelated publishing outputs.

## Review And Gate Semantics

Show review as narrowing and judgment, not as automatic mutation.

Required accuracy points:

- Code Review is optional.
- Doc Pair Review is optional and cost-capped.
- LLM review classifies or explains findings; it does not edit the repo.
- Deterministic filters and policies reduce noise before expensive review.
- Human developers, coding agents, or stronger models act on the final shortlist.

Use labels such as:

- `optional LLM review`
- `cost-capped`
- `noise filtering`
- `ranked shortlist`
- `refactor / review / noise`
- `consolidate / link / brief reference`
- `SQLite cache`
- `.dryscope/runs/<run-id>`
- `report.md / report.html / report.json`

Avoid saying:

- "automatic refactor"
- "fixes duplicates"
- "complete duplicate detection"
- "all findings are refactors"
- "all docs should be merged"
- "vector store"
- "FAISS"
- "PGVector"
- "document vector database"

## Recommended Diagram Skeleton

Represent the main diagram like this, but do not output it as text:

```text
Target Repository + Config
        |
        +--------------------------+
        |                          |
        v                          v
   Code Lane                  Docs Lane
   Parse Source               Chunk Documents
   Normalize Units            Section Match
   Embed Units                Docs Map
   Similarity Engine          Doc Pair Review
   Cluster Candidates         Docs Report Pack
   Code Match / Review
        |                          |
        +------------+-------------+
                     v
          Focused Cleanup Context
          Terminal + JSON + Reports

   Shared layer: Config, Cache, LLM Backend, Run Store, Cleanup
```

The final image should use real visual boxes, lanes, arrows, artifacts, and
storage blocks rather than rendering this ASCII sketch.

If stage numbers are shown, use this exact Code lane numbering:

1. Parse Source
2. Normalize Code Units
3. Embed Units
4. Similarity Engine
5. Cluster Candidates
6. Code Match
7. Code Review
8. Escalation Policy
9. Code Output

The Docs lane may use separate sublane numbering for Section Match and Docs
Map. Do not continue numbering across unrelated docs sublanes if it makes the
diagram harder to read.

## Short Labels To Prefer

Use short labels where possible:

- Target Repo
- Source Code
- Documentation
- Config Merge
- Project Profiles
- Parse Source
- Code Units
- Normalize
- Embed
- Similarity Engine
- Cluster
- Code Match
- Code Review
- Escalation Policy
- Chunk Docs
- Section Match
- Docs Map
- Taxonomy
- Intent Evidence
- Doc Pair Review
- Docs Report Pack
- SQLite Cache
- LLM Backend
- Run Store
- Unified JSON
- Terminal
- report.md
- report.html
- report.json
- Focused Cleanup Context

Do not use these labels:

- Vector Store
- FAISS
- PGVector
- Document Embedding as a Docs Map stage
- Docs Map Similarity Graph
- Run Artifacts without `.dryscope/runs/<run-id>`

## Final Output Requirements

The output must be:

- a single high-resolution image
- landscape orientation, preferably 16:9
- readable at typical README/documentation width
- suitable for a technical README, architecture page, or project announcement
- visually polished but information-dense
- accurate to the current dryscope process

The output must not be:

- Mermaid
- SVG or HTML code
- ASCII art
- a textual flowchart
- a set of unrelated panels
- a generic AI workflow graphic
