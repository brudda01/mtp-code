"""Run labeled mock integration checks only. No live collection capability."""
import argparse
from sandbox import Config,run_mock

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--wealth',choices=['equal','heterogeneous','cash_only'],default='heterogeneous')
    p.add_argument('--seed',type=int,default=42); p.add_argument('--rounds',type=int,default=10)
    p.add_argument('--assignment',type=int,default=0)
    p.add_argument('--short',action='store_true'); p.add_argument('--forum',action='store_true')
    a=p.parse_args()
    print(run_mock(Config(seed=a.seed,rounds=a.rounds,wealth=a.wealth,assignment=a.assignment,allow_short=a.short,forum=a.forum)))
if __name__=='__main__': main()
