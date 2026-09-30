"""Regression check: appending a hero must not discard map-specific object edits."""
import unittest

from add_to_maps import merge_objects, object_tables
from build_test_maps import i32, inject_script, mods, object_file


class ExistingMapTests(unittest.TestCase):
    def test_preserve_original_and_custom_objects(self):
        record = b'nfps'+b'\0'*4+i32(1)+b'umpi'+i32(0)+i32(125)+b'nfps'
        original = i32(1)+i32(1)+record+i32(0)
        added = object_file([('Nplh', 'Npal', mods({'unam':'Hero'}))])
        merged = merge_objects(original, added)
        old, new = object_tables(merged)
        self.assertEqual(old, [(b'nfps', record)])
        self.assertEqual(new, object_tables(added)[1])
        with self.assertRaises(AssertionError):
            merge_objects(merged, added)
        with self.assertRaises(AssertionError):
            object_tables(merged+b'extra')

    def test_extended_ability_table(self):
        old = object_file([('AHtb', 'A001', mods({'anam':'Keep','amcs':20}, 1))], extended=True)
        added = object_file([('ANcl', 'ANcp', mods({'anam':'New','amcs':100}, 1))], extended=True)
        self.assertEqual(object_tables(merge_objects(old, added, True), True)[1],
                         object_tables(old, True)[1]+object_tables(added, True)[1])

    def test_injection_runs_after_original_initialization(self):
        original = 'globals\nendglobals\nfunction main takes nothing returns nothing\ncall OriginalSetup()\nendfunction\n'
        script = inject_script(original)
        self.assertIn('call OriginalSetup()\n    call TimerStart(CreateTimer(), 0.0, false, function FP_Init)', script)
        with self.assertRaises(AssertionError):
            inject_script(script)


if __name__ == '__main__':
    unittest.main()
