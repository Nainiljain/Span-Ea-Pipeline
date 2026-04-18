"""
generate_token_b64.py
======================
Run this ONCE on your local machine AFTER you have a valid token.pickle.
It converts the token to a base64 string you can paste into Railway as
the TOKEN_PICKLE_B64 environment variable.

Usage:
    python generate_token_b64.py
"""
import pickle
import base64
import os

TOKEN_FILE = "token.pickle"

if not os.path.exists(TOKEN_FILE):
    print("❌ token.pickle not found!")
    print("   Run: python full_pipeline.py  (it will create token.pickle via browser login)")
    exit(1)

with open(TOKEN_FILE, "rb") as f:
    token_bytes = f.read()

token_b64 = base64.b64encode(token_bytes).decode("utf-8")

print("=" * 60)
print("  TOKEN_PICKLE_B64 value (copy everything below this line)")
print("=" * 60)
print(token_b64)
print("=" * 60)
print()
print("Next steps:")
print("  1. Copy the long string above")
print("  2. In Railway dashboard → your project → Variables")
print("  3. Add new variable: TOKEN_PICKLE_B64 = <paste here>")
print("  4. Redeploy")
