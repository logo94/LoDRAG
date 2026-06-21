## System Architecture & Processing Pipeline

The project implements a hybrid Named Entity Recognition and Disambiguation (NERD) framework specifically optimized for historical, literary, and critical-essay texts. The core objective is to achieve institutional-grade precision while maintaining near-instantaneous execution times.

### 1. High-Level Pipeline Overview

The text-processing framework operates through a decoupled four-stage pipeline:

[Raw Text] ──> 1. GLiNER (NER) ──> 2. Wikidata Candidate Search ──> 3. Reconcilier Ranking ──> [Structured Output]
│                                                   ▲
└───────► Uses Dynamic Domain Schema ───────────────┘
(Labels, Aliases & Semantic Relations)


1. **Information Extraction (NER):** GLiNER scans the raw text to extract entities. To maximize performance and prevent hallucinations, GLiNER is fed a highly optimized, domain-specific semantic schema containing only the curated `relations` (PIDs) mapped for each macro-category.
2. **Candidate Generation:** Extracted text snippets are resolved against the Wikidata API to fetch an initial pool of matching entity candidates.
3. **Deep Enrichment & Dual-Layer Filtering:** For each candidate, the system interrogates Wikidata. It extracts the structural ontology path (via `P31`/`P279`) to confirm the entity macro-class, and splits the data into two distinct internal tracks:
   * **The Semantic Track (Visible to GLiNER):** Only the whitelist relations defined in the JSON schema are retained to describe the entity in the text.
   * **The Hidden Track (Reserved for the Reconcilier):** Structural taxonomies and international authority controls are extracted to calculate the final ranking, remaining hidden from the LLM/GLiNER context to save token-overhead.
4. **Scoring & Final Selection:** The Reconcilier applies a multi-dimensional mathematical formula to score candidates, returning the exact matching QID or rejecting the entity if it falls below the safety threshold.

---

## 💡 Il Principio di Mutua Validazione (Feedback Loop Positivo)

L'architettura risolve il problema delle allucinazioni dei modelli linguistici (LLM) e dell'ambiguità dei motori di ricerca nativi attraverso un meccanismo di compensazione incrociata:

1. **Il Contesto Linguistico (GLiNER):** Identifica le menzioni nel testo e intuisce le relazioni sintattiche (es. *"Questo termine si comporta come un'occupazione nel testo"*), ma non possiede la conoscenza enciclopedica per validarle storicamente o fattualmente.
2. **Il Controllo Fattuale (Wikidata):** Possiede i grafi relazionali e le tassonomie del mondo reale, ma non conosce il contesto del testo analizzato.

Il sistema unisce questi due mondi in un ciclo in cui:
* **Le relazioni estratte dal testo diventano certe solo se l'elemento viene riconciliato su Wikidata.**
* **L'entità viene riconciliata su Wikidata solo se rispetta le relazioni e la struttura ontologica previste dal testo.**

Se un'entità supera la soglia minima e riceve un `wikidata_id`, significa che ha superato entrambi i filtri di sbarramento, azzerando i falsi positivi.

### 2. The Ranking System & Score Breakdown

Candidates are not selected via simple string matching. The `Reconcilier` ranks every candidate by calculating a cumulative confidence score ($S \in [0, 1]$), split into 5 distinct mathematical dimensions:

* **Text & Popularity Score:** Measures the literal Levenshtein/Jaro-Winkler distance between the text snippet and the Wikidata labels/aliases, weighted against the entity's global popularity (sitelinks count).
* **Wikidata Rank Bonus:** Applies a mathematical weight based on the entity's statement status on Wikidata (Preferred, Normal, or Deprecated).
* **Ontology Score:** Cross-references the candidate's `P31` (instance of) and `P279` (subclass of) chains against the configured macro-class `qids`. If a candidate for a `person` matches `Q5`, it receives a massive structural boost.
* **Relation Score:** Evaluates context. If the text mentions an author and an essay, and their corresponding Wikidata records are interconnected via a semantic relation (e.g., `P50`), the system assigns a context bonus.
* **Authority Score:** Evaluates the cultural and academic reliability of the entity based on institutional catalog mapping.

---

## Wikidata Semantic Schema Mapping

To optimize entity extraction via GLiNER and ensure maximum precision during the reconciliation phase, the system uses a domain-oriented schema driven by top-level semantic anchors. This prevents the injection of redundant metadata (e.g., external catalog IDs, regional editions) that would cause model hallucination or latency. 

Instead of hardcoding endless specific concepts in Python, the scoring system relies on a curated list of base QIDs representing broad, top-level cultural and academic macro-containers (e.g., *Literature, Literary Genre, Comedy, Profession*). These act as foundational anchor points: during reconciliation, the ranking algorithm automatically traces a candidate's family tree upwards via taxonomical properties. If any intermediate parent class intersects with these schema anchors, the system dynamically validates the entity as a legitimate match for the target macro-class.

Below is the semantic breakdown of the properties mapped for each macro-category:

### 1. Person (`person`)
* **`P19` (place of birth):** Connects the individual to a physical location, grounding biographical context.
* **`P20` (place of death):** Identifies the geographical end-point of the historical figure.
* **`P101` (field of work):** The specific specialization or academic discipline (e.g., *philology*, *literary criticism*).
* **`P106` (occupation):** Core professional role (e.g., *writer*, *poet*, *philosopher*). Essential for triggering occupation-based ontology boosts.
* **`P108` (employer):** Institutions or universities where the person was officially employed.
* **`P136` (genre):** Literary or artistic genres associated with the author's output (e.g., *burlesque poetry*, *satire*).
* **`P1416` (affiliation):** Unofficial or cultural affiliations (e.g., *academies*, *intellectual circles*).

### 2. Work (`work`)
* **`P50` (author):** The primary relationship connecting a text to its creator.
* **`P136` (genre):** The structural genre of the text (e.g., *treatise*, *sonnet*, *essay*).
* **`P407` (language of work or name):** The original or documented language of the text (e.g., *Old Italian*, *Latin*).
* **`P577` (publication date):** Temporal anchor, fundamental to positioning the work in the correct century.
* **`P921` (main subject):** What the work is about. Crucial for matching essays or critical studies (e.g., a study *about* Cecco Angiolieri).
* **`P8411` (attributed author):** Handles historical or pseudonymous attributions common in medieval/early modern texts.

### 3. Place (`place`)
* **`P17` (country):** The modern or historical sovereign state encompassing the location.
* **`P131` (located in the administrative territorial entity):** Hierarchical geographic routing (e.g., *Siena -> Tuscany*), ensuring regional coherence.

### 4. Organization (`organization`)
* **`P17` (country):** The political jurisdiction where the organization operates.
* **`P31` (instance of):** Qualifies the nature of the entity (e.g., *university*, *monastery*, *publishing house*).
* **`P159` (headquarters location):** The city or specific place hosting the institution's main seat.

### 5. Event (`event`)
* **`P17` (country):** The country or territory where the event took place.
* **`P276` (location):** The exact venue or city that hosted the event.
* **`P585` (point in time):** The exact date or precise moment in history when the event occurred.
* **`P664` (organizer):** The institution or individual responsible for staging or prompting the event.
* **`P710` (participant):** Links historical actors and figures who actively took part in the happening.

### 6. Concept (`concept`)

* **`qids` (Ontological Anchors):** `["Q8060", "Q28640", "Q40821", "Q40831", "Q151885", "Q182015", "Q7184903"]`
  
* **`P31` (instance of) / `P279` (subclass of):** Tassonomical links defining the hypernym of the abstract idea (e.g., *Humorismo is a subclass of Literary Style*). Crucial for calculating the `ontology_score` via the hypernym climbing logic.
* **`P138` (named after):** Identifies eponyms (e.g., *Petrarchism* named after *Francesco Petrarca*), heavily leveraging textual proximity in essays.
* **`P1269` (facet of):** Relates the abstract concept to its broader disciplinary field (e.g., *Burlesque* as a facet of *Literature* or *Theater*).
* **`P1552` (has characteristic):** Distinctive attributes that legally or theoretically define the concept.
* **`P2579` (studied in):** The field of research or academic branch that investigates this specific concept.


### 3. Allowed External Authority Files (`allowed_external_authority_pids`)

To ensure mathematical certainty during reconciliation, the system extracts a strict subset of **Authority Control Identifiers**. If a candidate is registered across these major global library catalogs, its `authority_score` scales exponentially, allowing the system to instantly separate historical figures from modern namesakes.

The whitelisted external database PIDs configured in the system are:

| PID | Authority Control / Catalog Name | Domain / Primary Target |
| :--- | :--- | :--- |
| **`P213`** | **ISNI** (International Standard Name Identifier) | International standard for identifying public identities. |
| **`P214`** | **VIAF** (Virtual International Authority File) | Aggregator linking major national library catalogs globally. |
| **`P227`** | **GND** (Integrated Authority File) | German National Library (Crucial for European history & philosophy). |
| **`P244`** | **LCAuth** (Library of Congress Authority ID) | US Library of Congress institutional authority. |
| **`P245`** | **ULAN** (Union List of Artist Names) | Getty Research Institute (Essential for artists and architects). |
| **`P268`** | **BnF ID** (Bibliothèque nationale de France) | French National Library standard catalog. |
| **`P269`** | **SUDOC** (Système universitaire de documentation) | French higher-education and academic thesis catalog. |
| **`P345`** | **IMDb ID** (Internet Movie Database) | Modern media/pop-culture reference safety check. |
| **`P396`** | **SBN Viaf / IT\ICCU** (Istituto Centrale per il Catalogo Unico) | National Library Service of Italy (Critical for Italian literature). |
| **`P508`** | **BNCF Thesaurus** (Biblioteca Nazionale Centrale di Firenze) | Specific subject-heading authority for philosophical/literary concepts. |
| **`P950`** | **BNE** (Biblioteca Nacional de España) | National Library of Spain catalog. |
| **`P1014`** | **AAT** (Art & Architecture Thesaurus) | Getty structured vocabulary, essential for anchoring abstract `concepts`. |

This dual-track architecture guarantees that **GLiNER remains fast and hyper-focused** on clean textual semantic labels, while the **Reconcilier retains access to rigorous database controls** to avoid false-positive matches.
