# Secure Business Core Mutation Command Pattern

**Status:** ADOPTED ARCHITECTURE STANDARD

**Applies to:** Future authorized Business Core mutation commands (Telegram
handlers registered in `business_core/telegram_handlers.py` that write to a
Google Sheets-backed registry and are gated through
`COMMAND_ENFORCEMENT_MAP`).

**Source of truth:** `business_core/telegram_handlers.py` as of commit
`5ad8dfad933cb1e8fcbeb6be3466abae3e4ed5d8` (deployment
`b8576028-f4d7-4c46-96ce-c2021ba799a1`). Every claim in this document is
verified against that source, not against prior chat discussion.

**Does not automatically apply to:**

- CREATE operations (no existing target row to authorize against before the
  write; not exercised by any of the eight commands this document is based
  on).
- Append-only operations.
- Operations with an external, irreversible side effect (e.g. sending an
  email, charging a real payment processor).
- Commands that lack a trusted canonical finder for their target.
- Operations that would require source-level locking to be correct.
- Genuinely `NON_IDEMPOTENT` mutations (see §8).

Each of the above requires its own, separately-scoped architecture review
before this pattern — or any variant of it — is applied.

---

## 1. Purpose and Principles

This pattern exists to guarantee, for every authorized mutation command:

- Caller-supplied input never establishes ownership of the target record.
- Authorization is evaluated against **stored, canonical** ownership — read
  from the target's own row, never from what the caller typed.
- Target ownership is **reread** after authorization succeeds and compared
  against what was authorized, closing the window where authorization could
  go stale between the check and the write.
- The mutation itself is invoked **exactly once**, off the event loop, with
  no handler-level retry.
- Handlers do not duplicate business logic (state-transition rules, balance
  arithmetic, validation) that belongs in `business_builder.py` / the
  manager layer.
- Every failure mode — missing row, authorization denial, infrastructure
  exception, stale ownership — fails closed: no mutation occurs.
- Secrets (exception text, raw rows, actor identities, financial values,
  free-text content) never enter logs or Telegram replies.
- Domain-specific security decisions (which fields to compare, whether a
  relationship ID may be blank, argument names) stay visible in each
  command's own source, not hidden behind a generic helper.
- Runtime abstraction beyond the four helpers already shared (§22) is
  deliberately deferred until a genuinely different mutation domain has
  validated the pattern (§23).

---

## 2. Canonical Pipeline

Every one of the eight currently authorized mutation commands
(`updateinteractionnotes_cmd`, `updateleadnotes_cmd`,
`updateobligationnotes_cmd`, `updateoffernotes_cmd`, `updatedocnotes_cmd`,
`failpayment_cmd`, `confirmpayment_cmd`, `reversepayment_cmd`) implements
this exact 14-step sequence, in this exact order, with no step reordered or
skipped.

| # | Step | Status | Purpose | Allowed | Prohibited | On failure |
|---|---|---|---|---|---|---|
| 1 | `_is_bc_enabled()` check | **REQUIRED** | Global feature gate | Early return with the disabled message | Proceeding past this check when disabled | Fixed disabled message, no further processing |
| 2 | `_validate_bc_transport_or_reply(update)` | **REQUIRED** | Reject non-private chats, malformed updates, missing Telegram user | Structural checks only (chat type, user id presence) | Any Sheets/authorization read at this stage | Fixed transport-rejection reply or silent return (malformed update); zero finder/authorization/mutation calls |
| 3 | `_parse_kv_args(raw)` | **REQUIRED** | Turn the raw command text into a key→value dict | Standard `key=value` / quoted-value / positional (`_posN`) parsing | — | N/A (parser itself does not fail) |
| 4 | Allowed-key validation (`set(args.keys()) <= _<COMMAND>_ALLOWED_KEYS`) | **REQUIRED** | Reject any unsupported key before any lookup | An explicit, per-command `frozenset` | Accepting keys not in the frozenset; echoing the rejected key/value | Fixed usage message, zero finder/authorization/mutation calls |
| 5 | Required-value validation | **REQUIRED** | Reject missing/blank required arguments | `if not x or not y: ...` style checks | — | Fixed usage message, zero finder/authorization/mutation calls |
| 6 | First trusted target lookup via `_resolve_target_in_thread(finder, id)` | **REQUIRED** | Resolve the target row using the caller-supplied ID as a lookup key only | Exactly one call to the canonical finder, thread-offloaded | Direct synchronous finder call; direct Sheets access; using a cache | Own try/except around this call → fixed temporarily-unavailable reply on exception |
| 7 | Stored ownership/relationship/state extraction | **REQUIRED** (ownership); **CONDITIONAL** (relationship/state, domain-specific) | Pull only the fields this command needs, from the row, never from caller input | `.get(field, "").strip()` | Trusting a caller-supplied `business_id`/`object_id`/similar | Fixed not-found/denied reply if the row is `None`/non-dict or a required field is blank |
| 8 | `_authorize_or_reply(...)` — exactly once | **REQUIRED** | Ask the Authorization Domain whether this identity may perform this action on this stored target | `resource`, `action`, `business_id` (+ `object_id` for `BUSINESS_AND_OBJECT`) from the map/stored row | Calling `authorization.py` directly; passing a caller-supplied identifier; calling more than once | Immediate return on denial or infrastructure failure; zero second lookup; zero mutation |
| 9 | Mandatory fresh reread via `_resolve_target_in_thread(finder, id)` | **REQUIRED** | Re-verify the target still has the ownership/relationship/state that was just authorized | Same finder, same ID, exactly once, only after step 8 succeeds | Skipping this step; reauthorizing instead of comparing; retrying | Own try/except → fixed temporarily-unavailable reply on exception |
| 10 | Stability comparison | **REQUIRED** | Detect any change between the first and second read | Exact-equality comparison of the declared field set (§13) | A universal hardcoded field list applied to every command regardless of domain | Fixed ownership-changed reply on any mismatch/disappearance; zero mutation, zero reauthorization |
| 11 | Mutation via `_mutate_target_in_thread(wrapper, *args)` — exactly once | **REQUIRED** | Perform the actual write | Exactly one call, thread-offloaded, to the domain's canonical `business_builder` wrapper | Direct manager call; direct Sheets write; any retry loop | Own try/except → fixed infrastructure-failure log + fixed reply on exception |
| 12 | Safe result mapper | **REQUIRED** | Convert the wrapper's structured result into Russian-language UX text | Type-checked, `ok is True`-gated, fixed-fallback mapper function | Rendering `result["error"]`; rendering raw exception text | Falls through to a fixed generic failure message on any unmapped/malformed shape |
| 13 | Fixed user reply | **REQUIRED** | Send the mapper's output | `_reply(update, mapper_output, parse_mode=None)` | — | — |
| 14 | Fixed-safe exception boundaries | **REQUIRED** | Isolate failures at each of the three lookup/mutation steps independently | A separate `try/except` per step (6, 9, 11), each with its own fixed message; an outer last-resort boundary where present | Log calls with dynamic content — `log.exception`, `exc_info=True`, `str(exc)`/`repr(exc)`/`format(exc)`, f-string interpolation of the exception | See rows 6/9/11 above |

---

## 3. Command Specification Template

Every future mutation command must have this specification written and
reviewed **before** any code is written.

```
Command name:
Purpose:
Resource:                          (BUSINESS | CLIENT | FINANCE | DOCUMENT | ...)
Action:                            (READ | UPDATE | CREATE | ARCHIVE | ASSIGN)
Target shape:                      (BUSINESS | BUSINESS_AND_OBJECT)
Operation kind:                    (MUTATION)
Mutation side-effect class:        (SINGLE_ROW_MUTATION | MULTI_ROW_MUTATION)
Idempotency class:                 (IDEMPOTENT | NON_IDEMPOTENT — see §8 before selecting NON_IDEMPOTENT)
Caller-supplied identifiers:       (which argument names the caller may legitimately supply)
Trusted finder:                    (exact function, exact module)
Stored ownership fields:           (exact field name(s), exact casing)
Stored relationship fields:        (if any; blank-tolerance decision + justification, see §11)
Stored state fields:               (if any; compared or not, and why)
Allowed arguments:                 (exact frozenset)
Required arguments:                (subset of allowed, non-blank)
Transport policy:                  (_validate_bc_transport_or_reply — always required)
Authorization call:                (resource / action / business_id [/ object_id])
Fresh-reread comparison set:       (exact fields, justified per §13)
Mutation wrapper:                  (exact business_builder function + signature)
Mutation argument order:           (exact positional order)
Mapper:                            (exact function; confirm reused or new)
Retry policy:                      (none — handler layer never retries)
Partial-state policy:              (N/A for SINGLE_ROW; explicit warning path required for MULTI_ROW)
Secrecy markers:                   (which test markers cover this command)
Production smoke policy:           (NO_SAFE_PRODUCTION_SMOKE_TEST unless explicitly justified otherwise)
Residual risks:                    (TOCTOU, concurrency, anything domain-specific)
Required tests:                    (transport, arguments, first-lookup, authorization, fresh-reread, mutation, security-marker, architecture-guard)
Required architecture guards:      (instantiate the catalog in §19 for this command)
Definition of done:                (see §24)
```

---

## 4. Mutation Side-Effect Classes

### `SINGLE_ROW_MUTATION`

Source-backed properties (confirmed across `updateinteractionnotes`,
`updateleadnotes`, `updateobligationnotes`, `updateoffernotes`,
`updatedocnotes`, `failpayment`):

- Exactly one logical row is changed by the mutation wrapper.
- A trusted first lookup is required.
- A fresh reread is required (`requires_fresh_reread: True` on every
  observed entry).
- No handler-level retry.
- The mutation helper is called exactly once.
- Partial cross-row state is not applicable — there is no second row to
  partially fail.
- Concurrency TOCTOU between the reread and the write remains possible; no
  source-level lock exists for any of these commands.

### `MULTI_ROW_MUTATION`

Source-backed properties (confirmed across `confirmpayment`,
`reversepayment` only):

- One wrapper call (`confirm_payment_transaction` /
  `reverse_payment_transaction`) may update more than one row (Transaction
  and, when applicable, Obligation).
- The relationship ID (`Payment Obligation ID`) is mandatory (non-blank)
  at both lookups — see §11.
- Ownership, relationship, **and** state stability are all compared at the
  fresh reread (three fields, not one).
- No handler-level retry.
- The mutation helper is called exactly once.
- The result may represent a **partial-state** outcome (first write
  succeeded, second write failed) — this must remain visible to the caller
  as a distinct warning, never collapsed into clean success or hard
  failure (§16).
- No atomicity or rollback is claimed or implemented anywhere in this
  codebase for multi-row mutations.

**Approved example — `failpayment` vs. `confirmpayment`/`reversepayment`:**
`failpayment_cmd` treats a blank `Payment Obligation ID` as acceptable at
both lookups, because `fail_payment_transaction` never touches the
Obligation row. `confirmpayment_cmd`/`reversepayment_cmd` reject a blank
`Payment Obligation ID` at both lookups, because both wrappers synchronize
the Obligation's balance/status. This is the concrete evidence that
mutation-class classification changes lookup requirements, not just naming.

Future `MULTI_ROW_MUTATION` commands are **not** guaranteed to share
Payment's exact comparison field set — the fields to compare must be
re-derived from that command's own domain, per §13.

---

## 5. Idempotency Classes

### `IDEMPOTENT`

Source-backed properties (the only idempotency class currently in use — all
14 map entries, all 8 mutation commands):

- Duplicate delivery of the same command against the same target may
  legitimately result in an `ok=True, changed=False` (unchanged/no-op)
  outcome, produced entirely inside `business_builder`'s own status-guard
  logic.
- The Telegram handler never retries; "idempotent" describes tolerance of
  external duplicate delivery (a user double-tapping, Telegram redelivering
  an update), not permission for the handler to self-retry.
- The mapper must render the unchanged/no-op outcome distinctly from the
  success outcome (a fixed `"ℹ️ ... изменений нет."`-style message,
  confirmed present in every mapper this pattern covers).
- Duplicate-delivery protection belongs entirely in the business/storage
  layer — the handler's fresh reread protects against authorization
  staleness, a different concern from duplicate-delivery tolerance.
- Concurrent execution remains a residual risk: no source-level locking
  exists anywhere in this codebase. Two simultaneous invocations that both
  pass the reread check could both proceed to write; the outcome then
  depends on whatever ordering the underlying Sheets API provides at that
  instant, which this pattern does not verify or guarantee.

### `NON_IDEMPOTENT`

**`NOT_PROVEN_FROM_CURRENT_AUTHORIZED_COMMANDS`** — no entry in
`COMMAND_ENFORCEMENT_MAP` currently declares this class, and none of the
eight authorized mutation commands exercises it.

If a future command is genuinely non-idempotent (repeated delivery would
legitimately perform a second, distinct effect — e.g. an append-only ledger
entry), this pattern **alone is insufficient**. That command requires:

- A separate, explicitly-scoped architecture review before implementation.
- An explicit idempotency-key or equivalent duplicate-suppression
  mechanism at the business/storage layer (this codebase already has a
  working precedent for the *shape* of such a mechanism —
  `caller_idempotency_key`/`external_transaction_id` on
  `create_payment_transaction` — though that command itself is a CREATE
  operation, outside `COMMAND_ENFORCEMENT_MAP`, and outside the scope of
  this pattern).
- Explicit acknowledgment that concurrent-execution risk is strictly worse
  than the `IDEMPOTENT` case: two concurrent calls could both succeed and
  both apply their effect, with nothing in this pattern to collapse them.

---

## 6. Target Shapes

Only two target shapes appear in `COMMAND_ENFORCEMENT_MAP` today.

### `BUSINESS`

- Stored `Business ID` (or `business_id`, per the domain's own casing
  convention) is required, non-blank, at both the first lookup and the
  reread.
- `object_id` is omitted entirely from the `_authorize_or_reply` call (not
  passed as an empty string).
- The caller cannot supply a trusted ownership value — the only permitted
  caller input is the target's own ID (used purely as a lookup key), and
  domain fields such as `business_id`/`amount`/`status` are always in the
  rejected-key set.

### `BUSINESS_AND_OBJECT`

- Confirmed only for `updatedocnotes` (`resource=DOCUMENT`). Both stored
  `business_id` and `object_id` are required, non-blank, at both the first
  lookup and the reread.
- Both are passed to `_authorize_or_reply` (`business_id=..., object_id=...`).
- Both are re-verified unchanged on the mandatory second lookup, exactly
  like `Business ID` alone is for the `BUSINESS`-shaped commands.

`authorization.py`'s own `_OBJECT_ADDRESSABLE_RESOURCES` constant lists
`{"OBJECT", "DOCUMENT", "OPERATIONAL"}`, implying `OBJECT`/`OPERATIONAL`
resources would structurally require this same shape — but no live
**mutation** entry in `COMMAND_ENFORCEMENT_MAP` currently uses
`resource=OBJECT` or `resource=OPERATIONAL`. That specific combination is
`NOT_PROVEN_FROM_MUTATION_SOURCE`: proven only for `DOCUMENT`, inferred by
structural symmetry (not verified in practice) for the other two.

---

## 7. Trusted Finder Contract

Confirmed identical across all eight commands:

- Exactly one canonical finder per domain (`find_payment_transaction_by_id`,
  `find_interaction_by_id`, `find_lead_by_id`,
  `find_payment_obligation_by_id`, `find_commercial_offer_by_id`,
  `find_document_by_id`) — never a list/filter/search helper.
- Always invoked via `_resolve_target_in_thread(finder, id)`, never called
  synchronously or directly.
- No direct Sheets access (`get_business_sheet(`, `update_cell(`,
  `find_row_by_id(`) anywhere in any of the eight handler bodies.
- No cache of any kind near an authorization-sensitive lookup.
- The caller-supplied ID selects a **candidate** target only; it is never
  itself trusted as an ownership claim. Ownership always comes from the
  row the finder returns.
- A `None` or non-dict result fails closed.
- A finder exception fails closed (caught by the step's own try/except,
  never propagated raw).
- The raw row is never logged or rendered — only individual scalar fields,
  extracted with `.get(key, "").strip()`.

**Field-casing warning:** Payment rows (`payment_transactions`,
`payment_obligations`) use title-case keys (`"Business ID"`,
`"Payment Obligation ID"`, `"Status"`). Document rows use snake_case keys
(`"business_id"`, `"object_id"`). The exact key names and casing must be
declared per command in its specification (§3) — do not assume one
convention applies project-wide.

---

## 8. Blank-Field Policy

Blank-field requirements are **domain-specific** and must be justified per
command, not assumed by analogy.

**Approved source-backed example:**

| Command | `Payment Obligation ID` policy | Why |
|---|---|---|
| `failpayment` | May be blank at both lookups | `fail_payment_transaction` never touches the Obligation row |
| `confirmpayment` / `reversepayment` | Must be non-blank at both lookups | Both wrappers synchronize the Obligation's balance/status |

There is no generic rule that relationship fields are "always optional" or
"always required." Each future command must state and justify its own
blank-field policy explicitly in its specification (§3).

---

## 9. Authorization Contract

- The first lookup always happens **before** authorization — authorization
  is evaluated against what the first lookup found, never against
  caller-supplied values.
- `_authorize_or_reply(update, resource=..., action=..., business_id=...[, object_id=...])`
  is called **exactly once** per invocation.
- `resource` and `action` come from the command's declared
  `COMMAND_ENFORCEMENT_MAP` entry.
- The structural target shape passed must match what
  `authorization.py`'s `_validate_structural_target` expects for that
  resource (`BUSINESS` → `business_id` only; `BUSINESS_AND_OBJECT` →
  both).
- On denial or authorization-infrastructure failure: immediate return,
  zero second lookup, zero mutation, no financial/business data rendered.
- `authorization.py` is never called directly by any handler — the only
  entry point is `_authorize_or_reply`, which itself calls the full
  `authorize_telegram_business_core_request` adapter (never the
  transport-only preflight) as defense in depth.

**Examples (both source-confirmed):**

```python
# BUSINESS shape
await _authorize_or_reply(update, resource="FINANCE", action="UPDATE", business_id=first_business_id)

# BUSINESS_AND_OBJECT shape
await _authorize_or_reply(update, resource="DOCUMENT", action="UPDATE", business_id=first_business_id, object_id=first_object_id)
```

---

## 10. Fresh-Reread Contract

- Same canonical finder, same target ID as the first lookup.
- The second lookup happens **only** after authorization succeeds — never
  before, never on denial.
- Exactly one second lookup per invocation.
- No reauthorization occurs after the reread, regardless of outcome.
- The declared field set (§13's ownership/relationship/state categories)
  is compared for exact equality between the first and second read.
- On disappearance, malformed result, a required field going blank, an
  exception, or **any** mismatch: zero mutation, fixed
  ownership-changed reply, no record content rendered.

**Comparison categories** (all three observed across the eight commands,
none invented beyond these):

| Category | Example field |
|---|---|
| Ownership | `Business ID` / `business_id` |
| Relationship | `Payment Obligation ID` / `object_id` |
| State | `Status` |

The exact set used by a given command is domain-specific — see the table
in §20. This document does not define a universal hardcoded comparison
list, and none should be created; a shared list risks silently downgrading
a stricter command's contract to a looser one (see §21).

---

## 11. Mutation Boundary

- The only permitted mutation entry point is
  `_mutate_target_in_thread(wrapper, *args)`.
- The exact wrapper signature must be inspected from
  `business_builder.py` source **before** writing the call — do not guess
  argument order.
- Exactly one invocation per command execution.
- No handler-level retry (no `for _ in range`, `while True`, or `retry`
  construct in any of the eight handlers).
- No direct Sheets write and no direct manager-layer call from the handler.
- No external side effect occurs before authorization completes.
- State-transition rules and financial/business calculations stay entirely
  inside `business_builder.py` / the manager layer — confirmed zero diff on
  those files across every phase that authorized a new command.
- Residual TOCTOU remains possible between the reread (§10) and the actual
  write — this pattern narrows the window but does not close it, and no
  source-level lock exists to close it further.

---

## 12. Mapper Contract

A result mapper for this pattern must:

- Type-check the result (`isinstance(result, dict)`) before any `.get()`
  call.
- Require `ok is True` by strict identity, not truthiness.
- Preserve the success outcome distinctly.
- Preserve the unchanged/no-op outcome distinctly (`changed is False`).
- Preserve any invalid-transition outcome with a fixed, non-leaking
  message.
- Preserve any partial-state warning distinctly (§16) — never coerced to
  success or hard failure.
- Handle a malformed or unmapped result shape safely, falling through to a
  fixed fallback message.
- Never render `result["error"]` or any raw exception text.
- Never perform business or financial calculations — every rendered value
  is passed through from a field `business_builder` already computed, not
  recomputed in the mapper.

**Source-backed examples:** `_payment_transaction_confirmation_message`,
`_payment_transaction_reversal_message`, and
`_payment_transaction_failure_message` (all in
`business_core/telegram_handlers.py`) implement this contract in full,
including the partial-state branch. The five Notes-domain mappers
(`_interaction_notes_message`, `_lead_notes_message`,
`_obligation_notes_message`, `_offer_notes_message`,
`_document_notes_message`) implement the same contract without the
partial-state branch, since none of their underlying wrappers touch a
second row.

---

## 13. Partial-State Contract

Relevant only to `MULTI_ROW_MUTATION`.

- The first write (e.g. the Transaction status change) may succeed while
  the second write (e.g. the Obligation balance sync) fails.
- Partial state must never be presented as clean success.
- Partial state must never be hidden as total failure.
- The mapper must render an explicit, distinct manual-review warning
  (confirmed source pattern: `"⚠️ ... Требуется ручная проверка."`).
- No rollback mechanism exists anywhere in this codebase for this
  scenario.
- The underlying result may carry `retry_safe=False` where appropriate —
  this pattern does not itself act on that flag; it only ensures the flag
  and the partial-state code are not lost between the business layer and
  the reply.
- Human reconciliation is the only currently-implemented remediation path.

---

## 14. Argument Policy

- An explicit, per-command `frozenset` names every allowed key.
- Unsupported keys are rejected **before** the first finder call, with a
  fixed usage message — never echoing the caller's actual key or value.
- Required-value checks also occur before the first finder call.
- Legacy positional syntax (a bare, unlabeled argument) is preserved
  **only** by explicit, named approval in that command's own
  implementation phase — it is not a default behavior new commands should
  assume.
- Any compatibility decision (preserving vs. dropping a piece of legacy
  syntax) must be named explicitly in that phase's scope, not silently
  decided.

**Approved legacy example:** `failpayment_cmd` accepts
`{"payment_transaction_id", "_pos0"}` — the bare positional form
(`/failpayment PTXN-001`) was an explicitly preserved piece of pre-existing
syntax when the command was authorized (Phase 17E-2A6-AUTH-B1), not a
default the pattern grants automatically. No other authorized mutation
command accepts a positional argument.

---

## 15. Logging and Secrecy Contract

**Prohibited, unconditionally:**

```
log.exception(...)
exc_info=True
str(exc) / str(e)
repr(exc) / repr(e)
format(exc) / format(e)
f"...{exc}" / f"...{e}"   (any dynamic exception interpolation)
```

Also prohibited in any log call or Telegram reply on any of these paths:
raw target IDs, raw rows, Notes/free-text content, actor names/identities,
reversal reasons, amounts, balances, or raw API payloads.

**Approved form:**

```python
log.error("<command>_cmd mutation infrastructure failure")
```

— a single fixed literal, no interpolation, no exception binding required
(`except Exception:`, not `except Exception as e:`).

**Independent exception boundaries required per command:**

1. First lookup.
2. Authorization adapter (handled internally by `_authorize_or_reply`
   itself — no additional boundary needed in the handler).
3. Second lookup.
4. Mutation helper.
5. An outer last-resort fallback, where present.

Each of steps 1, 3, and 4 has its own dedicated `try/except`, never a
single shared outer catch for these specific boundaries — an exception at
the first lookup produces a different, temporarily-unavailable message
than an exception at the mutation step, and conflating them into one
catch-all would blur that distinction.

**Historical note:** commit `5ad8dfad933cb1e8fcbeb6be3466abae3e4ed5d8`
brought `updateinteractionnotes_cmd` — the one command found, on audit,
still using dynamic f-string exception interpolation — into conformity
with this contract. As of that commit, all eight authorized mutation
commands satisfy it.

---

## 16. Architecture Guard Catalog

The following guard categories should be instantiated (as concrete tests)
for every mutation command authorized under this pattern:

1. Exact enforcement-map entry (resource/action/target_shape/operation_kind/
   requires_fresh_reread/mutation_side_effect_class/idempotency_class).
2. Exact map-size expectation after this command is added.
3. Previous map entries unchanged.
4. Handler step order matches §2.
5. Transport validation occurs before argument parsing.
6. Allowed-key validation occurs before the first finder call.
7. The canonical finder (and only the canonical finder) is used.
8. The finder call is thread-offloaded via `_resolve_target_in_thread`.
9. Stored ownership (never caller input) is used for authorization.
10. Authorization is called exactly once.
11. No second lookup occurs on denial.
12. A second lookup occurs exactly once on allow.
13. The exact declared comparison fields are checked, no more, no fewer.
14. Zero mutation occurs on any reread mismatch.
15. The mutation call is thread-offloaded via `_mutate_target_in_thread`.
16. The mutation call occurs exactly once on the authorized, stable path.
17. No direct Sheets write occurs anywhere in the handler.
18. No cache is used anywhere in the handler.
19. No Object Registry (or other unrelated registry) lookup occurs unless
    the target shape structurally requires it.
20. The mapper is either reused unchanged or explicitly approved as new.
21. The business_builder/manager layer is unchanged, unless that phase's
    scope explicitly approves a change there.
22. Command registration count is exactly one, unchanged in shape.
23. No configured secret marker leaks into logs or replies.
24. The unauthorized path produces zero mutation.
25. The unstable (reread-mismatch) path produces zero mutation.
26. Production integrity (row counts, identity state) is unchanged
    before and after implementation and after deployment.
27. Fixed-literal exception logging is used at every boundary.
28. No exception interpolation of any kind appears in any log call.

**Current implementation state:** these guards exist today as
individually-written, per-command tests distributed across
`test_command_enforcement.py`, `test_mutation_enforcement.py`, and
`test_payment_architecture_guards.py` — not as a shared, parametrized test
module. This document does not propose converting them to a generic
framework in this phase (§23).

---

## 17. Existing Authorized Commands

Source-confirmed as of commit `5ad8dfad933cb1e8fcbeb6be3466abae3e4ed5d8`.

| Command | Resource | Action | Target shape | Side-effect class | Idempotency | Finder | Comparison fields | Mutation wrapper | Partial-state possible? |
|---|---|---|---|---|---|---|---|---|---|
| `updateinteractionnotes` | CLIENT | UPDATE | BUSINESS | SINGLE_ROW_MUTATION | IDEMPOTENT | `find_interaction_by_id` | Business ID | `update_interaction_notes` | No |
| `updateleadnotes` | FINANCE | UPDATE | BUSINESS | SINGLE_ROW_MUTATION | IDEMPOTENT | `find_lead_by_id` | Business ID | `update_lead_admin_fields` | No |
| `updateobligationnotes` | FINANCE | UPDATE | BUSINESS | SINGLE_ROW_MUTATION | IDEMPOTENT | `find_payment_obligation_by_id` | Business ID | `update_payment_obligation_admin_fields` | No |
| `updateoffernotes` | FINANCE | UPDATE | BUSINESS | SINGLE_ROW_MUTATION | IDEMPOTENT | `find_commercial_offer_by_id` | Business ID | `update_commercial_offer_admin_fields` | No |
| `updatedocnotes` | DOCUMENT | UPDATE | BUSINESS_AND_OBJECT | SINGLE_ROW_MUTATION | IDEMPOTENT | `find_document_by_id` | business_id, object_id | `update_document_admin_fields` | No |
| `failpayment` | FINANCE | UPDATE | BUSINESS | SINGLE_ROW_MUTATION | IDEMPOTENT | `find_payment_transaction_by_id` | Business ID, Status | `fail_payment_transaction` | No |
| `confirmpayment` | FINANCE | UPDATE | BUSINESS | MULTI_ROW_MUTATION | IDEMPOTENT | `find_payment_transaction_by_id` | Business ID, Payment Obligation ID, Status | `confirm_payment_transaction` | **Yes** |
| `reversepayment` | FINANCE | UPDATE | BUSINESS | MULTI_ROW_MUTATION | IDEMPOTENT | `find_payment_transaction_by_id` | Business ID, Payment Obligation ID, Status | `reverse_payment_transaction` | **Yes** |

Mapper functions: `_interaction_notes_message`, `_lead_notes_message`,
`_obligation_notes_message`, `_offer_notes_message`,
`_document_notes_message`, `_payment_transaction_failure_message`,
`_payment_transaction_confirmation_message`,
`_payment_transaction_reversal_message` (one per command, in the same
order as the table above).

`COMMAND_ENFORCEMENT_MAP` size at this commit: **14** (6 read-only entries
plus the 8 mutation entries above).

---

## 18. Anti-Abstraction Analysis

The following must remain domain-specific per command, and must **not** be
absorbed into a generic runtime framework:

- The finder (module path and function).
- Stored field names and their casing convention.
- The blank-field policy for relationship fields (§8).
- The exact comparison field set (§10).
- The mutation wrapper's signature and argument order.
- State-transition logic (which status may move to which other status).
- The mapper's success/unchanged/error vocabulary.
- Partial-state semantics (only applicable to some commands, not others).
- The usage/error message text.
- Any legacy syntax exception (e.g. positional arguments).

**Why hiding these behind a generic helper would weaken security:** every
place in this codebase a shared helper already exists (transport
validation, finder offload, mutation offload — §22) is exactly as generic
as it needs to be, because the content at that step genuinely does not
vary by domain. Every place that remains unshared is unshared specifically
*because* the domain content there is where the security-relevant decision
lives. A generic comparator or generic exception-logging wrapper
configured incorrectly for a new command is exactly the kind of change
that could silently downgrade a stricter command's contract to a looser
one, or reintroduce a leak — without anyone noticing, because the
per-command visibility that makes such a mistake easy to catch on review
would be gone.

---

## 19. Current Shared Helpers

The following are already fully generic and already shared across all
eight commands — no further factoring is needed or proposed:

- `_validate_bc_transport_or_reply(update)`
- `_resolve_target_in_thread(finder, id)`
- `_mutate_target_in_thread(wrapper, *args)`
- `_authorize_or_reply(update, *, resource, action, business_id, object_id="")`

No wrapper around the *complete* 14-step pipeline exists, and none is
created by this document.

---

## 20. Abstraction Decision

**Adopted decision:** do not build a generic secure-mutation runtime
framework yet.

**Next step:** implement one additional, genuinely different mutation
domain using the specification template in §3 and the pipeline in §2,
without introducing any new shared abstraction beyond what already exists
(§19). After that domain is authorized and deployed, review whether the
accumulated evidence (now three distinct domains rather than two) justifies
small additional helpers, a broader framework, or continuing to document
and repeat.

**Current classification:**

- `DOCUMENTED STANDARD` — this document.
- `EXISTING SMALL HELPERS` — the four functions in §19, unchanged.
- `NO FULL PIPELINE FACTORY` — not built, not proposed for this phase.

---

## 21. Definition of Done

A future mutation command authorized under this pattern is done only when
**all** of the following hold:

- [ ] The command specification (§3) is written and approved.
- [ ] Exactly the intended `COMMAND_ENFORCEMENT_MAP` entry/entries are
      added, with no unrelated entry changed.
- [ ] Transport is validated before any other processing.
- [ ] Arguments are restricted to an explicit allowed set.
- [ ] Authorization uses only stored, trusted ownership — never
      caller-supplied values.
- [ ] Authorization is called exactly once.
- [ ] The mandatory fresh reread is implemented exactly as specified.
- [ ] The declared comparison field set is implemented and tested.
- [ ] Zero mutation occurs on authorization denial or reread mismatch.
- [ ] The mutation is thread-offloaded and invoked exactly once.
- [ ] The mapper is safe per §12 (and, if `MULTI_ROW_MUTATION`, preserves
      partial-state warnings per §13).
- [ ] All logging follows §15 (fixed literals only, no interpolation).
- [ ] Focused tests for this command pass.
- [ ] The relevant complete-domain test profile passes.
- [ ] The canonical regression suite shows only the currently-approved
      baseline failures — no new failures, no collection errors, no
      internal errors.
- [ ] Production integrity (row counts, identity state) is confirmed
      unchanged, read-only, both before and after implementation.
- [ ] Commit, push, and deploy occur **only** under a separate, explicit
      approval phase — never bundled into the implementation phase itself.

---

*This document describes the architecture as verified by source inspection
at the commit named at the top. It does not claim source-level locking or
transactional atomicity anywhere in this codebase, and it does not
describe any capability that is not demonstrated by the eight commands in
§17. It contains no production identity values, no secrets, and no
references to any specific chat session.*
