import re,sys
t=open(r"D:/machine learning/um-wt/backend/tests/conftest.py").read()
m=re.search(r'"(postgresql\+psycopg://[^"]+)/swing_trade_ml_test"',t)
print(m.group(1)+"/"+sys.argv[1])
