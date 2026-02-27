#!/usr/bin/env python3
"""
Source Discovery Module
=======================
Uses Perplexity or Google Custom Search to discover Lloyd's market
commentary sources across the web. Returns URLs and snippets for
subsequent scraping.

Discovery engines:
- Perplexity: AI-powered search with citations (default)
- Google Custom Search: Traditional search API (optional)
"""

import os
import re
import json
import time
import logging
from dataclasses import dataclass, asdict, field
from typing import List, Dict, Optional, Any
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
import requests

# Load environment variables from .env file
load_dotenv()

logger = logging.getLogger(__name__)


@dataclass
class DiscoveredSource:
    """A source discovered via Perplexity web search."""
    url: str
    title: str
    snippet: str
    source_type: str  # 'lloyds_official', 'rating_agency', 'trade_press', 'broker', 'analyst'
    year: Optional[int]
    relevance_score: float
    discovery_query: str
    discovered_at: str = ""


class PerplexitySourceFinder:
    """
    Uses Perplexity API to discover Lloyd's market commentary sources.
    
    Perplexity's strength is web search with real-time results and citations.
    We use it purely for finding URLs - not for analysis or summarization.
    """
    
    MODELS = {
        "fast": "sonar",
        "balanced": "sonar-pro",
    }
    
    # Discovery queries optimized for finding reserve commentary
    DISCOVERY_QUERIES = {
        "lloyds_official": [
            "Lloyd's of London {year} annual report PDF reserve development prior year",
            "Lloyd's market results {year} combined ratio prior year release site:lloyds.com",
            "Lloyd's aggregate accounts {year} PDF",
            "Lloyd's half year results {year} reserve",
        ],
        "rating_agency": [
            "AM Best Lloyd's of London {year} rating report reserve PDF",
            "Fitch Lloyd's {year} rating rationale reserve development",
            "S&P Lloyd's of London {year} rating analysis",
            "Moody's Lloyd's market {year} credit opinion",
        ],
        "trade_press": [
            "Lloyd's {year} results reserve release strengthening site:reinsurancene.ws",
            "Lloyd's market {year} prior year development site:artemis.bm",
            "Lloyd's of London {year} annual results reserve site:insurancejournal.com",
            "Lloyd's {year} combined ratio reserve release site:insurancetimes.co.uk",
            "Lloyd's market results {year} casualty reserve social inflation",
        ],
        "broker_analyst": [
            "Gallagher Re Lloyd's market report {year} PDF",
            "Guy Carpenter Lloyd's {year} market review",
            "Aon Lloyd's market {year} analysis",
            "Alpha Insurance Analysts Lloyd's {year} results",
            "Lloyd's syndicate {year} reserve development analysis",
        ],
        "thematic": [
            "Lloyd's {year} casualty reserve social inflation US liability",
            "Lloyd's {year} property reserve catastrophe hurricane",
            "Lloyd's {year} marine aviation reserve Ukraine",
            "Lloyd's {year} motor reserve Ogden rate",
            "Lloyd's COVID-19 {year} reserve business interruption",
        ],
    }
    
    # Domain classification
    DOMAIN_TYPES = {
        'lloyds.com': 'lloyds_official',
        'ambest.com': 'rating_agency',
        'fitchratings.com': 'rating_agency',
        'spglobal.com': 'rating_agency',
        'moodys.com': 'rating_agency',
        'reinsurancene.ws': 'trade_press',
        'artemis.bm': 'trade_press',
        'insurancejournal.com': 'trade_press',
        'insurancetimes.co.uk': 'trade_press',
        'insurancebusinessmag.com': 'trade_press',
        'aianalysts.com': 'analyst',
        'ajg.com': 'broker',
        'aon.com': 'broker',
        'guycarp.com': 'broker',
        'willistowerswatson.com': 'broker',
    }
    
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.environ.get("PERPLEXITY_API_KEY")
        if not self.api_key:
            raise ValueError("Perplexity API key required. Set PERPLEXITY_API_KEY env var.")
        
        self.api_url = "https://api.perplexity.ai/chat/completions"
        self.discovered_sources: List[DiscoveredSource] = []
        self.seen_urls: set = set()
        
    def _call_api(self, query: str) -> Dict[str, Any]:
        """Make discovery query to Perplexity."""
        
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        # System prompt optimized for URL discovery
        system_prompt = """You are a research assistant finding sources about Lloyd's of London market results.

For each query, find and list relevant URLs with brief descriptions.

FORMAT YOUR RESPONSE AS:
1. [URL] - [Brief description of what the source contains]
2. [URL] - [Brief description]
...

Focus on:
- Official Lloyd's reports and PDFs
- Rating agency reports (AM Best, Fitch, S&P, Moody's)
- Insurance trade press articles
- Broker market reports
- Analyst commentary

Prioritize sources that discuss:
- Prior year reserve development/movements
- Reserve releases or strengthening
- Line of business performance
- Causal factors (catastrophes, inflation, litigation)

Return ONLY URLs and brief descriptions. No analysis or summarization."""

        payload = {
            "model": self.MODELS["balanced"],
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": query}
            ],
            "temperature": 0.1,
        }

        try:
            response = requests.post(
                self.api_url,
                headers=headers,
                json=payload,
                timeout=60
            )
            if not response.ok:
                logger.error(f"Perplexity API error response: {response.text}")
            response.raise_for_status()
            return response.json()
        except requests.exceptions.HTTPError as e:
            logger.error(f"Perplexity API error: {e}")
            raise
        except Exception as e:
            logger.error(f"Perplexity API error: {e}")
            raise
    
    def _extract_urls_from_response(self, response: Dict, query: str, year: int) -> List[DiscoveredSource]:
        """Extract URLs from Perplexity response."""
        sources = []
        
        content = response.get('choices', [{}])[0].get('message', {}).get('content', '')
        citations = response.get('citations', [])
        
        # Extract URLs from citations (most reliable)
        for url in citations:
            if url in self.seen_urls:
                continue
            
            source = self._create_source(url, "", query, year)
            if source:
                sources.append(source)
                self.seen_urls.add(url)
        
        # Also extract URLs from response text
        url_pattern = r'https?://[^\s\]\)\"\'<>]+'
        urls_in_text = re.findall(url_pattern, content)
        
        for url in urls_in_text:
            # Clean URL
            url = url.rstrip('.,;:')
            
            if url in self.seen_urls:
                continue
            
            # Try to find snippet near URL in content
            snippet = ""
            url_pos = content.find(url)
            if url_pos > 0:
                start = max(0, url_pos - 100)
                end = min(len(content), url_pos + len(url) + 200)
                snippet = content[start:end]
            
            source = self._create_source(url, snippet, query, year)
            if source:
                sources.append(source)
                self.seen_urls.add(url)
        
        return sources
    
    def _create_source(self, url: str, snippet: str, query: str, year: int) -> Optional[DiscoveredSource]:
        """Create a DiscoveredSource object from URL."""
        
        # Classify source type by domain
        source_type = "other"
        for domain, stype in self.DOMAIN_TYPES.items():
            if domain in url.lower():
                source_type = stype
                break
        
        # Calculate relevance score
        relevance = self._calculate_relevance(url, snippet)
        
        # Skip low-relevance sources
        if relevance < 0.3:
            return None
        
        return DiscoveredSource(
            url=url,
            title=self._extract_title(url),
            snippet=snippet[:500] if snippet else "",
            source_type=source_type,
            year=year,
            relevance_score=relevance,
            discovery_query=query,
            discovered_at=datetime.now().isoformat()
        )
    
    def _extract_title(self, url: str) -> str:
        """Extract a title from URL path."""
        from urllib.parse import urlparse, unquote
        
        path = urlparse(url).path
        # Get last meaningful segment
        segments = [s for s in path.split('/') if s and not s.startswith('?')]
        if segments:
            title = unquote(segments[-1])
            # Clean up file extensions and underscores
            title = re.sub(r'\.(pdf|html|htm|aspx?)$', '', title, flags=re.IGNORECASE)
            title = title.replace('-', ' ').replace('_', ' ')
            return title[:100]
        return url[:100]
    
    def _calculate_relevance(self, url: str, snippet: str) -> float:
        """Calculate relevance score for a discovered source."""
        score = 0.0
        combined = f"{url} {snippet}".lower()
        
        # Domain quality
        high_quality_domains = ['lloyds.com', 'ambest.com', 'fitchratings.com']
        medium_quality_domains = ['reinsurancene.ws', 'artemis.bm', 'insurancejournal.com']
        
        for domain in high_quality_domains:
            if domain in url.lower():
                score += 0.4
                break
        else:
            for domain in medium_quality_domains:
                if domain in url.lower():
                    score += 0.3
                    break
            else:
                score += 0.2
        
        # Content relevance keywords
        keywords = {
            'reserve': 0.15,
            'prior year': 0.15,
            'release': 0.1,
            'strengthening': 0.1,
            'combined ratio': 0.1,
            'casualty': 0.05,
            'property': 0.05,
            'annual report': 0.1,
            'market results': 0.1,
        }
        
        for keyword, weight in keywords.items():
            if keyword in combined:
                score += weight
        
        return min(score, 1.0)
    
    def discover_sources_for_year(self, year: int) -> List[DiscoveredSource]:
        """Discover all sources for a specific year."""
        
        sources = []
        
        for category, queries in self.DISCOVERY_QUERIES.items():
            logger.info(f"Discovering {category} sources for {year}...")
            
            for query_template in queries:
                query = query_template.format(year=year)
                
                try:
                    response = self._call_api(query)
                    new_sources = self._extract_urls_from_response(response, query, year)
                    sources.extend(new_sources)
                    
                    logger.info(f"  Query '{query[:50]}...' found {len(new_sources)} new sources")
                    
                    time.sleep(2)  # Rate limiting
                    
                except Exception as e:
                    logger.error(f"Error with query '{query}': {e}")
                    continue
        
        return sources
    
    def discover_all(self, years: List[int] = None) -> List[DiscoveredSource]:
        """Discover sources for multiple years."""
        
        if years is None:
            years = list(range(2014, 2025))
        
        all_sources = []
        
        for year in years:
            logger.info(f"\n=== Discovering sources for {year} ===")
            year_sources = self.discover_sources_for_year(year)
            all_sources.extend(year_sources)
            logger.info(f"Total for {year}: {len(year_sources)} sources")
        
        # Sort by relevance
        all_sources.sort(key=lambda x: x.relevance_score, reverse=True)
        
        self.discovered_sources = all_sources
        return all_sources
    
    def discover_by_line_of_business(self, lob: str, years: List[int] = None) -> List[DiscoveredSource]:
        """Discover sources specific to a line of business."""
        
        if years is None:
            years = [2022, 2023, 2024]
        
        lob_queries = {
            "property_reinsurance": [
                "Lloyd's {year} property reinsurance reserve catastrophe hurricane",
                "Lloyd's {year} property cat reserve release strengthening",
            ],
            "casualty_reinsurance": [
                "Lloyd's {year} casualty reinsurance reserve social inflation",
                "Lloyd's {year} liability reinsurance reserve US litigation",
            ],
            "casualty_direct": [
                "Lloyd's {year} casualty direct reserve professional liability D&O",
                "Lloyd's {year} general liability reserve social inflation US",
            ],
            "marine_aviation": [
                "Lloyd's {year} marine aviation reserve Ukraine war",
                "Lloyd's {year} MAT reserve cargo hull",
            ],
            "motor": [
                "Lloyd's {year} motor reserve Ogden rate UK",
                "Lloyd's {year} international motor reserve",
            ],
        }
        
        lob_key = lob.lower().replace(' ', '_').replace('-', '_')
        queries = lob_queries.get(lob_key, [f"Lloyd's {{year}} {lob} reserve development"])
        
        sources = []
        for year in years:
            for query_template in queries:
                query = query_template.format(year=year)
                try:
                    response = self._call_api(query)
                    new_sources = self._extract_urls_from_response(response, query, year)
                    sources.extend(new_sources)
                    time.sleep(2)
                except Exception as e:
                    logger.error(f"Error: {e}")
                    continue
        
        return sources
    
    def save_discovered_sources(self, filepath: str):
        """Save discovered sources to JSON."""
        
        data = {
            "discovered_at": datetime.now().isoformat(),
            "total_sources": len(self.discovered_sources),
            "sources_by_type": {},
            "sources": [asdict(s) for s in self.discovered_sources]
        }
        
        # Count by type
        for source in self.discovered_sources:
            stype = source.source_type
            data["sources_by_type"][stype] = data["sources_by_type"].get(stype, 0) + 1
        
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        
        logger.info(f"Saved {len(self.discovered_sources)} sources to {filepath}")
    
    def export_urls_for_scraping(self, filepath: str):
        """Export just URLs grouped by type for the scraper."""
        
        output = {
            "lloyds_official": [],
            "rating_agency": [],
            "trade_press": [],
            "broker": [],
            "analyst": [],
            "other": [],
        }
        
        for source in self.discovered_sources:
            stype = source.source_type
            if stype not in output:
                stype = "other"
            
            output[stype].append({
                "url": source.url,
                "year": source.year,
                "relevance": source.relevance_score
            })
        
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(output, f, indent=2)
        
        logger.info(f"Exported URLs to {filepath}")


class GoogleSearchFinder:
    """
    Uses Google Custom Search API to discover Lloyd's market commentary sources.

    Optional alternative to Perplexity for source discovery.
    Requires GOOGLE_API_KEY and GOOGLE_CSE_ID environment variables.
    """

    # Reuse domain classification from PerplexitySourceFinder
    DOMAIN_TYPES = PerplexitySourceFinder.DOMAIN_TYPES

    # Simplified queries for Google (no AI interpretation)
    DISCOVERY_QUERIES = {
        "lloyds_official": [
            "Lloyd's of London {year} annual report reserve development",
            "Lloyd's market results {year} prior year release site:lloyds.com",
        ],
        "rating_agency": [
            "AM Best Lloyd's {year} rating report reserve",
            "Fitch Lloyd's {year} rating reserve development",
        ],
        "trade_press": [
            "Lloyd's {year} reserve release site:reinsurancene.ws",
            "Lloyd's {year} prior year development site:artemis.bm",
            "Lloyd's {year} results reserve site:insurancejournal.com",
        ],
        "broker_analyst": [
            "Gallagher Re Lloyd's market report {year}",
            "Lloyd's syndicate {year} reserve analysis",
        ],
    }

    def __init__(self, api_key: Optional[str] = None, cse_id: Optional[str] = None):
        self.api_key = api_key or os.environ.get("GOOGLE_API_KEY")
        self.cse_id = cse_id or os.environ.get("GOOGLE_CSE_ID")

        if not self.api_key or not self.cse_id:
            raise ValueError(
                "Google API key and CSE ID required. "
                "Set GOOGLE_API_KEY and GOOGLE_CSE_ID env vars."
            )

        self.api_url = "https://www.googleapis.com/customsearch/v1"
        self.discovered_sources: List[DiscoveredSource] = []
        self.seen_urls: set = set()

    def _call_api(self, query: str, start: int = 1) -> Dict[str, Any]:
        """Make search query to Google Custom Search API."""

        params = {
            "key": self.api_key,
            "cx": self.cse_id,
            "q": query,
            "start": start,
            "num": 10,  # Max results per request
        }

        try:
            response = requests.get(self.api_url, params=params, timeout=30)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Google Search API error: {e}")
            raise

    def _extract_sources_from_response(self, response: Dict, query: str, year: int) -> List[DiscoveredSource]:
        """Extract sources from Google search response."""
        sources = []

        items = response.get('items', [])

        for item in items:
            url = item.get('link', '')

            if url in self.seen_urls:
                continue

            title = item.get('title', '')
            snippet = item.get('snippet', '')

            source = self._create_source(url, title, snippet, query, year)
            if source:
                sources.append(source)
                self.seen_urls.add(url)

        return sources

    def _create_source(self, url: str, title: str, snippet: str, query: str, year: int) -> Optional[DiscoveredSource]:
        """Create a DiscoveredSource object from search result."""

        # Classify source type by domain
        source_type = "other"
        for domain, stype in self.DOMAIN_TYPES.items():
            if domain in url.lower():
                source_type = stype
                break

        # Calculate relevance score
        relevance = self._calculate_relevance(url, title, snippet)

        # Skip low-relevance sources
        if relevance < 0.3:
            return None

        return DiscoveredSource(
            url=url,
            title=title[:200] if title else url[:100],
            snippet=snippet[:500] if snippet else "",
            source_type=source_type,
            year=year,
            relevance_score=relevance,
            discovery_query=query,
            discovered_at=datetime.now().isoformat()
        )

    def _calculate_relevance(self, url: str, title: str, snippet: str) -> float:
        """Calculate relevance score for a discovered source."""
        score = 0.0
        combined = f"{url} {title} {snippet}".lower()

        # Domain quality
        high_quality_domains = ['lloyds.com', 'ambest.com', 'fitchratings.com']
        medium_quality_domains = ['reinsurancene.ws', 'artemis.bm', 'insurancejournal.com']

        for domain in high_quality_domains:
            if domain in url.lower():
                score += 0.4
                break
        else:
            for domain in medium_quality_domains:
                if domain in url.lower():
                    score += 0.3
                    break
            else:
                score += 0.2

        # Content relevance keywords
        keywords = {
            'reserve': 0.15,
            'prior year': 0.15,
            'release': 0.1,
            'strengthening': 0.1,
            'combined ratio': 0.1,
            'casualty': 0.05,
            'property': 0.05,
            'annual report': 0.1,
            'market results': 0.1,
        }

        for keyword, weight in keywords.items():
            if keyword in combined:
                score += weight

        return min(score, 1.0)

    def discover_sources_for_year(self, year: int) -> List[DiscoveredSource]:
        """Discover all sources for a specific year."""

        sources = []

        for category, queries in self.DISCOVERY_QUERIES.items():
            logger.info(f"[Google] Discovering {category} sources for {year}...")

            for query_template in queries:
                query = query_template.format(year=year)

                try:
                    response = self._call_api(query)
                    new_sources = self._extract_sources_from_response(response, query, year)
                    sources.extend(new_sources)

                    logger.info(f"  Query '{query[:50]}...' found {len(new_sources)} new sources")

                    time.sleep(1)  # Rate limiting (Google allows 100 queries/day free)

                except Exception as e:
                    logger.error(f"Error with query '{query}': {e}")
                    continue

        return sources

    def discover_all(self, years: List[int] = None) -> List[DiscoveredSource]:
        """Discover sources for multiple years."""

        if years is None:
            years = [2022, 2023, 2024]  # Fewer years due to API limits

        all_sources = []

        for year in years:
            logger.info(f"\n=== [Google] Discovering sources for {year} ===")
            year_sources = self.discover_sources_for_year(year)
            all_sources.extend(year_sources)
            logger.info(f"Total for {year}: {len(year_sources)} sources")

        # Sort by relevance
        all_sources.sort(key=lambda x: x.relevance_score, reverse=True)

        self.discovered_sources = all_sources
        return all_sources

    def save_discovered_sources(self, filepath: str):
        """Save discovered sources to JSON."""

        data = {
            "discovered_at": datetime.now().isoformat(),
            "discovery_engine": "google",
            "total_sources": len(self.discovered_sources),
            "sources_by_type": {},
            "sources": [asdict(s) for s in self.discovered_sources]
        }

        # Count by type
        for source in self.discovered_sources:
            stype = source.source_type
            data["sources_by_type"][stype] = data["sources_by_type"].get(stype, 0) + 1

        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        logger.info(f"Saved {len(self.discovered_sources)} sources to {filepath}")

    def export_urls_for_scraping(self, filepath: str):
        """Export just URLs grouped by type for the scraper."""

        output = {
            "lloyds_official": [],
            "rating_agency": [],
            "trade_press": [],
            "broker": [],
            "analyst": [],
            "other": [],
        }

        for source in self.discovered_sources:
            stype = source.source_type
            if stype not in output:
                stype = "other"

            output[stype].append({
                "url": source.url,
                "year": source.year,
                "relevance": source.relevance_score
            })

        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(output, f, indent=2)

        logger.info(f"Exported URLs to {filepath}")


def main():
    """Main entry point for source discovery."""
    import argparse

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )

    parser = argparse.ArgumentParser(description="Discover Lloyd's commentary sources")
    parser.add_argument("--years", nargs="+", type=int, default=[2022, 2023, 2024],
                        help="Years to search")
    parser.add_argument("--output", default="discovered_sources.json",
                        help="Output JSON file")
    parser.add_argument("--lob", type=str, help="Search specific line of business")
    parser.add_argument("--google", action="store_true",
                        help="Use Google Custom Search instead of Perplexity")

    args = parser.parse_args()

    # Select discovery engine
    if args.google:
        print("Using Google Custom Search for discovery...")
        finder = GoogleSearchFinder()
    else:
        print("Using Perplexity for discovery...")
        finder = PerplexitySourceFinder()

    if args.lob and hasattr(finder, 'discover_by_line_of_business'):
        sources = finder.discover_by_line_of_business(args.lob, args.years)
    else:
        sources = finder.discover_all(args.years)
    
    finder.save_discovered_sources(args.output)
    finder.export_urls_for_scraping(args.output.replace('.json', '_urls.json'))
    
    # Summary
    print(f"\n=== Discovery Summary ===")
    print(f"Total sources found: {len(sources)}")
    
    by_type = {}
    for s in sources:
        by_type[s.source_type] = by_type.get(s.source_type, 0) + 1
    
    for stype, count in sorted(by_type.items(), key=lambda x: -x[1]):
        print(f"  {stype}: {count}")
    
    print(f"\nTop 10 by relevance:")
    for s in sources[:10]:
        print(f"  [{s.relevance_score:.2f}] {s.source_type}: {s.url[:70]}...")


if __name__ == "__main__":
    main()
