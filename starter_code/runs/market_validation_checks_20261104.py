"""Offline R039 checks for one-factor controls and empirical return units."""
import contextlib
import io
from pathlib import Path
import tempfile
import unittest
import zipfile
import numpy as np
from runs import market_validation_20261104 as d


class Checks(unittest.TestCase):
    def test_only_economic_config_difference_is_mm_skew(self):
        a=d.recipe(16253,"original").to_dict();b=d.recipe(16253,"no_skew").to_dict()
        self.assertEqual(sum(g["count"] for g in a["agents"]),14)
        self.assertEqual(a["llm_limits"]["max_requests"],0)
        self.assertEqual(a["agents"][0]["params"]["inventory_skew"],.02)
        self.assertEqual(b["agents"][0]["params"]["inventory_skew"],0)
        a.pop("name");b.pop("name");a["agents"][0]["params"].pop("inventory_skew");b["agents"][0]["params"].pop("inventory_skew")
        self.assertEqual(a,b)
    def test_price_return_and_total_return_are_distinct(self):
        p,t=d.returns([dict(price="100",dividend="1"),dict(price="101",dividend="1")],100)
        np.testing.assert_allclose(p,[0,np.log(1.01)])
        np.testing.assert_allclose(t,[np.log(1.01),np.log(1.02)])
    def test_acf_includes_zeros_and_handles_constant_sequences(self):
        self.assertAlmostEqual(d.acf([1,-1,1,-1])[0],-.75)
        self.assertEqual(d.acf([0]*10),[None]*10)
        self.assertIsNone(d.acf([1,-1,1,-1])[3])
    def zipdata(self,bad=False):
        text="Example fixture\n,Mkt-RF,SMB,HML,RF\n20251229,1,0,0,0.1\n20251230,-0.1,0,0,0.1\n20251231,"+("-99.99" if bad else "2")+",0,0,0.1\n20260102,80,0,0,0.1\n\nAnnual\n2025,9,0,0,1\n"
        output=io.BytesIO()
        with zipfile.ZipFile(output,"w") as z:z.writestr("fixture.csv",text)
        return output.getvalue()
    def test_empirical_cutoff_percent_and_excess_return_units(self):
        r=d.empirical(self.zipdata(),count=3)
        self.assertEqual((r["first_date"],r["last_date"],r["count"],r["zero_return_count"]),("20251229","20251231",3,1))
        np.testing.assert_allclose([x["log_total_return"] for x in r["records"]],[np.log(1.011),0,np.log(1.021)])
        with self.assertRaises(AssertionError):d.empirical(self.zipdata(True),count=3)
    def test_source_and_config_seals(self):
        scratch=d.BASE/".tmp";scratch.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=scratch) as temp:
            with contextlib.redirect_stdout(io.StringIO()):root=d.prepare(Path(temp))
            p=d.validate(root);self.assertEqual(len(p["arms"]),8)
            path=root/p["arms"][0]["config"];path.write_text(path.read_text()+"\n# drift\n")
            with self.assertRaises(AssertionError):d.validate(root)


if __name__=="__main__":unittest.main()
