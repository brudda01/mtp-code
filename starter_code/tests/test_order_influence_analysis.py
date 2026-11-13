"""Independent audit must reject corrupted outcome records."""
from copy import deepcopy
import unittest
from research.order_influence import BASE, read
from research.analyze_order_influence import independent_audit


class AnalysisAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.frames=read(BASE/'runs/order_influence_20261107/frames.json')
        cls.record=next(r for r in read(BASE/'runs/order_influence_20261107/results.json') if r['result']['volume']>0)

    def test_saved_record_passes(self):
        self.assertEqual(independent_audit(self.frames,[self.record])['status'],'passed')

    def test_wrong_price_rejected(self):
        r=deepcopy(self.record);r['result']['price']+=.1
        with self.assertRaises(AssertionError):independent_audit(self.frames,[r])

    def test_cash_creation_rejected(self):
        r=deepcopy(self.record);r['result']['posttrade_accounts']['llm_012']['cash']+=1
        with self.assertRaises(AssertionError):independent_audit(self.frames,[r])

    def test_share_creation_rejected(self):
        r=deepcopy(self.record);r['result']['posttrade_accounts']['llm_012']['shares']+=1
        with self.assertRaises(AssertionError):independent_audit(self.frames,[r])


if __name__=='__main__':unittest.main()
