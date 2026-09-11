<p align="center">
  <img
    width="100%"
    src="https://capsule-render.vercel.app/api?type=waving&amp;height=220&amp;color=0:0B1220,50:1E1B4B,100:4F46E5&amp;text=BIO&amp;fontColor=E2E8F0&amp;fontSize=54&amp;fontAlignY=50"
    alt="BIO banner"
  />
</p>

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

For values built through the demonstrated adapters, the types check represented
workflow compatibility and stage identity. The process layer also requires a
successful exit and expected output file before constructing the supported
typed result.

The examples do not parse FASTQ, BAM, VCF, GTF, reference, or matrix contents.
They do not verify biological assumptions, sample identity, executable
versions, environments, bit reproducibility, or scientific correctness.

## Run the suite

```sh
sh scripts/ouro1.sh check samples/bioinformatics/bio.ouro
sh scripts/ouro1.sh check samples/bioinformatics/hela_rnaseq.ouro
sh scripts/ouro1.sh check samples/bioinformatics/variant_calling.ouro
sh scripts/samples_suite.sh
```

The suite checks the reusable layer, both vertical slices, their executable
fixtures, golden output, and the negative type-error cases.

<p align="center">
  <img
    width="100%"
    src="https://capsule-render.vercel.app/api?type=waving&amp;height=220&amp;color=0:0B1220,50:1E1B4B,100:4F46E5&amp;section=footer"
    alt=""
  />
</p>
