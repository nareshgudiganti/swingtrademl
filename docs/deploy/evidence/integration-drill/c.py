import os

import swing_trade_ml
from swing_trade_ml.core import password_policy as p

print(swing_trade_ml.__file__)
f=os.path.join(os.path.dirname(p.__file__),"common_passwords.txt"); print(f, os.path.getsize(f))
print(len(p.load_common_passwords()))
for pw in ["passwordpassword","a long random pass phrase here","short"]:
    print(repr(pw), p.check_password(pw))
