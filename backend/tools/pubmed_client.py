"""
PubMed client tool.

Executes two sequential calls against the NCBI E-utilities API:
  1. esearch — converts a query + filters into a list of PubMed IDs (PMIDs)
  2. efetch  — fetches full article metadata (title, abstract, journal,
               publication date) for those PMIDs

Abstracts are truncated at 250 words to manage Claude's context window.
If no results are found, returns a structured message so Claude can
decide to retry with a refined query or different date range.

Authentication is optional — PUBMED_API_KEY in .env raises the rate
limit from 3 to 10 requests/sec, useful for future scaling.
"""

from __future__ import annotations

import os
import xml.etree.ElementTree as ET

import httpx
from dotenv import load_dotenv

from tools.cache import DEFAULT_TTL_SECONDS, async_ttl_cache

load_dotenv()

_ESEARCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
_EFETCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
_ABSTRACT_WORD_LIMIT = 250


def _base_params() -> dict:
    """
    Returns base parameters shared across all NCBI API calls.

    Includes the API key if set in the environment, otherwise omits it
    and falls back to the unauthenticated rate limit (3 req/sec).
    """
    params = {}
    api_key = os.getenv("PUBMED_API_KEY")
    if api_key:
        params["api_key"] = api_key
    return params


def _truncate_abstract(text: str) -> str:
    """
    Truncates abstract text to _ABSTRACT_WORD_LIMIT words.

    Args:
        text: Raw abstract string from the PubMed XML response.

    Returns:
        Truncated string with ellipsis appended if truncation occurred.
    """
    words = text.split()
    if len(words) <= _ABSTRACT_WORD_LIMIT:
        return text
    return " ".join(words[:_ABSTRACT_WORD_LIMIT]) + "..."


def _parse_articles(xml_text: str) -> list[dict]:
    """
    Parses the efetch XML response into a list of article dicts.

    Each dict contains: pmid, title, journal, pub_date, abstract.
    Structured abstracts (with labelled sections like BACKGROUND,
    RESULTS) are concatenated into a single string before truncation.

    Args:
        xml_text: Raw XML string returned by the efetch endpoint.

    Returns:
        List of article dicts, one per PubmedArticle element found.
    """
    root = ET.fromstring(xml_text)
    articles = []

    for article_el in root.findall(".//PubmedArticle"):
        citation = article_el.find("MedlineCitation")
        if citation is None:
            continue

        # PMID
        pmid_el = citation.find("PMID")
        pmid = pmid_el.text if pmid_el is not None else ""

        article = citation.find("Article")
        if article is None:
            continue

        # Title
        title_el = article.find("ArticleTitle")
        title = "".join(title_el.itertext()) if title_el is not None else ""

        # Journal
        journal_el = article.find("Journal/Title")
        journal = journal_el.text if journal_el is not None else ""

        # Publication date — prefer structured Year/Month, fall back to MedlineDate
        year_el = article.find("Journal/JournalIssue/PubDate/Year")
        month_el = article.find("Journal/JournalIssue/PubDate/Month")
        medline_el = article.find("Journal/JournalIssue/PubDate/MedlineDate")

        if year_el is not None:
            pub_date = year_el.text
            if month_el is not None:
                pub_date = f"{month_el.text} {pub_date}"
        elif medline_el is not None:
            pub_date = medline_el.text
        else:
            pub_date = ""

        # Abstract — concatenate all sections (handles structured abstracts)
        abstract_parts = []
        for abstract_text_el in article.findall("Abstract/AbstractText"):
            label = abstract_text_el.get("Label")
            text = "".join(abstract_text_el.itertext()).strip()
            if label:
                abstract_parts.append(f"{label}: {text}")
            else:
                abstract_parts.append(text)

        raw_abstract = " ".join(abstract_parts)
        abstract = _truncate_abstract(raw_abstract) if raw_abstract else ""

        articles.append(
            {
                "pmid": pmid,
                "title": title,
                "journal": journal,
                "pub_date": pub_date,
                "abstract": abstract,
            }
        )

    return articles


@async_ttl_cache(ttl_seconds=DEFAULT_TTL_SECONDS)
async def search(
    query: str,
    reldate: int,
    retmax: int,
    sort: str,
) -> dict:
    """
    Searches PubMed and returns structured article data for Claude.

    Executes esearch to get matching PMIDs, then efetch to retrieve
    article content. Returns an empty results list with an explanatory
    message if no studies are found, so Claude can refine its query.

    Args:
        query:   Search terms — clinical keywords, drug names, MeSH terms.
        reldate: Restrict to articles published in the last N days.
        retmax:  Maximum number of articles to return (capped at 10).
        sort:    'relevance' or 'pub+date'.

    Returns:
        Dict with a 'results' list and a 'message' string. On success,
        'results' contains article dicts. On failure, 'results' is empty
        and 'message' explains what went wrong.
    """
    async with httpx.AsyncClient(timeout=15) as client:
        # Step 1: esearch — get PMIDs matching the query and filters
        esearch_params = {
            **_base_params(),
            "db": "pubmed",
            "term": query,
            "retmax": retmax,
            "reldate": reldate,
            "datetype": "pdat",
            "sort": sort,
            "retmode": "json",
        }

        esearch_resp = await client.get(_ESEARCH_URL, params=esearch_params)
        esearch_resp.raise_for_status()
        esearch_data = esearch_resp.json()

        pmids = esearch_data.get("esearchresult", {}).get("idlist", [])

        if not pmids:
            return {
                "results": [],
                "message": (
                    f"No studies found for query: '{query}' within the last "
                    f"{reldate} days. Consider broadening the search terms or "
                    f"adjusting the date range."
                ),
            }

        # Step 2: efetch — retrieve article content for the returned PMIDs
        efetch_params = {
            **_base_params(),
            "db": "pubmed",
            "id": ",".join(pmids),
            "retmode": "xml",
            "rettype": "abstract",
        }

        efetch_resp = await client.get(_EFETCH_URL, params=efetch_params)
        efetch_resp.raise_for_status()

        articles = _parse_articles(efetch_resp.text)

        return {
            "results": articles,
            "message": f"Found {len(articles)} studies for query: '{query}'.",
        }
