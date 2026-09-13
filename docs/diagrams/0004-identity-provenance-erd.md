# ADR-0004 identity and provenance logical ERD

This is a logical model, not an approved migration. Names may be refined in
the schema PR, but the grains, ownership, and dependency directions are
fixed by accepted ADR-0004. `MENU_ROOT` shows only the future vertical's
dependency seam; it is not a generic offering model or a complete menu ERD.

```mermaid
erDiagram
    BRONZE_SOURCE {
        bigint id PK
        string namespace UK
        string kind
    }

    BRONZE_CAPTURE {
        bigint id PK
        bigint source_id FK
        bigint source_endpoint_id FK
        datetime fetched_at
        string content_hash
        string bundle_path
        string outcome
    }

    BRONZE_SOURCE_ENDPOINT {
        bigint id PK
        bigint source_id FK
        string canonical_uri UK
        string endpoint_kind
    }

    BRONZE_SOURCE_RECORD {
        bigint id PK
        bigint source_id FK
        string external_key
        datetime first_seen_at
    }

    BRONZE_SOURCE_RECORD_VERSION {
        bigint id PK
        bigint source_record_id FK
        bigint capture_id FK
        datetime observed_at
        string content_hash
        json source_payload
    }

    BRONZE_EVIDENCE {
        bigint id PK
        bigint source_record_version_id FK
        bigint capture_id FK
        string locator
        string excerpt_hash
    }

    IDENTITY_SUBJECT {
        bigint id PK
        string kind
        string readiness
        datetime created_at
    }

    IDENTITY_PLACE {
        bigint subject_id PK,FK
        string subject_kind FK
        string address
        decimal latitude
        decimal longitude
    }

    IDENTITY_ORGANIZATION {
        bigint subject_id PK,FK
        string subject_kind FK
        string canonical_name
        string name_fingerprint
        string organization_kind
    }

    IDENTITY_ESTABLISHMENT {
        bigint subject_id PK,FK
        string subject_kind FK
        bigint organization_subject_id FK
        bigint place_subject_id FK
        datetime valid_from
        datetime valid_to
        string operating_status
    }

    IDENTITY_SUBJECT_NAME {
        bigint id PK
        bigint subject_id FK
        string name
        string name_fingerprint
        string name_kind
        bigint evidence_id FK
    }

    IDENTITY_RESOLUTION_EVENT {
        bigint id PK
        bigint source_record_id FK
        string operation
        bigint from_subject_id FK
        bigint to_subject_id FK
        bigint adjudication_id FK
        decimal confidence
        string method
        string method_version
        string actor_class
        datetime decided_at
        datetime effective_at
    }

    IDENTITY_CURRENT_RESOLUTION {
        bigint source_record_id PK,FK
        bigint subject_id FK
        bigint last_event_id UK,FK
        string state
    }

    IDENTITY_ADJUDICATION {
        bigint id PK
        string actor
        string rationale
        datetime decided_at
    }

    IDENTITY_RESOLUTION_EVIDENCE {
        bigint resolution_event_id PK,FK
        bigint evidence_id PK,FK
    }

    IDENTITY_SUBJECT_CHANGE {
        bigint id PK
        string operation
        bigint adjudication_id FK
        decimal confidence
        string method
        string method_version
        string actor_class
        datetime decided_at
        datetime effective_at
    }

    IDENTITY_SUBJECT_CHANGE_MEMBER {
        bigint subject_change_id PK,FK
        bigint subject_id PK,FK
        string role PK
    }

    IDENTITY_SUBJECT_CHANGE_EVIDENCE {
        bigint subject_change_id PK,FK
        bigint evidence_id PK,FK
    }

    MENU_ROOT {
        bigint id PK
        bigint scope_subject_id FK
        string scope_subject_kind FK
        bigint source_record_version_id FK
    }

    GOLD_MENU_READ_MODEL {
        bigint id PK
        bigint menu_root_id
        bigint scope_subject_id
        datetime as_of
    }

    BRONZE_SOURCE ||--o{ BRONZE_CAPTURE : produces
    BRONZE_SOURCE ||--o{ BRONZE_SOURCE_ENDPOINT : exposes
    BRONZE_SOURCE_ENDPOINT o|--o{ BRONZE_CAPTURE : fetched_at
    BRONZE_SOURCE ||--o{ BRONZE_SOURCE_RECORD : namespaces
    BRONZE_SOURCE_RECORD ||--|{ BRONZE_SOURCE_RECORD_VERSION : versions
    BRONZE_CAPTURE o|--o{ BRONZE_SOURCE_RECORD_VERSION : contains
    BRONZE_SOURCE_RECORD_VERSION ||--o{ BRONZE_EVIDENCE : locates
    BRONZE_CAPTURE o|--o{ BRONZE_EVIDENCE : locates

    IDENTITY_SUBJECT ||--o| IDENTITY_PLACE : typed_as
    IDENTITY_SUBJECT ||--o| IDENTITY_ORGANIZATION : typed_as
    IDENTITY_SUBJECT ||--o| IDENTITY_ESTABLISHMENT : typed_as
    IDENTITY_PLACE ||--o{ IDENTITY_ESTABLISHMENT : hosts
    IDENTITY_ORGANIZATION ||--o{ IDENTITY_ESTABLISHMENT : operates
    IDENTITY_SUBJECT ||--o{ IDENTITY_SUBJECT_NAME : named_by
    BRONZE_EVIDENCE ||--o{ IDENTITY_SUBJECT_NAME : supports

    BRONZE_SOURCE_RECORD ||--o{ IDENTITY_RESOLUTION_EVENT : interpreted_by
    IDENTITY_SUBJECT o|--o{ IDENTITY_RESOLUTION_EVENT : previous_target
    IDENTITY_SUBJECT o|--o{ IDENTITY_RESOLUTION_EVENT : new_target
    BRONZE_SOURCE_RECORD ||--o| IDENTITY_CURRENT_RESOLUTION : enters_workflow
    IDENTITY_SUBJECT o|--o{ IDENTITY_CURRENT_RESOLUTION : current_target
    IDENTITY_RESOLUTION_EVENT ||--o| IDENTITY_CURRENT_RESOLUTION : last_event
    IDENTITY_RESOLUTION_EVENT ||--o{ IDENTITY_RESOLUTION_EVIDENCE : cites
    BRONZE_EVIDENCE ||--o{ IDENTITY_RESOLUTION_EVIDENCE : evidence
    IDENTITY_ADJUDICATION o|--o{ IDENTITY_RESOLUTION_EVENT : justifies

    IDENTITY_SUBJECT_CHANGE ||--|{ IDENTITY_SUBJECT_CHANGE_MEMBER : has
    IDENTITY_SUBJECT ||--o{ IDENTITY_SUBJECT_CHANGE_MEMBER : participates
    IDENTITY_SUBJECT_CHANGE ||--o{ IDENTITY_SUBJECT_CHANGE_EVIDENCE : cites
    BRONZE_EVIDENCE ||--o{ IDENTITY_SUBJECT_CHANGE_EVIDENCE : evidence
    IDENTITY_ADJUDICATION o|--o{ IDENTITY_SUBJECT_CHANGE : justifies

    IDENTITY_SUBJECT ||--o{ MENU_ROOT : scopes
    BRONZE_SOURCE_RECORD_VERSION ||--o{ MENU_ROOT : derived_from
    MENU_ROOT ||--o{ GOLD_MENU_READ_MODEL : projects
```

`BRONZE_EVIDENCE` has exactly one of `source_record_version_id` or
`capture_id`. Each decision has one or more Evidence links or one immutable
Adjudication. Database constraints must also ensure that each Subject has
exactly one typed row, Establishment references typed Organization and Place
Subjects, and a menu root permits only Organization or Establishment
Subjects. Composite `(subject_id, subject_kind)` FKs enforce the typed
references against Subject's unique `(id, kind)` pair; the duplicated kind
columns are intentional constraint anchors. Resolution state requires a
Subject only when `state = 'resolved'`; `unresolved` and `needs_review` keep
an explicit null-target row. An append-only `Open` event creates the initial
`unresolved` row, so `last_event_id` is always present and the projection is
rebuildable. Subjects begin `provisional`, and vertical roots may reference
only Subjects that pass the approved identity-readiness gate.
