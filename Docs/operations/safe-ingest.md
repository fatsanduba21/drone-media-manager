# Safe ingest checkpoint

1. On Windows, run `dmm-worker scan PATH`, then `dmm-worker ingest --dry-run PATH`.
2. Run `dmm-worker submit PATH` to upload the immutable relative-path snapshot.
3. On the Mac, confirm with `dmm-server ingest confirm SNAPSHOT_ID --trip TRIP_ID`.
4. Monitor with `dmm-server ingest status INGEST_ID`; reconnects resume from checkpoints.
5. Source and destination SHA-256, size, and inventory metadata must agree before promotion.
   Divergent existing files are preserved as conflicts.
6. MP4/SRT pairs, missing SRT, and orphan SRT states remain explicit in the manifest.

Only removable sources can receive a card-format notice. `REQUIRE_SECOND_COPY`
requires a separate verified backup. `NAS_ONLY` may report: “Only one verified
copy exists; keep the source card until a second copy is verified.” Card release
is separate from retaining verified originals in the INBOX destination.
