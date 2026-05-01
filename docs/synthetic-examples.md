# Synthetic Examples

These examples are intentionally small and synthetic. They are for exposition
only: they explain the kinds of signals dryscope uses, but they are not
benchmark cases and were not copied from real repositories.

## Why Not Cosine Similarity Alone?

Cosine similarity over embeddings is useful because it can catch code that has
similar intent even when names differ. On its own, though, it can also overstate
matches that are only broadly related.

These two helpers may embed close together because both validate and normalize
input:

```python
def validate_email(email):
    if "@" not in email:
        raise ValueError("invalid email")
    return email.lower()
```

```python
def validate_phone(phone):
    digits = "".join(ch for ch in phone if ch.isdigit())
    if len(digits) != 10:
        raise ValueError("invalid phone")
    return digits
```

They are conceptually similar, but they are not duplicated implementation logic.
Token overlap helps push this kind of pair down because the concrete operations
and domain rules differ.

This pair is more plausibly a duplicate candidate:

```python
def fetch_user(client, user_id):
    response = client.get(f"/users/{user_id}")
    response.raise_for_status()
    return response.json()
```

```python
def fetch_order(client, order_id):
    response = client.get(f"/orders/{order_id}")
    response.raise_for_status()
    return response.json()
```

After normalization, the call shape, error handling, and return pattern remain
very close. Cosine similarity and token overlap both point in the same
direction, so the pair is a stronger Code Match candidate.

## Size-Ratio Filtering

Size-ratio filtering avoids accepting pairs where one unit is much larger than
the other. A tiny helper can be semantically related to a large function without
being a useful duplicate of that function.

```python
def is_admin(user):
    return user.role == "admin"
```

```python
def authorize_dashboard_request(user, account, feature_flags, audit_log):
    if user.role == "admin":
        audit_log.record("admin-dashboard-access", user.id)
        return True
    if account.plan != "enterprise":
        return False
    if not feature_flags.enabled("dashboard_delegation"):
        return False
    return user.id in account.dashboard_delegates
```

These both involve admin authorization, so their embeddings may be related. But
the small helper and the larger policy function are not comparable duplicate
units.

## Docs Map Example

Docs Map works at the document and corpus level. It looks for overlapping
purpose, aboutness, and reader intent even when documents do not repeat the same
paragraphs.

| Document | Synthetic role |
| --- | --- |
| `docs/search-requirements.md` | product requirements for search filters and ranking |
| `docs/search-design.md` | indexing pipeline and query API design |
| `research/vector-search.md` | embedding experiments and retrieval quality notes |
| `plans/search-rollout.md` | implementation status, rollout risks, and checklist |

Docs Map might group these around a `search experience` topic, assign facets
such as `requirements`, `design`, `research`, and `plan`, then recommend that
the repo establish clearer canonical sources or cross-links.

## Section Match Examples

Section Match works at a smaller level. Two documents can have distinct
document-level purposes while still repeating the same supporting section.

### Useful Consolidation Candidate

| Document | Document purpose | Repeated section |
| --- | --- | --- |
| `docs/search-requirements.md` | define user-visible behavior | `Configuration`: environment variables and defaults |
| `docs/search-design.md` | explain architecture and data flow | `Configuration`: same variables, rc file, and feature flags |

Section Match would point to those specific sections. The right fix might be a
shared configuration reference page, a cross-link, or one canonical section that
the other document references.

### Useful Cross-Document Consistency Candidate

Some repeated sections are not pure copy-paste mistakes. They may be repeated
because related docs need to stay aligned.

| Document | Section | Synthetic repeated content |
| --- | --- | --- |
| `docs/deploy/linux.md` | `Environment variables` | `APP_ENV`, `APP_CONFIG`, and `APP_LOG_LEVEL` setup |
| `docs/deploy/windows.md` | `Environment variables` | the same variables plus Windows-specific shell syntax |

Section Match can surface this as a maintenance risk. The likely fix is not
necessarily to delete one section. A better fix might be one shared
`docs/deploy/configuration.md` page plus short platform-specific examples in
each deployment guide.

### Intentional Repetition

Other repeated sections are useful to detect but may not be worth consolidating.

| Document | Section | Why it repeats |
| --- | --- | --- |
| `docs/integrations/react.md` | `Install the adapter` | parallel framework guide |
| `docs/integrations/preact.md` | `Install the adapter` | parallel framework guide |
| `docs/integrations/vue.md` | `Install the adapter` | parallel framework guide |

These sections may have the same structure because readers land on one
integration guide at a time. Section Match may still report them, but a reviewer
could label the repetition intentional and keep the docs separate.

### Related Documents Without Section Duplication

Docs Map and Section Match answer different questions. Two documents can overlap
in topic without having repeated sections.

| Document | Purpose |
| --- | --- |
| `docs/billing-requirements.md` | define invoices, refunds, and user-visible billing behavior |
| `docs/billing-design.md` | explain payment provider boundaries, database tables, and event flow |

Docs Map might group both documents under `billing`, because their intent
overlaps. Section Match might find nothing if the requirements doc and design
doc do not repeat the same section-level text. That is a useful outcome: the
documents are related at the corpus level, but they do not necessarily need
section-level consolidation.
