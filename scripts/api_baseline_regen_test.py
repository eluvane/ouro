#!/usr/bin/env python3
"""Public API header and baseline preservation contracts; no native claims."""
from __future__ import annotations

import unittest
from unittest.mock import patch

import api_baseline_regen as api


class SignatureContracts(unittest.TestCase):
    def signature(self, text):
        return api.collect_signature(text.splitlines(), 0, "std/api.ouro")[0]

    def test_existing_one_line_hash(self):
        signature = self.signature("def stable_api : Nat := Z; -- public")
        self.assertEqual(signature, "def stable_api : Nat")
        self.assertEqual(f"{api.hash_text(signature):x}", "4ca5958dd1a1ccef")

    def test_continuation_and_comments_equal_one_line_header(self):
        one = "def continued (x : Nat) : Nat := x;"
        many = "def continued (x : Nat) -- comment\n\t-- another comment\n : Nat\n := x;"
        self.assertEqual(self.signature(one), self.signature(many))

    def test_same_first_line_changed_result_changes_hash(self):
        first = "def continued (x : Nat)\n"
        before = self.signature(first + " : Nat := x;")
        after = self.signature(first + " : Bool := True;")
        self.assertNotEqual(api.hash_text(before), api.hash_text(after))

    def test_body_is_excluded(self):
        first = "def continued (x : Nat)\n : Nat := "
        self.assertEqual(self.signature(first + "x;"),
                         self.signature(first + "S x; -- changed body"))

    def test_nested_assignment_stays_in_header(self):
        source = "def defaulted {A : Type} (x : Nat := 30)\n : Nat := x;"
        self.assertEqual(self.signature(source),
                         "def defaulted {A : Type} (x : Nat := 30) : Nat")

    def test_quoted_markers_stay_in_header(self):
        for literal in ['"left := -- right"', 'r#"left := -- right"#']:
            with self.subTest(literal=literal):
                source = f"def key : Eq String {literal}\n {literal} := witness;"
                self.assertEqual(self.signature(source),
                                 f"def key : Eq String {literal} {literal}")

    def test_character_boundaries_and_primed_names(self):
        source = "def key' : Eq Char ')' ')'\n := witness;"
        self.assertEqual(self.signature(source), "def key' : Eq Char ')' ')'")

    def test_malformed_and_unterminated_headers_fail(self):
        for source in ["def incomplete : Nat", "def incomplete : Nat;",
                       "def incomplete (x : Nat := x;", "def incomplete ] := x;",
                       'def incomplete : Eq String "unfinished',
                       'def incomplete : Eq String r#"unfinished',
                       "def incomplete : Eq Char 'unfinished"]:
            with self.subTest(source=source), self.assertRaisesRegex(
                    ValueError, "std/api.ouro:1: (malformed|unterminated) API signature"):
                self.signature(source)

    def test_next_declaration_cannot_finish_header(self):
        for declaration in ["def next : Nat := Z;", "axiom Next : Type;",
                            "inductive Next : Type := | New : Next;",
                            "private def next : Nat := Z;"]:
            with self.subTest(declaration=declaration), self.assertRaisesRegex(
                    ValueError, "unterminated API signature"):
                self.signature("def incomplete : Nat\n" + declaration)

    def test_inventory_metadata_and_synthetic_rows_survive(self):
        source = api.ROOT / "std/api.ouro"
        signature = self.signature("def continued (x : Nat)\n : Nat := x;")
        generated = [("std/api.ouro", "continued", f"{api.hash_text(signature):x}", signature)]
        synthetic = "std/api.ouro\tfield\t123\taccessors\tplanned\t# generated accessor"
        existing = [("std/api.ouro", "continued",
                     "std/api.ouro\tcontinued\t1\tstable-namespace\tplanned"),
                    ("std/api.ouro", "field", synthetic)]
        with patch.object(api, "std_sources", return_value=[source]), \
                patch.object(api, "rows_for", return_value=generated), \
                patch.object(api, "existing_rows", return_value=existing):
            rendered, rows, sources = api.render_baseline()
        self.assertEqual((rows, sources), (2, 1))
        self.assertIn("\tstable-namespace\tplanned\t# def continued (x : Nat) : Nat\n", rendered)
        self.assertIn(synthetic + "\n", rendered)


if __name__ == "__main__":
    unittest.main()
