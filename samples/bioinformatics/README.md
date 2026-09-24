# Typed bioinformatics examples

These examples use the generic external-tool layer in
[`samples/scientific/`](../scientific/README.md) to represent bioinformatics
workflow states in ordinary Ouro types.

Fixture executables keep CI self-contained. A real adapter can replace the
executable and argument list while retaining the same typed stage boundary.

## RNA-seq slice

`hela_rnaseq.ouro` models:

```text
unchecked paired-end human FASTQ
  -> validation process
  -> validated FASTQ
  -> alignment against GRCh38
  -> unsorted, unindexed GRCh38 BAM
```

The sample preserves the declared input identities and process record in the
derived artifact provenance.

## Variant-calling slice

`variant_calling.ouro` models:

```text
coordinate-sorted, indexed GRCh38 BAM
  + GRCh38 reference
  -> variant-calling process
  -> raw GRCh38 VCF
  -> filtering process
  -> filtered GRCh38 VCF
```

## Checked states

The shared model distinguishes, among other indices:

- human and mouse organisms;
- GRCh37, GRCh38, and GRCm39 genome builds;
- single-end and paired-end reads;
- unchecked and validated FASTQ;
- unsorted/sorted and unindexed/indexed BAM;
- samples-by-genes and cells-by-genes expression matrices;
- raw and normalized expression;
- raw and filtered VCF.

Negative fixtures demonstrate that the typechecker rejects combinations such as
unchecked reads at alignment, mismatched genome builds, unindexed BAM input,
double normalization, filtered VCF passed to the filtering stage, and evidence
from the wrong process stage.

## What the examples establish

The [process boundary](../scientific/README.md#process-boundary) controls
construction of successful stage evidence; the indices above check domain
compatibility.

The examples do not parse FASTQ, BAM, VCF, GTF, reference, or matrix contents.
They do not verify biological assumptions, sample identity, or scientific
correctness. Process and reproducibility limits are defined in the
[reusable layer](../scientific/README.md#identity-and-reproducibility).

## Run the suite

Use the samples suite from [CI](../../docs/ci.md). It checks the reusable layer,
both vertical slices, executable fixtures, golden output, and negative
type-error cases. Individual modules use the
[module checker](../../docs/tooling.md#check-and-evaluate).
