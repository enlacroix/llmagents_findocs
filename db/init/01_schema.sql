CREATE TABLE counterparties (
    id             serial PRIMARY KEY,
    name           text NOT NULL,
    inn            varchar(12) UNIQUE,
    kpp            varchar(9),
    ogrn           varchar(15),
    address        text,
    phone          text,
    email          text,
    bank_account   varchar(20),
    bik            varchar(9),
    is_own_company boolean NOT NULL DEFAULT false
);

CREATE TABLE branches (
    code    varchar(10) PRIMARY KEY,
    name    text NOT NULL,
    address text NOT NULL
);

CREATE TABLE authorities (
    id           serial PRIMARY KEY,
    person_name  text NOT NULL,
    position     text NOT NULL,
    scope        text NOT NULL,
    amount_limit numeric(14, 2),
    basis        text NOT NULL
);

CREATE TABLE documents (
    id            serial PRIMARY KEY,
    source_file   text NOT NULL,
    page          integer NOT NULL,
    document_type text NOT NULL,
    status        text NOT NULL CHECK (status IN ('approved', 'needs_review')),
    reason        text,
    review_fields jsonb NOT NULL DEFAULT '[]',
    issues        jsonb NOT NULL DEFAULT '[]',
    data          jsonb,
    processed_at  timestamptz NOT NULL DEFAULT now(),
    UNIQUE (source_file, page)
);

CREATE VIEW review_queue AS
SELECT id, source_file, page, document_type, reason, review_fields, processed_at
FROM documents
WHERE status = 'needs_review'
ORDER BY processed_at;
