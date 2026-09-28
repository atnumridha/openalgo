# Profit-trailing review

Independent reviewer: no critical issues; one important integration issue; no deferred minors.

Finding: after a profitable ratchet, restart compared Kotak's original broker stop with the higher application stop and incorrectly reported uncovered exposure.

Resolution: verify the durable broker trigger against broker evidence and original-stop coverage, without loosening the application stop. The existing-stop replay path uses the same distinction. `test_recovery_verifies_broker_fallback_without_dropping_earned_app_stop` failed before the fix and passed afterward; the final 4,151-test backend suite passed. A weaker recorded trigger and a broker evidence mismatch remain rejected.

Scope rulings: candle testing cannot establish tick-accurate profit capture; negative replay remains unprofitable; old frozen models require new qualification; the pre-existing five-second checkpoint interval remains. The product and release report explicitly state that profit trailing requires OpenAlgo and its price feed, while the broker-held fallback stays fixed. No automatic live activation was added.
