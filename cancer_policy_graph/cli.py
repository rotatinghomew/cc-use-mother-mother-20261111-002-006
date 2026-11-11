from __future__ import annotations
import argparse
import json
from cancer_policy_graph.service import run_fixture

def main() -> int:
    parser=argparse.ArgumentParser(description='癌症防治指南变化证据图')
    parser.add_argument("fixture")
    parser.add_argument("--db",default="/tmp/cancer_policy_graph.sqlite3")
    args=parser.parse_args()
    result=run_fixture(args.fixture,args.db)
    print(json.dumps(result,ensure_ascii=False,sort_keys=True))
    return 0

if __name__ == "__main__": raise SystemExit(main())
