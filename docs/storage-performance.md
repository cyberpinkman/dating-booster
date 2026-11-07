# Memory and storage performance

The storage contract keeps encryption, app isolation and event ordering intact.
Normal reads of an initialized SQLite store validate its schema and metadata with
SELECTs. They do not run DDL or upsert metadata. Initialization and schema repair
take the shared data-directory write lock and recheck after acquiring it.

Memory events have a separate immutable batch append API. The first payload for
an event ID wins; a failed batch leaves its earlier events uncommitted. Ordinary
audit-event upserts retain their existing semantics. SQLite uses one transaction;
legacy JSONL builds the complete addition before one atomic file replacement.

An ingest reads the old memory history once, appends its batch, and reuses those
events for the projection and event count. Append/rebuild and observation rebuild
hold the same write lock across reads and writes. Feedback holds that lock across
its raw feedback stream, memory stream and projection, so concurrent retries
retain the same first event in both streams.

Replay preserves the log's causal order. If older timestamp sorting damaged a
history with repeated facts and its dependencies cannot be recovered uniquely,
`memory_fact_reference_order_ambiguous` blocks the rebuild and preserves the
original evidence and projection; rebuild cannot automatically repair every
historical ambiguity.

Store/provider reuse is limited to a synchronous ingest, feedback or rebuild
operation. Nested repository calls share it; the outer operation discards it.
There is no process-lifetime key cache. A later operation rediscovers the store
and key after maintenance such as rekey or delete. Rekey holds the same root
write lock through key rotation, payload rewrites and WAL checkpoint, so it
cannot rotate a key while an ingest is still using it. The operation cache also
keys stores by database file identity.

## Synthetic measurements

These are local, single-run measurements on 2026-11-07, using temporary encrypted
SQLite stores with the local key provider. No real user data, GUI, model request
or Keychain access was involved. The baseline is `8a381e6`; the comparison uses
the storage performance changes. Wall time is illustrative; operation counts are
the stable regression contract.

Each case seeds the existing synthetic chat fixture with unique observation IDs,
nine events per observation, then ingests one more observation with nine events.
Both runs instrument audit decoding, provider creation and schema checks.

| Existing events | Decryptions before | Decryptions after | Before | After |
| ---: | ---: | ---: | ---: | ---: |
| 9 | 153 | 9 | 28.62 ms | 12.43 ms |
| 450 | 5,004 | 450 | 148.92 ms | 28.42 ms |
| 1,800 | 19,854 | 1,800 | 571.20 ms | 88.95 ms |

For each initialized-store ingest, provider instances fell from 32 to 1, schema
checks from 32 to 14, and metadata upserts from 192 to 0. With the Darwin provider
path mocked, availability probes and key lookups each fell from 32 to 1. These
are call counts, not measured real Keychain latency.

With another SQLite connection holding `BEGIN IMMEDIATE`, the old `get_document`
was still blocked after 250 ms and returned only after the writer released its
transaction. The updated read completed in 0.20 ms while the writer remained
open. The regression also exercises list and exists operations under that lock.

## Verification

```bash
DATING_BOOST_KEY_PROVIDER=local .venv/bin/python -m pytest -q \
  tests/test_memory_storage_performance.py tests/test_memory_replay_order.py \
  tests/test_storage.py tests/test_match_storage_concurrency.py \
  tests/test_production_data.py tests/test_production_reliability.py
```

The new contract tests initially failed for writes on read, missing atomic batch
support, non-serialized rebuild/feedback updates and repeated history decoding.
After the change, this suite passed 62 tests and 15 subtests. Coverage includes
SQLite and legacy rollback, same-ID retries, concurrent processes, empty-store
initialization, same-operation provider reuse, and fresh providers across rekey
and delete. The added feedback race test checks both event streams and a single
projection count. A mocked Keychain race initially allowed rekey to complete
inside a repository operation using the previous key; its regression now proves
that rotation waits and both existing and newly written rows remain decryptable.

Batch atomicity does not make the whole multi-document ingest a single database
transaction. A crash between its durable steps still requires the existing
recovery/rebuild workflow.
