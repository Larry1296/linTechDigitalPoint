"""Retrieval over the help articles in ``knowledge/``: each ``##`` section is one passage.

A small BM25 index is enough here: the knowledge base is a few dozen passages written in the
words customers use, and query expansion covers the common synonyms ("sign up" -> getting
started, "Excel" -> import spreadsheet). The index is built once per process.
"""
import math
import re
from collections import Counter
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from django.conf import settings

KNOWLEDGE_DIR = Path(__file__).resolve().parent / "knowledge"
ADMIN_KNOWLEDGE_DIR = Path(__file__).resolve().parent / "knowledge_admin"  # the platform administrator's articles only
STOPWORDS = set("""a an and are as at be by can could do does for from has have how i if in into is it its
me my of on or our so that the their them there these this to was we what when where which who why will
with would you your yours about any just not no yes get got""".split())
# Customer phrasing -> the words the articles use. Applied to the question only.
SYNONYMS = {
    "signup": "get started create account register", "sign": "sign in register account",
    "register": "create account get started", "registration": "create account get started",
    "start": "get started set up", "begin": "get started set up", "onboarding": "set up business steps",
    "setup": "set up business steps",
    "cost": "pricing price subscription plan", "price": "pricing selling price", "pricing": "subscription plan trial",
    "fee": "pricing subscription", "fees": "pricing subscription", "pay": "payment pricing subscription",
    "free": "trial pricing", "trial": "trial pricing subscription", "plan": "subscription plan pricing",
    "renew": "subscription plan", "expired": "subscription ends read only",
    "mpesa": "mpesa", "m-pesa": "mpesa", "lipa": "mpesa payment", "till": "cash mpesa payment", "float": "mpesa agency float",
    "agent": "mpesa agency agent",
    "excel": "import spreadsheet", "csv": "import spreadsheet", "spreadsheet": "import", "bulk": "import spreadsheet",
    "upload": "import spreadsheet logo", "duplicate": "import existing skipped", "duplicates": "import existing skipped",
    "inventory": "stock products", "stock": "stock inventory", "count": "stock adjustment count",
    "shelf": "shelves locations compartment", "shelves": "shelves locations compartment", "unplaced": "not shelf place",
    "employee": "staff role", "employees": "staff role", "worker": "staff role", "workers": "staff role",
    "user": "staff role", "users": "staff role", "cashier": "cashier staff role", "permission": "staff role access",
    "permissions": "staff role access", "access": "role access",
    "refund": "refund return sales history", "return": "refund return", "returns": "refund return",
    "receipt": "receipt print whatsapp email", "whatsapp": "receipt share", "print": "receipt printer",
    "discount": "bargain lowest price", "bargain": "lowest price", "credit": "credit sale customers owe",
    "debt": "credit customers owe", "owe": "customers owe credit",
    "report": "reports profit", "profit": "profit loss reports", "loss": "profit loss",
    "expense": "expenses money spent", "expenses": "money spent",
    "branch": "branches shop", "branches": "shop locations", "shops": "branches",
    "password": "password forgot reset", "forgot": "forgot password reset", "login": "sign in password",
    "locked": "idle session lock sign", "logout": "signed out session",
    "secure": "security private data", "safe": "security private data", "privacy": "private data security",
    "logo": "logo business", "barcode": "barcode scan scanner", "scanner": "barcode scan",
    "service": "services jobs", "printing": "cyber cafe printing services", "cyber": "cyber cafe printing services",
    "repair": "services jobs repairs", "repairs": "services jobs",
    "support": "contact support team", "contact": "contact support", "help": "support contact",
    "phone": "device browser", "install": "device browser hardware", "offline": "browser device",
    "currency": "currency country", "country": "countries currency", "kenya": "countries kenya",
}


@dataclass(frozen=True)
class Passage:
    article: str   # article title, e.g. "Pricing and subscriptions"
    heading: str   # section heading, e.g. "How much does DukaFlow cost?"
    text: str      # section body

    def render(self):
        return f"## {self.heading}\n(From: {self.article})\n{self.text}"


def _stem(word):
    for suffix in ("ing", "es", "ed", "s"):
        if len(word) > len(suffix) + 3 and word.endswith(suffix):
            return word[: -len(suffix)]
    return word


def tokens(text):
    words = re.findall(r"[a-z0-9]+(?:-[a-z0-9]+)?", text.lower())
    return [_stem(w.replace("-", "")) for w in words if w not in STOPWORDS]


def _fill(text):
    contact = settings.PLATFORM_CONTACT_EMAIL
    return (text.replace("{platform}", settings.PLATFORM_NAME)
                .replace("{contact}", f"Email the team at {contact}." if contact
                         else "A public support email has not been published yet; please use the contact details on the website."))


def load_passages(directory=KNOWLEDGE_DIR):
    passages = []
    for path in sorted(directory.glob("*.md")):
        content = _fill(path.read_text(encoding="utf-8"))
        # An article may hold several "# Title" parts; each "## Question" belongs to the title above it.
        for part in re.split(r"^# ", content, flags=re.M)[1:]:
            title, _, rest = part.partition("\n")
            for section in re.split(r"^## ", rest, flags=re.M)[1:]:
                heading, _, body = section.partition("\n")
                passages.append(Passage(article=title.strip(), heading=heading.strip(), text=body.strip()))
    return passages


class Index:
    """Okapi BM25 over passages; the heading counts twice because it is the question it answers."""

    def __init__(self, passages, k1=1.4, b=0.75):
        self.passages = passages
        self.docs = [tokens(f"{p.heading} {p.heading} {p.article} {p.text}") for p in passages]
        self.counts = [Counter(doc) for doc in self.docs]
        self.avg = sum(map(len, self.docs)) / max(len(self.docs), 1)
        frequency = Counter(term for doc in self.docs for term in set(doc))
        n = len(self.docs)
        self.idf = {term: math.log(1 + (n - df + 0.5) / (df + 0.5)) for term, df in frequency.items()}
        self.k1, self.b = k1, b

    def search(self, query, limit=5):
        words = tokens(query)
        raw = re.findall(r"[a-z0-9-]+", query.lower())
        expanded = words + [t for w in raw for t in tokens(SYNONYMS.get(w) or SYNONYMS.get(_stem(w), ""))]
        terms = Counter(expanded)
        scored = []
        for passage, counts, doc in zip(self.passages, self.counts, self.docs):
            score = 0.0
            for term, weight in terms.items():
                tf = counts.get(term)
                if tf:
                    norm = tf * (self.k1 + 1) / (tf + self.k1 * (1 - self.b + self.b * len(doc) / self.avg))
                    score += self.idf[term] * norm * (1 if term in words else 0.5) * min(weight, 2)
            if score > 0:
                scored.append((score, passage))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [passage for _, passage in scored[:limit]]


@lru_cache(maxsize=1)
def index():
    return Index(load_passages())


@lru_cache(maxsize=1)
def admin_index():
    return Index(load_passages(ADMIN_KNOWLEDGE_DIR))


def retrieve(question, previous="", limit=5):
    """Passages for the question; the previous question helps follow-ups like "and how much is it?"."""
    found = index().search(question, limit)
    if previous:
        seen = set(found)
        found += [p for p in index().search(f"{question} {previous}", limit) if p not in seen][: max(0, limit - len(found)) or 1]
    return found[: limit + 1]


def outline():
    """The article and section titles, so the model knows what the knowledge base covers."""
    lines, current = [], None
    for passage in index().passages:
        if passage.article != current:
            current = passage.article
            lines.append(f"- {current}:")
        lines.append(f"  - {passage.heading}")
    return "\n".join(lines)
