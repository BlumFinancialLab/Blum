# Contributing Learning Evidence

BLUM Finance does not collect prompts, outputs, account data, or usage telemetry.
Community learning is explicit and evidence-bound.

## Contribution lifecycle

1. Run BLUM Finance locally and retain the point-in-time request and response.
2. After the stated horizon, attach an observed outcome and verified provenance.
3. Create a redacted contribution bundle:

   ```bash
   blum-contribute example.json --output contribution.json --consent
   ```

4. Inspect the bundle locally. To submit it for review, explicitly run:

   ```bash
   blum-contribute example.json --output contribution.json --consent --push
   ```

The upload opens a pull request against `Italianhype/Blum-Finance-Memory`.
It never writes directly to accepted memory or released model weights.

## Required evidence

A contribution must contain:

- a timestamped request with point-in-time evidence;
- the model response generated at that timestamp;
- a mature outcome observed after the decision;
- verified source provenance and an explicit quality score;
- explicit consent under the contribution license.

Pending, inconclusive, chronologically invalid, tampered, or unverified examples
remain quarantined. Secrets, account identifiers, email addresses and Hugging
Face tokens are removed from generated bundles.

## Local memory

Eligible bundles can improve a local installation without changing weights:

```bash
blum-memory-add contribution.json
```

The inference pipeline retrieves only outcomes observable before the new
request's `as_of` timestamp. Retrieved records are labeled as historical
analogies and cannot replace current evidence.

## Model updates

Accepted records may enter a future immutable dataset snapshot. A training run
always creates a challenger. Promotion requires temporal holdout evaluation,
no-fabrication and schema checks, adequate sample quality, and an explicit
versioned release. Anonymous inputs never self-modify a published model.
