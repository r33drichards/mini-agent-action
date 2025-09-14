test cmd 

```
python main.py  --exec "python test.py" --task "fix this test, you can see it fail with python test.py. you will be validated against that cmd" --debug   

```

output



```
👋 This is mini-swe-agent version 1.11.1.
Your config is stored in '/Users/robertwendt/Library/Application 
Support/mini-swe-agent/.env'
validation result:  F
======================================================================
FAIL: test_failing (__main__.Test.test_failing)
----------------------------------------------------------------------
Traceback (most recent call last):
  File "/Users/robertwendt/mini-agent-action/test.py", line 10, in test_failing
    self.assertEqual(add(1, 2), 3)
AssertionError: 4 != 3

----------------------------------------------------------------------
Ran 1 test in 0.000s

FAILED (failures=1)

validation result:  .
----------------------------------------------------------------------
Ran 1 test in 0.000s

OK

(mini-agent-action) ➜  mini-agent-action git:(master) ✗ 
```

publish 


test pypi
```
uv publish --token $PYPI_TOKEN
```
