import copy
import csv
import io
import unittest
from types import SimpleNamespace as Obj

from nexus.selection import selection_rows, filter_rows, selection_page, selection_csv


def member(uid, name=None, bot=False):
    return Obj(id=uid, name=name or f'user{uid}', display_name=name or f'Member {uid}', bot=bot)


class SelectionTests(unittest.TestCase):
    def test_current_roster_includes_unregistered_and_bots_excludes_departed(self):
        states = {'1': {'accepted': True, 'path': 'jedi', 'rank': 3},
                  '2': {'accepted': True, 'path': 'sith', 'rank': 2, 'minimum_age_confirmed': 18},
                  '3': {'accepted': True, 'path': None},
                  '4': {'accepted': False, 'path': None},
                  '99': {'accepted': True, 'path': 'sith'}}
        before = copy.deepcopy(states)
        rows = selection_rows([member(x, bot=x == 6) for x in range(1, 7)], states)
        by_id = {row['id']: row for row in rows}
        self.assertEqual(set(by_id), set('123456'))
        self.assertEqual([by_id[str(x)]['status'] for x in range(1, 7)],
                         ['jedi', 'sith', 'unselected', 'not_joined', 'not_joined', 'bot'])
        self.assertEqual(by_id['1']['rank'], 'Jedi Knight')
        self.assertIn('not recorded', by_id['1']['rules'])
        self.assertEqual(by_id['2']['rules'], '18+ confirmed')
        self.assertEqual(states, before)
        self.assertEqual(len(filter_rows(rows, 'complete')), 2)
        self.assertEqual(len(filter_rows(rows, 'incomplete')), 3)
        self.assertEqual(len(filter_rows(rows, 'bot')), 1)
        self.assertEqual(len(filter_rows(rows, 'sith')), 1)

    def test_all_rows_exported_beyond_first_page_and_1000_members(self):
        rows = selection_rows([member(x) for x in range(1, 1006)], {})
        content = selection_page(rows, rows, 'all', 126, 1800000000)
        self.assertIn('Page **126/126**', content)
        exported = list(csv.reader(io.StringIO(selection_csv(rows, 1800000000).decode('utf-8-sig'))))
        self.assertEqual(len(exported), 1006)
        self.assertEqual(len({row[0] for row in exported[1:]}), 1005)
        with self.assertRaises(ValueError):
            selection_page(rows, rows, 'all', 127, 1800000000)

    def test_empty_filters_and_untrusted_names_are_safe(self):
        self.assertIn('No members match', selection_page([], [], 'all', 1, 1800000000))
        names = ['=HYPERLINK("example")', '+1', '-1', '@everyone', '\t=1', '  =1', 'a,"b"\nnext', '*' * 32]
        rows = selection_rows([member(x + 1, name) for x, name in enumerate(names)], {})
        content = selection_page(rows, rows, 'all', 1, 1800000000)
        self.assertNotIn('@everyone', content)
        self.assertLessEqual(len(content), 2000)
        exported = list(csv.reader(io.StringIO(selection_csv(rows, 1800000000).decode('utf-8-sig'))))
        by_name = {row[1].lstrip("'"): row for row in exported[1:]}
        for name in names[:6]:
            self.assertTrue(by_name[name][1].startswith("'"))
        self.assertEqual(by_name[names[6]][1], names[6])
        self.assertEqual(len(exported), len(names) + 1)
