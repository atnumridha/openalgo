# Neo migration manifest

Version 1 records source SHA-256, source SQLite user version, source fill count and executed quantity, dry-run status, inserted/reused/enriched counts and destination count. Private runtime reconciliation adds accounting completeness and source date coverage. Source backups preserve the journal, archived fills, datasets and published reports. No execution intent or open ownership is imported into the engine.

Repeated imports compare immutable execution fields before accepting an identity. Conflicts roll back the whole import. Broker fill date/time takes precedence over order exchange time. Actual fees are populated only from explicit execution reports.

The ₹10 Trade Free brokerage estimate is conservative when promotional start/end dates have not been verified. A free-brokerage scenario requires an explicit verified dated window. Estimates are not paid fees.
