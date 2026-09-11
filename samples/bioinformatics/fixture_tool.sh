#!/usr/bin/env sh
set -eu

mode=${1:?missing mode}
output=${2:?missing output path}
shift 2

case "$mode" in
	validate)
		[ "$#" -eq 2 ] || exit 65
		printf '{"validated":true,"schema":1,"read1":"%s","read2":"%s"}\n' "$1" "$2" >"$output"
		printf 'fixture validation complete\n'
		;;
	align)
		[ "$#" -eq 3 ] || exit 65
		printf 'fixture-bam-v1\nread1=%s\nread2=%s\nreference=%s\n' "$1" "$2" "$3" >"$output"
		printf 'fixture alignment complete\n'
		;;
	variant-call)
		[ "$#" -eq 2 ] || exit 65
		printf '##fileformat=VCFv4.3\n##reference=%s\n#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\nchr1\t101\t.\tA\tG\t42\t.\tSOURCE=%s\n' "$2" "$1" >"$output"
		printf 'fixture variant calling complete\n'
		;;
	variant-filter)
		[ "$#" -eq 1 ] || exit 65
		[ -f "$1" ] || exit 66
		printf '##fileformat=VCFv4.3\n##source=fixture-filter-v1\n#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\nchr1\t101\t.\tA\tG\t42\tPASS\tINPUT=%s\n' "$1" >"$output"
		printf 'fixture variant filtering complete\n'
		;;
	fail)
		printf 'fixture alignment failed\n' >&2
		exit 23
		;;
	no-output)
		printf 'fixture completed without output\n'
		;;
	*)
		printf 'unknown fixture mode: %s\n' "$mode" >&2
		exit 64
		;;
esac
