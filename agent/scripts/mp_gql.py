"""Tiny Matterport GraphQL helper. Usage: python -m agent.scripts.mp_gql '<query>' ['{vars json}']"""
import json, os, sys, time
from pathlib import Path
import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")
URL = "https://api.matterport.com/api/models/graph"


def gql(query, variables=None, retries=4):
    auth = (os.environ["MATTERPORT_API_KEY"], os.environ["MATTERPORT_API_TOKEN"])
    for i in range(retries):
        try:
            r = httpx.post(URL, json={"query": query, "variables": variables or {}}, auth=auth, timeout=60)
            if r.status_code == 429 or r.status_code >= 500:
                time.sleep(2 ** i * 2); continue
            return r.json()
        except httpx.HTTPError:
            time.sleep(2 ** i * 2)
    return {"errors": [{"message": "request failed"}]}


if __name__ == "__main__":
    v = json.loads(sys.argv[2]) if len(sys.argv) > 2 else None
    print(json.dumps(gql(sys.argv[1], v), indent=1))
