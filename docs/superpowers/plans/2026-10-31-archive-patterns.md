# Archive pattern implementation plan

Goal: Cover every distinct readable setup in the 23 supplied images through causal chart detections or an explicit reference-only entry where the image cannot define a reproducible rule.

Architecture: Extend the existing pure Bar recognizers and shared related-pattern layer. Keep historical probability engine separate from newly added, uncalibrated names. Only verified closed bars and replay prefixes enter detection. Current labels, pointer stems, chart selection and option automation remain authoritative.

Tasks:
- [x] Extract safely, identify 3 byte-identical duplicates, visually read 20 unique images.
- [x] Add simple candle families with mirrored/negative fixtures.
- [x] Add multi-candle gap/continuation/exhaustion families with fixtures.
- [x] Add structural retests and institutional catalog with honest rule status.
- [x] Add missing chart geometry, SAR flips, confirmed demand/supply context.
- [x] Integrate all recognition modes; show coverage/corrections in plain English.
- [x] Run focused regressions, typecheck, complete frontend suite, build and publish; verify Chrome.

Operational definitions are our implementation choices, not validated trading edges or exact proprietary rules. Conflicting signs are corrected against primary definitions. No orders, signal probabilities, promotional actions or clock-only BUY/SELL claims inferred from images. No new dependencies.
