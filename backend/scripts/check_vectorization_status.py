# backend/scripts/list_unique_titles_scan.py
from azure.search.documents import SearchClient
from azure.core.credentials import AzureKeyCredential
import os, sys, urllib.parse

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config

def norm(s: str) -> str:
    if not s:
        return ""
    s = str(s).strip()
    s = s.replace("+", " ")
    return urllib.parse.unquote(s)

def main():
    client = SearchClient(
        endpoint=config.AZURE_SEARCH_ENDPOINT,
        index_name=config.AZURE_SEARCH_INDEX_NAME,
        credential=AzureKeyCredential(config.AZURE_SEARCH_KEY),
    )

    results = client.search(
        search_text="*",
        top=1000,
        select=["title", "url", "parent_id", "filepath", "chunk_id"]
    )

    titles = set()
    urls = set()

    for r in results:
        d = dict(r)
        if d.get("title"):
            titles.add(norm(d["title"]))
        if d.get("url"):
            urls.add(norm(d["url"]))

    print(f"\nUnique titles found: {len(titles)}")
    for i, t in enumerate(sorted(titles), 1):
        print(f"{i}. {t}")

    print(f"\nUnique urls found: {len(urls)}")
    # comment out if too noisy
    # for i, u in enumerate(sorted(urls), 1):
    #     print(f"{i}. {u}")

if __name__ == "__main__":
    main()
