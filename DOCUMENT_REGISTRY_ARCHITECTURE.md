# Document Registry — Architecture (Phase 15 design)

Status: **design only — no code written, no Sheets changed, no commit/push/deploy.**

## 0. Context and why this isn't starting from zero

Before designing anything new, three existing pieces already cover parts of this problem, and the design below is built to fit them rather than duplicate them:

- **`document_template_registry`** (Sheets, live, in use) — the *catalog* of required documents per Business/Service/Template/Template-Stage: `Document Template ID, Biz ID, Service ID, Template ID, Template Stage ID, Title, Document Type, Description, Drive File ID, Google Drive, Version, Status, Notes, Created At, Last Updated`. This already answers "what documents are needed for this kind of stage" at the *template* level. ROADMAP_STAGES already links to it via `Document Template IDs` (Phase 8C knowledge binding).
- **`ROADMAP_STAGES.Docs Required` / `Docs Received`** (Sheets, live, in use) — free-text summary copied from the template at roadmap-creation time. This is a snapshot, not a tracked entity — no per-document status, no Drive link, no versioning.
- **`materials` sheet + `business_core/material_manager.py`** — a `Material` dataclass module (Phase ~7) with fields almost identical to what a "document instance" needs (`Roadmap ID`, `Stage ID`, `Client ID`, `Drive URL`, `File Type`, `Status`, `Checked By`, `Approved At`) plus a `check_stage_documents()` matching function. **It is dead code**: not imported anywhere in `telegram_handlers.py`, no registered command, and the live `materials` sheet has 0 data rows in production. It was never wired up.

**Design conclusion used throughout this document:** Document Registry is not a fourth parallel concept — it is the *instance-level* entity that `materials`/`material_manager.py` was meant to become but never did, wired against the *template-level* catalog that `document_template_registry` already provides. Section 10 (Migration) and Section 12 (Risks) treat `materials`/`material_manager.py` as material to retire, not preserve.

---

## 1. Entity model

```
Document
├── document_id            DOC-xxxxxx (own ID space, not reused MAT-/DOC template ID)
├── business_id             → BIZ_REGISTRY
├── client_id                → PEOPLE_REGISTRY               (optional — some docs are object-only)
├── object_id                 → OBJECT_REGISTRY               (optional — some docs are client-only,
│                                                                e.g. passport copy before any object exists)
├── roadmap_id                → ROADMAPS                       (optional — doc can be uploaded pre-roadmap)
├── stage_id                    → ROADMAP_STAGES                 (optional — doc can be roadmap-level,
│                                                                not tied to one stage, e.g. a contract)
├── document_template_id      → DOCUMENT_TEMPLATE_REGISTRY      (optional — link to "what this satisfies";
│                                                                  empty for ad-hoc uploads with no
│                                                                  matching template)
├── title                        display name, independent of filename
├── document_type              enum, see §8-adjacent classification below
├── status                     see §8
├── version                    integer, 1-based (see §6)
├── is_current_version         bool — exactly one TRUE per (document_family_id)
├── document_family_id       groups versions of "the same document" together (see §6)
├── drive_file_id              Google Drive file ID of THIS version
├── drive_url                    convenience — derived, not authoritative
├── filename                    original filename as uploaded
├── file_size_kb
├── source                      Telegram / Drive / WhatsApp / manual — reuses material_manager's enum
├── uploaded_by                 Telegram user id/username of uploader
├── uploaded_at
├── checked_by                  staff who reviewed it
├── checked_at
├── rejection_reason           only meaningful when status=rejected
├── notes
├── created_at
└── last_updated
```

Design choices:
- **All of `client_id`/`object_id`/`roadmap_id`/`stage_id` are optional and independent**, not a strict hierarchy chain. A passport copy can exist against a client before any object/roadmap exists. A contract can be roadmap-level, not stage-level. This mirrors how `MATERIALS` was already designed (`Business ID, Client ID, Roadmap ID, Stage ID` as independent optional columns), and avoids forcing premature structure.
- **`document_family_id` is separate from `document_id`** specifically to support versioning (§6) without overloading the primary key.

---

## 2. Google Sheets schema

New sheet: **`DOCUMENT_REGISTRY`** (`document_registry` key in `BUSINESS_SHEET_NAMES`/`BUSINESS_HEADERS`, matching the existing naming convention).

```python
"document_registry": [
    "Document ID", "Document Family ID", "Version", "Is Current Version",
    "Business ID", "Client ID", "Object ID", "Roadmap ID", "Stage ID",
    "Document Template ID",
    "Title", "Document Type", "Status",
    "Drive File ID", "Google Drive", "Filename", "File Size KB",
    "Source", "Uploaded By", "Uploaded At",
    "Checked By", "Checked At", "Rejection Reason",
    "Notes", "Created At", "Last Updated",
],
```

25 columns. Follows the project's existing conventions exactly:
- Header-safe: written/read only via `row_from_header_map()` / `read_business_sheet()` by header name, never by position (same discipline as every other Business Core sheet since Phase 10.2B).
- First column is the primary ID (`Document ID`) — required for `find_row_by_id()` to work unmodified.
- All foreign keys stored as plain ID strings (`RM-001`, `OBJ-001`, ...), never nested objects — matches every other sheet.

No changes to any existing sheet's schema. `ROADMAP_STAGES.Docs Required`/`Docs Received` are left exactly as-is (see §7 for how they coexist).

---

## 3. ID strategy

- **Prefix:** `DOC-` (e.g. `DOC-000123`), via the existing `generate_next_id("document_registry", "DOC")` / `_ID_PREFIXES` mechanism — no new ID-generation code path needed, reuses `business_core/sheets.py`'s existing infra untouched.
- **Collision note:** `document_template_registry` already uses IDs with a different prefix (`Document Template ID` uses generated IDs from `generate_document_template_id()` in `knowledge_manager.py` — need to confirm at implementation time it doesn't also use bare `DOC-`; if it does, Document Registry should use `DOCU-` or `DREG-` instead to avoid ambiguity in free-text search/grep. **Action item for implementation phase, not a blocker for this design.**
- **Versioning and IDs:** each version gets its **own** `Document ID` (immutable, append-only, matches the project's "never mutate identity columns" rule used everywhere from Phase 11J onward). `Document Family ID` is what stays constant across versions — itself just the *first* version's `Document ID`, needing no separate generator.
- **Batch creation risk (Phase 11F lesson, directly applicable):** if a future bulk-upload command ever creates multiple Document rows in one batch write, it **must** use a `generate_next_ids(sheet_key, count)`-style single-read reservation, exactly like the Phase 11F fix for `ROADMAP_STAGES` — this is the single most important lesson from this project's history to carry into Document Registry from day one, since the same bug class (duplicate IDs from per-row `generate_next_id()` calls inside a pre-batch loop) is trivially reproducible here too if not designed against explicitly.

---

## 4. Relationships (Business / Client / Object / Roadmap / Stage / Document)

```
BIZ_REGISTRY (BIZ-001)
   │
   ├── PEOPLE_REGISTRY (PRS-001)  ── client_id
   │       │
   │       └── OBJECT_REGISTRY (OBJ-001)  ── object_id
   │               │
   │               └── ROADMAPS (RM-001)  ── roadmap_id
   │                       │
   │                       └── ROADMAP_STAGES (STAGE-001..008)  ── stage_id
   │
   └── DOCUMENT_TEMPLATE_REGISTRY (per Service/Template/TemplateStage)
           │  (document_template_id — "what this document satisfies")
           ▼
   DOCUMENT_REGISTRY (DOC-000123)
       ── business_id  (always required)
       ── client_id     (optional)
       ── object_id       (optional)
       ── roadmap_id        (optional)
       ── stage_id            (optional)
       ── document_template_id (optional)
```

- **Business ID is the only mandatory link** — every document belongs to exactly one business, matching how every other Business Core entity is scoped.
- All other links are **optional and independently settable** (not a required chain) — a document can be attached at whatever level makes sense (client-level passport, object-level cadastral extract, roadmap-level contract, stage-level technical report).
- **Referential integrity is checked, not enforced** at write time — same philosophy as the rest of Business Core (e.g. `/report`'s "Roadmap без объекта" orphan check is a *report*, not a database constraint, because Google Sheets has no foreign keys). Document Registry gets the equivalent: `/report` gains an "Orphan documents" line (documents whose `client_id`/`object_id`/`roadmap_id`/`stage_id`, when set, point to a non-existent row).

---

## 5. Drive integration

Reuses `integrations/google_drive_adapter.py` and `business_core/business_builder.py`'s existing provisioning patterns — **no new Drive API code**, only new call sites:

- **Storage location:** documents live inside the *existing* object/client Drive folder structure (`01 Документы от клиента`, `02 Документы наши`, already provisioned by `provision_client_drive()`/`create_object_folder()`), not a new top-level Drive tree. This matches the standing rule (confirmed repeatedly across phases 11H/11J) that Drive folder structure is provisioned once and not casually restructured.
- **Upload flow:** Telegram file upload → `upload_file()` (already exists in `google_drive_adapter.py`, used nowhere yet — same "built but unwired" situation as `material_manager.py`) → target folder resolved from the document's `client_id`/`object_id` via the existing `provision_client_drive`/`provision_object_drive` idempotent lookups → `Drive File ID` stored on the Document Registry row.
- **`Google Drive` column** is a convenience URL derived from `Drive File ID` at write time (`get_file_url()` already exists) — never independently edited, to avoid the two-source-of-truth drift the project explicitly fixed for Business IDs in Phase 13A (`resolve_business()`). This is a direct lesson-transfer: **store the canonical ID, derive the display URL, never let a human free-type the derived value.**
- **No new Drive folder types.** Documents are files inside existing folders, not folders themselves.

---

## 6. Versioning

- **Model:** append-only. Uploading a new version of an existing document creates a **new row** (new `Document ID`, same `Document Family ID`, `Version = previous + 1`, `Is Current Version = TRUE`), and flips the previous row's `Is Current Version` to `FALSE`. This is two single-cell writes (old row's flag, new row's flag/values) plus one append — the same "point write only what's needed, re-read after" discipline used everywhere since Phase 11J/13A.
- **Why append-only, not overwrite-in-place:** overwriting a Drive file / Sheets row in place would destroy audit history (who uploaded what, when, and what the previous version looked like) — directly contrary to this project's established value of preserving history over convenience (see the SHA-256 backup discipline used before every destructive Sheets operation across ~15 phases).
- **Drive-side versioning is NOT delegated to Google Drive's native file revision history** — each version is a **distinct Drive file** (matching the "distinct row per version" model), because Google Drive's native revision history is not queryable via the Sheets-based architecture this project uses, and would be invisible to `/report`-style auditing.
- **Command surface:** re-uploading against an existing `document_family_id` is a normal "new document, same family" operation from the command's point of view — no separate "version bump" command needed in the Telegram UX (§9).

---

## 7. Required Docs vs Uploaded Docs

Two distinct, already-partially-existing concepts, kept distinct rather than merged:

| Concept | Where it lives | What it answers |
|---|---|---|
| **Required** (template-level) | `DOCUMENT_TEMPLATE_REGISTRY` (existing) + `ROADMAP_STAGES.Docs Required` (existing, free-text snapshot at roadmap-creation time) | "What documents does this *kind* of stage need, in general?" |
| **Uploaded** (instance-level) | **New `DOCUMENT_REGISTRY`** | "What has actually been received for *this specific* roadmap/stage/client, and what state is it in?" |

- `ROADMAP_STAGES.Docs Required`/`Docs Received` are **left untouched** — they remain the lightweight free-text summary they already are (populated once from the template at roadmap creation, per the existing `create_stages_from_template_record()` behavior). Document Registry does not replace them; it becomes the detailed, queryable source of truth that `Docs Received`'s free text could never be.
- **"Ready" computation** (does this stage have everything it needs) becomes a *derived* value: for each `Document Template ID` referenced by the stage's `Document Template IDs` column, does a `DOCUMENT_REGISTRY` row exist with matching `document_template_id` + `stage_id` + `status IN (approved, received)`? This directly replaces `material_manager.py`'s dead `check_stage_documents()` keyword-matching heuristic (§0) with an exact ID-based match — strictly more reliable, and finally wired to something real.
- **Ad-hoc uploads** (a document with no matching template — e.g. a client sends an unusual extra file) are fully supported: `document_template_id` is simply left empty. They show up under "uploaded but not required" rather than being rejected or forced into a template slot.

---

## 8. Document statuses

Canonical status set (mirrors the `STAGE_STATUS_CANONICAL` pattern from `roadmap_manager.py` — a small, explicit tuple validated on write, not a free-text field):

```python
DOCUMENT_STATUS_CANONICAL = ("pending_review", "approved", "rejected", "expired")
```

- **`pending_review`** — uploaded, not yet checked by staff. Default status on upload.
- **`approved`** — staff confirmed it satisfies the requirement. Sets `Checked By`/`Checked At`.
- **`rejected`** — staff rejected it (wrong document, illegible scan, etc). Requires non-empty `Rejection Reason` — mirrors the Phase 14A `/blockstage` rule ("обязательная непустая причина"), applied to the same kind of "must explain why" UX.
- **`expired`** — for documents with a real-world validity window (e.g. a technical report valid for 6 months). Not auto-transitioned in this design (see §12 — deliberately deferred, not a "not implemented" gap) — an explicit `/expiredoc` command or a scheduled job could set it later; out of scope for the first cut.

No `done`/`skipped`/`in_progress` analogues — a document doesn't have a lifecycle shaped like a stage's; it's binary-ish (received → judged good or bad), which is why it gets its own status set rather than reusing `STAGE_STATUS_CANONICAL`.

---

## 9. Telegram commands

Following the exact architecture pattern established across Phases 13A/14A (immutable confirmation snapshot, shared `_xxx_edit_start`/`_xxx_edit_execute` core, per-command snapshot key, re-read-before-write, old→new confirmation, state cleanup on every terminal outcome):

| Command | Purpose | Write? |
|---|---|---|
| `/uploaddoc` (reply to a Telegram file message) `client_id=... object_id=... roadmap_id=... stage_id=... template_id=... title="..."` | Register a new document (or new version, if `document_family_id=` given) | Yes — append |
| `/doc document_id=DOC-000123` | Read-only full card: all fields, current version marker, link to prior versions of the same family | No |
| `/docs4stage stage_id=STAGE-001` | Read-only list: required (from template) vs uploaded (from registry), what's missing | No |
| `/approvedoc document_id=...` | Set `status=approved`, `Checked By`/`Checked At` | Yes — confirm flow |
| `/rejectdoc document_id=... reason="..."` | Set `status=rejected` + `Rejection Reason` (non-empty, same rule as `/blockstage`) | Yes — confirm flow |
| `/docversions document_family_id=...` | Read-only: full version history of one document family | No |

Deliberately **not** included in the first cut (mirrors Phase 14A's discipline of trimming scope rather than over-building):
- No `/editdoc` for arbitrary field edits — title/type corrections can be added later the same way `/editclient`/`/editobject` were added *after* `/newclient`/`/newobject` proved out, not before.
- No auto-expiry scheduler (§8).
- No bulk-upload command (avoids the batch-ID-generation risk in §3 until it's actually needed).

---

## 10. Migration strategy

Three independent tracks, each safe to do separately:

1. **New sheet creation** — `init_business_core_sheets()`-style: add `document_registry` to `BUSINESS_HEADERS`/`BUSINESS_SHEET_NAMES`, create the sheet with headers via the existing `ensure_headers()` idempotent path. Zero risk — pure addition, no existing sheet touched.
2. **Retire `materials`/`material_manager.py`** (recommended, not required): since the live `materials` sheet has 0 data rows and `material_manager.py` has zero call sites in `telegram_handlers.py`, this is a **zero-data-loss** removal. Proposed sequence, following this project's standing deletion protocol (backup → manifest → SHA-verify → delete, never skip steps even for an empty sheet):
   - Read-only confirm `materials` still has 0 rows at implementation time.
   - Backup the (empty) sheet + `material_manager.py` source for the record.
   - Remove the sheet from `BUSINESS_HEADERS`/`BUSINESS_SHEET_NAMES` (code change) and archive `material_manager.py` (do not silently delete — rename to `material_manager.py.deprecated` or move under a clearly-marked path, consistent with never deleting code outright without a dedicated phase).
   - This is optional and can be its own later phase — Document Registry does not depend on it happening first.
3. **No migration of `ROADMAP_STAGES.Docs Required`/`Docs Received` data** — they stay as-is (§7); Document Registry is additive, not a replacement for that column.

No live Sheet is modified as part of *this* design phase — all three tracks are implementation-phase work, explicitly not authorized here.

---

## 11. Backward compatibility

- **Zero impact on existing sheets** — `ROADMAP_STAGES`, `OBJECT_REGISTRY`, `PEOPLE_REGISTRY`, `ROADMAPS`, `DOCUMENT_TEMPLATE_REGISTRY` schemas are untouched.
- **Zero impact on existing commands** — `/stage`, `/stages`, `/report`, `/updatestage`, `/assignstage`, `/duedate`, `/priority`, `/blockstage`, `/unblockstage`, `/editclient`, `/editobject`, `/newclient`, `/newobject`, `/startroadmap` all continue to work unmodified; Document Registry is a net-new sheet + net-new commands only.
- **`/report` gains new lines** (document counts, orphan documents, pending-review count) but its existing lines (Clients/Objects/Roadmaps/Stages/Progress/BIZ-TEST-adjacent counts) are unaffected — same additive pattern as every prior `/report` extension.
- **Existing roadmaps/stages created before Document Registry exists** work correctly with zero linked documents — `/docs4stage` on such a stage simply reports "0 uploaded" against whatever the template says is required, no error, no special-casing needed (mirrors the Phase 14A backward-compatibility guarantee for short/old rows).

---

## 12. Risks and alternative approaches considered

**Risks:**
- **ID prefix collision** between `DOC-` (proposed for Document Registry) and any existing/future use of that prefix elsewhere — flagged in §3 as an implementation-time check, not resolved here.
- **Drive API quota** — file uploads are heavier API calls than Sheets writes; a busy staff member bulk-uploading many documents could hit rate limits faster than any Sheets-only command has so far (this project has repeatedly hit 429s on Sheets alone). Mitigate by not building a bulk-upload command in the first cut (§9).
- **"Ready" derivation correctness** depends on `Document Template IDs` actually being populated on `ROADMAP_STAGES` — today this is populated via Phase 8C's knowledge-binding path, but only for templates that have `document_template_id` links configured; templates without them will show "0 required" rather than a meaningful gap. Acceptable for v1, worth flagging.
- **Two "document" concepts already exist in the codebase** (`document_template_registry` for templates, dead `materials`/`Material` for instances) — the biggest real risk is a future contributor (or a future me) reviving `material_manager.py` in parallel with Document Registry, recreating the exact duplication this design tries to avoid. Mitigated by explicitly recommending retirement in §10, not just silent non-use.

**Alternatives considered and rejected:**
- **Extend `MATERIALS` in place instead of creating `DOCUMENT_REGISTRY`.** Rejected: `MATERIALS`' schema is missing versioning fields, canonical status, and a template link column; retrofitting all of that onto a sheet named "materials" (a name that doesn't read as "documents" to a non-technical business owner) seemed worse than a clean new sheet plus an explicit, disclosed retirement of the old one.
- **Store document metadata as columns directly on `ROADMAP_STAGES`** (e.g. `Doc 1 Status`, `Doc 2 Status`, ...). Rejected: unbounded/variable number of documents per stage, no support for multiple documents per requirement or ad-hoc uploads, and it's exactly the fixed-column-per-slot anti-pattern this project has avoided everywhere else (e.g. `ROADMAPS.Stage 1 Status`..`Stage 10 Status` already exists as legacy cruft from an earlier design and is not extended further by newer phases).
- **Native Google Drive revision history instead of append-only Sheets rows for versioning.** Rejected in §6 — not queryable/auditable through this project's Sheets-centric reporting model.
- **Strict enforced parent hierarchy** (Document must have Stage, Stage's Roadmap must have Object, etc.) instead of independent optional links. Rejected: contradicts real workflow (client documents arrive before an object exists) and contradicts the project's existing tolerance for optional/soft links enforced by reporting rather than write-time constraints (§4).

---

**Verdict of this phase: design only, no code.** Awaiting direction on whether to proceed to implementation, and if so, whether Track 2 of §10 (retiring `materials`) should be bundled into the first implementation phase or deferred.
