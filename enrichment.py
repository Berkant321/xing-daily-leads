"""Data enrichment from external sources: LinkedIn, Google, Website, News.

Fetches and caches company intelligence to fuel KAM scoring and briefing.
Integrates with ChatGPT for synthesis and strategic insights.
"""
from __future__ import annotations

import json
import os
from datetime import date, datetime, timedelta
from typing import Any

import pandas as pd
import requests


class LinkedInEnricher:
    """Fetch company profile, headcount trends, recent hires, recent funding."""

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or os.getenv("LINKEDIN_API_KEY")
        self.base_url = "https://api.linkedin.com/v2"
        self.session = requests.Session()
        if self.api_key:
            self.session.headers.update({"Authorization": f"Bearer {self.api_key}"})

    def company_profile(self, company_name: str) -> dict[str, Any]:
        """Fetch LinkedIn company profile: employees, growth, industry, website."""
        if not self.api_key:
            return {"status": "skipped", "reason": "LINKEDIN_API_KEY not configured"}
        try:
            resp = self.session.get(
                f"{self.base_url}/search/companies",
                params={"q": company_name, "limit": 1},
                timeout=10,
            )
            if resp.status_code == 200 and resp.json().get("data"):
                company = resp.json()["data"][0]
                return {
                    "name": company.get("name"),
                    "industry": company.get("industry"),
                    "employee_count": company.get("employee_count_range"),
                    "website": company.get("website_url"),
                    "headcount_trend": company.get("headcount_change"),
                    "recent_hires_count": company.get("recent_employees_count"),
                    "source": "LinkedIn",
                    "fetched_at": datetime.now().isoformat(),
                }
            return {"status": "not_found", "query": company_name}
        except requests.RequestException as e:
            return {"status": "error", "error": str(e)}

    def recent_funding_and_news(self, company_name: str) -> list[dict[str, Any]]:
        """Fetch recent news, funding rounds, leadership changes."""
        if not self.api_key:
            return []
        try:
            resp = self.session.get(
                f"{self.base_url}/search/news",
                params={"q": company_name, "limit": 10},
                timeout=10,
            )
            if resp.status_code == 200:
                items = []
                for item in resp.json().get("data", []):
                    items.append(
                        {
                            "title": item.get("title"),
                            "published_at": item.get("published_date"),
                            "category": item.get("category"),
                            "url": item.get("url"),
                            "source": "LinkedIn News",
                        }
                    )
                return items
            return []
        except requests.RequestException:
            return []


class GoogleSearchEnricher:
    """Fetch recent news, press releases, public filing mentions."""

    def __init__(self, api_key: str | None = None, search_engine_id: str | None = None):
        self.api_key = api_key or os.getenv("GOOGLE_SEARCH_API_KEY")
        self.search_engine_id = search_engine_id or os.getenv("GOOGLE_SEARCH_ENGINE_ID")

    def search_news(self, company_name: str, limit: int = 5) -> list[dict[str, Any]]:
        """Search Google News for recent company mentions and developments."""
        if not self.api_key or not self.search_engine_id:
            return []
        try:
            query = f"{company_name} news OR press release OR earnings"
            resp = requests.get(
                "https://www.googleapis.com/customsearch/v1",
                params={
                    "q": query,
                    "cx": self.search_engine_id,
                    "key": self.api_key,
                    "tbm": "nws",
                    "num": limit,
                },
                timeout=10,
            )
            if resp.status_code == 200:
                items = []
                for result in resp.json().get("items", []):
                    items.append(
                        {
                            "title": result.get("title"),
                            "snippet": result.get("snippet"),
                            "link": result.get("link"),
                            "published_at": result.get("publishedDate"),
                            "source": "Google News",
                        }
                    )
                return items
            return []
        except requests.RequestException:
            return []


class WebsiteIntelligence:
    """Parse company website for careers, products, leadership, financial reports."""

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(
            {"User-Agent": "Mozilla/5.0 (KAM Intelligence Bot)"}
        )

    def fetch_careers_page(self, website_url: str) -> dict[str, Any]:
        """Check careers/jobs page for current hiring activity and open positions."""
        if not website_url:
            return {"status": "no_url"}
        try:
            resp = self.session.get(website_url, timeout=5)
            if resp.status_code == 200:
                content = resp.text.lower()
                open_positions = content.count("job") + content.count("career")
                has_careers_page = "careers" in content or "jobs" in content
                return {
                    "has_careers_page": has_careers_page,
                    "estimated_open_positions": max(0, open_positions // 5),
                    "status": "accessible",
                    "fetched_at": datetime.now().isoformat(),
                }
            return {"status": f"http_{resp.status_code}"}
        except requests.RequestException as e:
            return {"status": "error", "error": str(e)}

    def fetch_leadership(self, website_url: str) -> list[dict[str, str]]:
        """Extract leadership/team members from About page."""
        if not website_url:
            return []
        try:
            resp = self.session.get(website_url, timeout=5)
            if resp.status_code == 200:
                content = resp.text.lower()
                if "team" in content or "leadership" in content or "about" in content:
                    return [
                        {"note": "Leadership page found", "url": website_url}
                    ]
            return []
        except requests.RequestException:
            return []


class ChatGPTAnalyzer:
    """Use ChatGPT to synthesize company data into strategic insights."""

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        self.model = "gpt-4"

    def analyze_company_strategy(
        self, company_name: str, enrichment_data: dict[str, Any]
    ) -> dict[str, Any]:
        """Ask ChatGPT: What are this company's likely pain points, growth plans, and opportunities?"""
        if not self.api_key:
            return {"status": "skipped", "reason": "OPENAI_API_KEY not configured"}

        profile = enrichment_data.get("linkedin", {})
        news = enrichment_data.get("news", [])
        website = enrichment_data.get("website", {})

        prompt = f"""You are a KAM (Key Account Manager) analyst. 
        
Analyze this company and provide strategic insights in JSON format:

Company: {company_name}
Industry: {profile.get('industry', 'unknown')}
Employee Count: {profile.get('employee_count', 'unknown')}
Recent Hiring: {profile.get('recent_hires_count', 0)} new employees
Website: {profile.get('website', 'unknown')}

Recent News & Developments:
{json.dumps(news[:3], ensure_ascii=False, indent=2)}

Website Intelligence:
{json.dumps(website, ensure_ascii=False, indent=2)}

Provide a JSON response with these fields (only strings and lists, no null):
{{
  "strategic_focus": "What are their likely business priorities?",
  "growth_indicators": ["List", "of", "positive", "signals"],
  "challenges": ["List", "of", "likely", "pain", "points"],
  "recruitment_activity": "High/Medium/Low — based on hiring signals",
  "expansion_stage": "Startup/Growth/Mature/Decline",
  "recommended_approach": "How should we engage this account?",
  "confidence": "High/Medium/Low"
}}

Be concise. Base everything on the data provided, not guesses."""

        try:
            import openai

            openai.api_key = self.api_key
            response = openai.ChatCompletion.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
                max_tokens=500,
            )
            result_text = response["choices"][0]["message"]["content"]
            try:
                return json.loads(result_text)
            except json.JSONDecodeError:
                return {
                    "analysis": result_text,
                    "confidence": "Medium",
                    "parsed_from_text": True,
                }
        except ImportError:
            return {
                "status": "openai_not_installed",
                "instruction": "pip install openai",
            }
        except Exception as e:
            return {"status": "error", "error": str(e)}

    def generate_account_plan(
        self, company_name: str, current_position: str, strategy: dict[str, Any]
    ) -> str:
        """Generate a personalized KAM engagement plan based on company analysis."""
        if not self.api_key:
            return "ChatGPT not configured."

        prompt = f"""You are a KAM strategist.

Company: {company_name}
Current Position: {current_position}
Strategic Analysis: {json.dumps(strategy, ensure_ascii=False, indent=2)}

Generate a 3-month engagement plan with:
1. Immediate next steps (first 2 weeks)
2. Key questions to validate our hypothesis
3. Internal resources to mobilize
4. Success metrics

Format: Concise bullets, max 200 words."""

        try:
            import openai

            openai.api_key = self.api_key
            response = openai.ChatCompletion.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.4,
                max_tokens=300,
            )
            return response["choices"][0]["message"]["content"]
        except Exception as e:
            return f"Error generating plan: {str(e)}"


def enrich_company(
    company_name: str, website: str = ""
) -> dict[str, Any]:
    """One-call enrichment: gather all available intel on a company."""
    result = {
        "company_name": company_name,
        "enriched_at": datetime.now().isoformat(),
    }

    # LinkedIn
    linkedin = LinkedInEnricher()
    result["linkedin"] = linkedin.company_profile(company_name)
    result["linkedin_news"] = linkedin.recent_funding_and_news(company_name)

    # Google News
    google = GoogleSearchEnricher()
    result["news"] = google.search_news(company_name)

    # Website
    web = WebsiteIntelligence()
    result["website"] = web.fetch_careers_page(website) if website else {}
    result["leadership"] = web.fetch_leadership(website) if website else []

    # ChatGPT Analysis
    gpt = ChatGPTAnalyzer()
    result["strategy"] = gpt.analyze_company_strategy(
        company_name,
        {
            "linkedin": result.get("linkedin", {}),
            "news": result.get("news", []),
            "website": result.get("website", {}),
        },
    )

    return result
