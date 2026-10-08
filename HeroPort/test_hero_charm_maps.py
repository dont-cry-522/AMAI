"""Preserve all existing map abilities while adding a normal-object Charm edit."""
import struct
import unittest

from build_test_maps import i32, mods, object_file
from add_to_maps import object_tables
from hero_charm_maps import allow_hero_charm


class CharmTables(unittest.TestCase):
    def test_keeps_existing_abilities_and_adds_one_base_edit(self):
        original = object_file([('ANcl','AHcr',mods({'anam':'保留'},1))],extended=True)
        result = object_tables(allow_hero_charm(original),extended=True)
        self.assertEqual([raw for raw,_ in result[0]],[b'ANch'])
        self.assertEqual(result[1],object_tables(original,extended=True)[1])
        self.assertIn(b'hero,nonhero', result[0][0][1])
        with self.assertRaises(AssertionError):
            allow_hero_charm(allow_hero_charm(original))


if __name__=='__main__':
    unittest.main()
