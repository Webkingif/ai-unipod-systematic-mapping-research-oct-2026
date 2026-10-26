import urllib.request
import urllib.parse
import json
import time

CROSSREF_API = "https://api.crossref.org/works"
MY_EMAIL = "your_actual_email@example.com"

def get_true_isca_dois(query_terms, rows=100):
    full_query = f"Interspeech {query_terms}"
    params = {
        "query": full_query,
        "rows": rows,
        "mailto": MY_EMAIL
    }
    url = f"{CROSSREF_API}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(
        url, 
        headers={"User-Agent": f"MappingStudyBot/1.0 (mailto:{MY_EMAIL})"}
    )
    
    try:
        with urllib.request.urlopen(req) as response:
            data = json.loads(response.read().decode("utf-8"))
            items = data.get("message", {}).get("items", [])
            
            dois = []
            for item in items:
                doi = item.get("DOI")
                if doi and doi.startswith("10.21437/"):  # Filters strictly for ISCA DOIs
                    dois.append(doi)
            return dois
    except Exception as e:
        print(f"Crossref query failed: {e}")
        return []

if __name__ == "__main__":
    query = "Yoruba"
    print(f"Querying Crossref for genuine ISCA papers matching: '{query}'...")
    dois = get_true_isca_dois(query, rows=100)
    
    print(f"\nFound {len(dois)} true ISCA/Interspeech DOIs:")
    print(" ".join(dois))
