测试：python3 -m unittest discover -s tests/policy_graph -p 'test_*.py'
构建：python3 -m compileall -q cancer_policy_graph
验收：python3 -m cancer_policy_graph.cli fixtures/demo.json --db /tmp/cancer_policy_graph-acceptance.sqlite3
