"""Rule-based job-title parser.

title (+ optional HR department field) -> level, department, specialty, flags and confidence.

Written separately from the generator's vocabulary on purpose: the parser should
generalise from keywords, not memorise the generator's tables. Typo repair uses
RapidFuzz (MIT) against the parser's own token vocabulary.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, asdict
from functools import lru_cache

from rapidfuzz import fuzz, process

LEVEL_NAMES = {0: "CEO", 1: "Executive", 2: "VP", 3: "Director", 4: "Manager", 5: "IC"}

ABBREV = {
    "sr": "senior", "snr": "senior", "jr": "junior", "mgr": "manager", "mngr": "manager", "dir": "director",
    "eng": "engineering", "engr": "engineer", "svp": "vp", "evp": "vp", "avp": "vp", "mktg": "marketing",
    "ops": "operations", "fin": "finance", "swe": "software engineer", "sde": "software engineer",
    "ae": "account executive", "csm": "customer success manager", "pmm": "product marketing manager",
    "ml": "machine learning", "dev": "developer", "devs": "developers", "infosec": "security",
    "cybersecurity": "security", "em": "engineering manager", "cx": "customer experience", "hrbp": "hr business partner",
}
EXEC_ABBREV = {"ceo": "CEO", "cto": "CTO", "cfo": "CFO", "cro": "CRO", "cmo": "CMO", "coo": "COO", "cpo": "CPO",
               "chro": "CHRO", "cdo": "CDO", "cio": "CIO", "ciso": "CISO", "cso": "CISO", "clo": "GC", "cco": "CCO"}
EXEC_PHRASES = [  # (phrase, role) checked in order
    ("chief executive", "CEO"), ("chief technology", "CTO"), ("chief technical", "CTO"),
    ("chief data", "CDO"), ("chief product", "CPO"), ("chief revenue", "CRO"), ("chief commercial", "CRO"),
    ("chief sales", "CRO"), ("chief marketing", "CMO"), ("chief customer", "CCO"), ("chief financial", "CFO"),
    ("chief finance", "CFO"), ("chief people", "CHRO"), ("chief human", "CHRO"), ("chief legal", "GC"),
    ("general counsel", "GC"), ("chief operating", "COO"), ("chief operations", "COO"),
    ("chief information security", "CISO"), ("chief security", "CISO"), ("chief information", "CIO"),
]
EXEC_DEPT = {"CTO": "Engineering", "CDO": "Data", "CPO": "Product", "CRO": "Sales", "CMO": "Marketing",
             "CCO": "Customer Success", "CFO": "Finance", "CHRO": "People", "GC": "Legal", "COO": "Operations",
             "CIO": "IT", "CISO": "Security"}

# Ordered: earlier, more specific phrases win ("data engineer" -> Data, not Engineering).
DEPT_RULES = [
    ("Data", ["data engineer", "analytics engineer", "data scien", "machine learning", "data analyst",
              "business intelligence", " bi ", " etl ", "big data", "applied scien", "data and ai", " data ",
              "analytics"]),
    ("Security", ["security", " soc ", " grc ", "information security"]),
    ("IT", ["it support", "help desk", "helpdesk", "desktop support", "systems administrator", "it systems",
            "salesforce administrator", "information technology", " it ", "systems manager"]),
    ("Sales", ["sales engineer", "solutions engineer", "account executive", "sales", " sdr ", " bdr ",
               "business development", "revenue", "enterprise", "mid market", " smb "]),
    ("Marketing", ["product marketing", "marketing", "marketer", "demand gen", "content", "copywriter", "brand",
                   "graphic designer", "social media"]),
    ("Customer Success", ["customer success", "customer support", "support", "customer service", "onboarding",
                          "implementation", "account manager", "account management", "customer experience",
                          " cs "]),
    ("Engineering", ["ui engineer"]),
    ("Design", ["product designer", " ux ", " ui ", "designer", "design", "user research"]),
    ("Product", ["product manager", "product owner", "product analyst", "product lead", " product"]),
    ("Finance", ["financ", " fpa ", "accountant", "accounting", "accounts payable", "payroll", "controller"]),
    ("People", ["recruit", "talent", "sourcer", " hr ", "human resources", "people"]),
    ("Legal", ["counsel", "legal", "paralegal", "contracts", "compliance", "risk analyst"]),
    ("Operations", ["operations", "supply chain", "logistics", "warehouse", "procurement", " buyer", "facilities",
                    "office manager", "workplace", "plant manager", "program manager", "project manager"]),
    ("Engineering", ["engineer", "developer", "software", " sre ", "site reliability", "devops", " qa ",
                     "quality assurance", " test ", "sdet", " ios ", "android", "mobile", "frontend", "front end",
                     "backend", "back end", "platform", "infrastructure", "technology", "engineering"]),
]
SPEC_RULES = {
    "Engineering": [("Backend", ["backend", "back end"]), ("Frontend", ["frontend", "front end", "ui engineer"]),
                    ("Platform", ["platform", " sre ", "site reliability", "devops", "infrastructure"]),
                    ("Mobile", ["mobile", " ios ", "android"]),
                    ("QA", [" qa ", " test ", "sdet", "quality"])],
    "Data": [("Data Engineering", ["data engineer", "analytics engineer", " etl ", "big data"]),
             ("Machine Learning", ["machine learning", "data scien", "applied scien"]),
             ("Analytics", ["analyst", "analytics", " bi ", "business intelligence"])],
    "Product": [("Growth", ["growth", "product analyst"]), ("Core Product", ["core product"])],
    "Design": [("UX Research", ["research"]), ("Product Design", ["designer", "product design"])],
    "Sales": [("Sales Development", [" sdr ", " bdr ", "sales development", "business development"]),
              ("Enterprise", ["enterprise", "solutions engineer", "sales engineer"]),
              ("Mid-Market", ["mid market"]), ("SMB", [" smb ", "inside sales"])],
    "Marketing": [("Product Marketing", ["product marketing", "product marketer"]),
                  ("Demand Generation", ["demand", "performance"]),
                  ("Content", ["content", "copywriter", "social media"]), ("Brand", ["brand", "graphic"])],
    "Customer Success": [("Onboarding", ["onboarding", "implementation"]),
                         ("Account Management", ["account manage", "customer success manager"]),
                         ("Support", ["support", "service", "agent"])],
    "Finance": [("FP&A", [" fpa ", "financial analyst", "finance business partner"]),
                ("Accounting", ["account", "payroll", "payable"])],
    "People": [("Recruiting", ["recruit", "talent", "sourcer"]),
               ("People Operations", [" hr ", "people partner", "people operations", "generalist"])],
    "Legal": [("Compliance", ["compliance", "risk"]), ("Legal", ["counsel", "legal", "paralegal", "contracts"])],
    "Operations": [("Supply Chain", ["supply", "logistics", "warehouse", "procurement", "buyer", "plant"]),
                   ("Facilities", ["facilities", "office manager", "workplace"]),
                   ("Business Operations", ["business operations", "operations analyst", "program", "project"])],
    "IT": [("IT Support", ["support", "help desk", "helpdesk", "desktop"]),
           ("Corporate Systems", ["systems", "administrator", "salesforce"])],
    "Security": [("GRC", [" grc ", "compliance", "risk"]),
                 ("Security Engineering", ["security engineer", "application security", " soc "])],
}
# "...manager" titles that are individual contributors, not people managers.
IC_MANAGER_PHRASES = ["product manager", "account manager", "customer success manager", "product marketing manager",
                      "social media manager", "brand manager", "office manager", "program manager",
                      "project manager", "implementation manager", "contracts manager"]
MANAGER_PHRASES = ["engineering manager", "group product manager", "manager", "controller", "head of"]
IC_NOUNS = ["engineer", "developer", "analyst", "designer", "specialist", "representative", "executive",
            "scientist", "recruiter", "accountant", "counsel", "coordinator", "administrator", "associate",
            "consultant", "writer", "strategist", "partner", "generalist", "researcher", "technician", "agent",
            "paralegal", "sourcer", "officer", "marketer", "copywriter", "buyer", "owner", " sdr", " bdr", "sdet",
            " sre", "intern", "manager", "advisor"]
DEPT_FIELD_MAP = {
    "engineering": ["Engineering"], "eng": ["Engineering"], "tech": ["Engineering"], "technology": ["Engineering"],
    "r and d": ["Engineering", "Product"], "rd": ["Engineering", "Product"],
    "product and engineering": ["Engineering", "Product"], "data": ["Data"], "data and analytics": ["Data"],
    "bi": ["Data"], "data science": ["Data"], "product": ["Product"], "product mgmt": ["Product"],
    "product management": ["Product"], "design": ["Design"], "ux": ["Design"], "sales": ["Sales"],
    "gtm": ["Sales", "Marketing"], "revenue": ["Sales"], "commercial": ["Sales"], "marketing": ["Marketing"],
    "mktg": ["Marketing"], "customer success": ["Customer Success"], "support": ["Customer Success"],
    "cx": ["Customer Success"], "customer service": ["Customer Success"], "finance": ["Finance"],
    "accounting": ["Finance"], "fin": ["Finance"], "people": ["People"], "hr": ["People"],
    "human resources": ["People"], "talent": ["People"], "legal": ["Legal"], "compliance": ["Legal"],
    "operations": ["Operations"], "ops": ["Operations"], "supply chain": ["Operations"], "it": ["IT", "Security"],
    "information technology": ["IT"], "security": ["Security"], "infosec": ["Security"],
}


@dataclass
class ParsedTitle:
    level: int | None
    dept: str | None
    specialty: str | None
    exec_role: str | None = None
    seniority: str | None = None
    is_contractor: bool = False
    is_assistant: bool = False
    head_of: bool = False
    level_conf: float = 0.0
    dept_conf: float = 0.0
    parsed_by: str = "rules"   # rules | llm | none

    @property
    def conf(self) -> float:
        return self.level_conf * (self.dept_conf if self.level and self.level > 0 else 1.0)

    def as_dict(self) -> dict:
        d = asdict(self)
        d["parse_conf"] = self.conf
        return d


def _ascii(s: str) -> str:
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()


def _vocab() -> list[str]:
    words = set(ABBREV.values()) | set(EXEC_ABBREV)
    for _, phrases in DEPT_RULES:
        for p in phrases:
            words.update(p.split())
    for rules in SPEC_RULES.values():
        for _, phrases in rules:
            for p in phrases:
                words.update(p.split())
    for p in IC_MANAGER_PHRASES + MANAGER_PHRASES + IC_NOUNS + [x for x, _ in EXEC_PHRASES]:
        words.update(p.split())
    words.update(["senior", "junior", "staff", "principal", "lead", "director", "vice", "president", "head",
                  "chief", "officer", "intern", "founder", "assistant", "executive", "contract", "contractor",
                  "group", "regional", "team", "global", "associate", "analyst", "engineering", "developer"])
    return sorted(w for w in words if len(w) >= 4)


VOCAB = _vocab()
VOCAB_SET = set(VOCAB)


def _fix_token(tok: str) -> str:
    if len(tok) < 5 or tok in VOCAB_SET or not tok.isalpha():
        return tok
    m = process.extractOne(tok, VOCAB, scorer=fuzz.ratio, score_cutoff=84)
    return m[0] if m else tok


def normalise(title: str) -> tuple[str, dict]:
    """Lower-case, strip junk, expand abbreviations, repair typos. Returns (text, flags)."""
    flags = {"contract": False, "intern": False}
    t = _ascii(title).strip()
    t = re.split(r"\s[|@]\s|\s-\s(?:open to work)", t, maxsplit=1)[0]
    low = t.lower()
    if re.search(r"contract", low):
        flags["contract"] = True
        low = re.sub(r"\(?\[?\b(contractor|contract)\b\]?\)?", " ", low)
    low = re.sub(r"\((she|he|they)/(her|him|them)\)", " ", low)
    low = low.replace("fp&a", " fpa ").replace("r&d", " rd ").replace("&", " and ")
    low = re.sub(r"[(),.\[\]/:;!+_-]", " ", low)
    toks = []
    for tok in low.split():
        if tok in ABBREV:
            toks.extend(ABBREV[tok].split())
        else:
            toks.append(_fix_token(tok))
    text = " " + " ".join(toks) + " "
    text = text.replace(" vice president ", " vp ").replace(" mid market ", " mid market ")
    if " intern " in text:
        flags["intern"] = True
    return text, flags


def _first_dept(text: str) -> str | None:
    for dept, phrases in DEPT_RULES:
        if any(p in text for p in phrases):
            return dept
    return None


def _specialty(text: str, dept: str | None) -> str | None:
    for spec, phrases in SPEC_RULES.get(dept or "", []):
        if any(p in text for p in phrases):
            return spec
    return None


def _seniority(text: str) -> str:
    if " intern " in text:
        return "intern"
    if any(w in text for w in (" junior ", " associate ", " i ")):
        return "junior"
    if any(w in text for w in (" staff ", " principal ")):
        return "staff"
    if " lead " in text:
        return "lead"
    if any(w in text for w in (" senior ", " iii ")):
        return "senior"
    return "mid"


def dept_from_field(field: str | None) -> list[str]:
    if not field or not isinstance(field, str):
        return []
    key = re.sub(r"\s+", " ", _ascii(field).lower().replace("&", " and ").replace("r and d", "rd")).strip()
    return DEPT_FIELD_MAP.get(key, [])


@lru_cache(maxsize=200_000)
def parse_title(title: str | None, dept_field: str | None = None) -> ParsedTitle:
    fdepts = dept_from_field(dept_field)
    if not title or not isinstance(title, str) or not title.strip():
        return ParsedTitle(None, fdepts[0] if len(fdepts) == 1 else None, None, dept_conf=0.6 if fdepts else 0.0,
                           parsed_by="none")
    text, flags = normalise(title)
    p = ParsedTitle(level=None, dept=None, specialty=None, is_contractor=flags["contract"])

    # ---- level -------------------------------------------------------
    role = None
    if " chief of staff " in text or " executive assistant " in text or " ea to " in text:
        p.is_assistant, p.level, p.level_conf = True, 5, 0.9
    else:
        for phrase, r in EXEC_PHRASES:
            if phrase in text:
                role = r
                break
        if not role:
            for tok in text.split():
                if tok in EXEC_ABBREV:
                    role = EXEC_ABBREV[tok]
                    break
        if role == "CEO" or (not role and " founder " in text and " president " not in text):
            p.level, p.exec_role, p.level_conf = 0, "CEO", 0.97 if role else 0.5
        elif role:
            p.level, p.exec_role, p.dept = 1, role, EXEC_DEPT[role]
            p.level_conf = 0.8 if (role == "CPO" and "chief" not in text) else 0.95
        elif " president " in text and " vp " not in text:
            p.level, p.exec_role, p.level_conf = 0, "CEO", 0.6
        elif " vp " in text:
            p.level, p.level_conf = 2, 0.95
        elif " head of " in text:
            p.level, p.head_of, p.level_conf = 3, True, 0.75
        elif " director " in text:
            p.level, p.level_conf = 3, 0.95
        elif any(ph in text for ph in IC_MANAGER_PHRASES) and " group " not in text:
            # "Program Manager Lead" / "CSM Lead" are senior ICs, not people managers
            p.level, p.level_conf = 5, 0.75
        elif " intern " in text:
            p.level, p.level_conf = 5, 0.95
        elif any(ph in text for ph in MANAGER_PHRASES):
            p.level, p.level_conf = 4, 0.9
        elif " team lead " in text or re.search(r"^ (product|design) lead ", text) or text.startswith(" lead "):
            # "Lead Data Engineer" is an IC; "Lead, Analytics" / "Team Lead" manage people
            if text.startswith(" lead ") and any(n.strip() in text.split() for n in IC_NOUNS):
                p.level, p.level_conf = 5, 0.8
            else:
                p.level, p.level_conf = 4, 0.65
        elif " senior counsel " in text:
            p.level, p.level_conf = 5, 0.55
        elif any(n in text for n in IC_NOUNS) or _first_dept(text):
            p.level, p.level_conf = 5, 0.85
        else:
            p.level, p.level_conf = None, 0.0

    # ---- department ---------------------------------------------------
    if p.level == 1:
        p.dept_conf = 0.95
    elif p.is_assistant or p.level == 0:
        p.dept, p.dept_conf = None, 1.0
    else:
        tdept = _first_dept(text)
        if tdept and fdepts:
            p.dept, p.dept_conf = (tdept, 0.97) if tdept in fdepts else (tdept, 0.7)
        elif tdept:
            p.dept, p.dept_conf = tdept, 0.85
        elif fdepts:
            p.dept, p.dept_conf = fdepts[0], 0.7 if len(fdepts) == 1 else 0.4
        else:
            p.dept, p.dept_conf = None, 0.0
    if p.level is not None and p.level >= 2:
        p.specialty = _specialty(text, p.dept)
        # A dept-level noun ("Head of Data") is not a specialty
        if p.level <= 3 and p.specialty and p.dept == "Data" and p.specialty == "Analytics" and "analytics" in text \
                and " data " in text:
            p.specialty = None
    if p.level == 5:
        p.seniority = _seniority(text)
    if p.level is None:
        p.parsed_by = "none"
        from . import llm_fallback   # optional, off unless ORGCHART_LLM=1 and a client is plugged in
        if llm_fallback.enabled():
            d = llm_fallback.classify(title)
            if d:
                p.level, p.dept, p.level_conf, p.dept_conf = d["level"], d["dept"] or p.dept, d["conf"], d["conf"]
                p.parsed_by = "llm"
    return p
