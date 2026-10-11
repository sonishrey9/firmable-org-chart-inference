"""Synthetic dataset generator: truth first, mess second.

Every company is built as a true reporting tree. The flat, messy people list is
derived from it, and the hidden answer key (manager_id and true attributes) is
written separately. The vocabulary here is deliberately independent from the
parser in ``titles.py`` and includes a held-out set of titles the parser was never
written for.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from datetime import date, timedelta

import pandas as pd
from faker import Faker

TODAY = date(2026, 10, 1)

# --------------------------------------------------------------------------
# Company-level vocabulary
# --------------------------------------------------------------------------
INDUSTRIES = {
    # industry: department weights
    "SaaS":          {"Engineering": 30, "Data": 6, "Product": 7, "Design": 3, "Sales": 18, "Marketing": 8, "Customer Success": 10, "Finance": 4, "People": 4, "Legal": 1.5, "Operations": 3, "IT": 2, "Security": 3},
    "Fintech":       {"Engineering": 26, "Data": 8, "Product": 6, "Design": 2, "Sales": 12, "Marketing": 6, "Customer Success": 9, "Finance": 9, "People": 4, "Legal": 4, "Operations": 6, "IT": 3, "Security": 5},
    "Banking":       {"Engineering": 14, "Data": 7, "Product": 3, "Sales": 14, "Marketing": 5, "Customer Success": 12, "Finance": 16, "People": 5, "Legal": 7, "Operations": 10, "IT": 6, "Security": 5},
    "Healthcare":    {"Engineering": 12, "Data": 6, "Product": 3, "Sales": 10, "Marketing": 6, "Customer Success": 14, "Finance": 8, "People": 6, "Legal": 5, "Operations": 24, "IT": 6},
    "Retail":        {"Engineering": 8, "Data": 4, "Product": 2, "Design": 2, "Sales": 22, "Marketing": 12, "Customer Success": 12, "Finance": 7, "People": 7, "Legal": 2, "Operations": 26, "IT": 4},
    "Manufacturing": {"Engineering": 12, "Data": 3, "Sales": 14, "Marketing": 5, "Customer Success": 6, "Finance": 8, "People": 6, "Legal": 2, "Operations": 40, "IT": 5},
    "Logistics":     {"Engineering": 10, "Data": 5, "Product": 2, "Sales": 14, "Marketing": 4, "Customer Success": 12, "Finance": 7, "People": 6, "Legal": 2, "Operations": 38, "IT": 4},
    "Media":         {"Engineering": 16, "Data": 6, "Product": 6, "Design": 8, "Sales": 18, "Marketing": 18, "Customer Success": 6, "Finance": 6, "People": 5, "Legal": 4, "Operations": 5, "IT": 2},
    "EdTech":        {"Engineering": 22, "Data": 6, "Product": 7, "Design": 5, "Sales": 16, "Marketing": 12, "Customer Success": 14, "Finance": 4, "People": 5, "Legal": 1.5, "Operations": 5, "IT": 2},
}

COUNTRIES = {
    "US": ("en_US", ["New York", "San Francisco", "Austin", "Chicago", "Boston", "Seattle", "Denver"]),
    "IN": ("en_IN", ["Bengaluru", "Mumbai", "Pune", "Hyderabad", "Gurugram", "Chennai"]),
    "GB": ("en_GB", ["London", "Manchester", "Edinburgh", "Bristol"]),
    "AU": ("en_AU", ["Sydney", "Melbourne", "Brisbane", "Perth"]),
    "DE": ("de_DE", ["Berlin", "Munich", "Hamburg"]),
    "ES": ("es_ES", ["Madrid", "Barcelona", "Valencia"]),
}
COUNTRY_WEIGHTS = {"US": 35, "IN": 22, "GB": 14, "AU": 14, "DE": 8, "ES": 7}

SIZE_BUCKETS = [((100, 199), 45), ((200, 499), 33), ((500, 999), 16), ((1000, 1800), 6)]

NOISE_LEVELS = {"clean": 0.3, "moderate": 1.0, "messy": 1.7, "very_messy": 2.5}
NOISE_WEIGHTS = {"clean": 15, "moderate": 40, "messy": 30, "very_messy": 15}

COMPANY_WORDS = ["Nimbus", "Quanta", "Bluefin", "Arbor", "Lumen", "Kestrel", "Vertex", "Harbor", "Saffron", "Cobalt",
                 "Juniper", "Orbit", "Tidal", "Ember", "Granite", "Atlas", "Willow", "Pioneer", "Copper", "Meridian",
                 "Aurora", "Falcon", "Indigo", "Summit", "Beacon", "Northwind", "Cascade", "Zephyr", "Monsoon", "Banyan"]
COMPANY_SUFFIX = {"SaaS": ["Labs", "Cloud", "Software", "AI"], "Fintech": ["Pay", "Capital", "Money", "Finance"],
                  "Banking": ["Bank", "Financial", "Trust"], "Healthcare": ["Health", "Care", "Medical"],
                  "Retail": ["Stores", "Retail", "Market"], "Manufacturing": ["Industries", "Manufacturing", "Works"],
                  "Logistics": ["Logistics", "Freight", "Express"], "Media": ["Media", "Studios", "Publishing"],
                  "EdTech": ["Learning", "Academy", "Edu"]}

# --------------------------------------------------------------------------
# Department structure
# --------------------------------------------------------------------------
SPECIALTIES = {
    "Engineering": ["Backend", "Frontend", "Platform", "Mobile", "QA"],
    "Data": ["Data Engineering", "Analytics", "Machine Learning"],
    "Product": ["Core Product", "Growth"],
    "Design": ["Product Design", "UX Research"],
    "Sales": ["Enterprise", "Mid-Market", "SMB", "Sales Development"],
    "Marketing": ["Demand Generation", "Product Marketing", "Content", "Brand"],
    "Customer Success": ["Support", "Onboarding", "Account Management"],
    "Finance": ["FP&A", "Accounting"],
    "People": ["Recruiting", "People Operations"],
    "Legal": ["Legal", "Compliance"],
    "Operations": ["Business Operations", "Supply Chain", "Facilities"],
    "IT": ["IT Support", "Corporate Systems"],
    "Security": ["Security Engineering", "GRC"],
}

# Exec role that owns each department: (role, weight) options. "own" means the
# department gets its own C-level exec when the company is big enough.
EXEC_OWNER = {
    "Engineering": [("CTO", 1.0)],
    "Data": [("CTO", 0.5), ("CDO", 0.25), ("CFO", 0.1), ("CEO", 0.15)],
    "Product": [("CPO", 0.6), ("CTO", 0.25), ("CEO", 0.15)],
    "Design": [("CPO", 0.6), ("CTO", 0.2), ("CMO", 0.2)],
    "Sales": [("CRO", 1.0)],
    "Marketing": [("CMO", 0.85), ("CRO", 0.15)],
    "Customer Success": [("CRO", 0.45), ("COO", 0.35), ("CCO", 0.2)],
    "Finance": [("CFO", 1.0)],
    "People": [("CHRO", 0.45), ("COO", 0.3), ("CEO", 0.25)],
    "Legal": [("GC", 0.6), ("CFO", 0.25), ("CEO", 0.15)],
    "Operations": [("COO", 1.0)],
    "IT": [("CIO", 0.4), ("CTO", 0.3), ("COO", 0.2), ("CFO", 0.1)],
    "Security": [("CISO", 0.4), ("CTO", 0.45), ("CIO", 0.15)],
}
EXEC_HOME = {"CTO": "Engineering", "CDO": "Data", "CPO": "Product", "CRO": "Sales", "CMO": "Marketing",
             "CCO": "Customer Success", "CFO": "Finance", "CHRO": "People", "GC": "Legal", "COO": "Operations",
             "CIO": "IT", "CISO": "Security"}
# Execs that only exist in bigger companies
EXEC_MIN_SIZE = {"CDO": 400, "CPO": 250, "CCO": 600, "CHRO": 400, "GC": 300, "CIO": 500, "CISO": 500, "COO": 150,
                 "CMO": 150, "CRO": 100, "CFO": 100, "CTO": 100}

# --------------------------------------------------------------------------
# Title vocabulary (generator side)
# --------------------------------------------------------------------------
CEO_TITLES = ["Chief Executive Officer", "CEO", "Co-Founder & CEO", "Founder and CEO", "CEO & Co-founder",
              "President & CEO", "Chief Executive"]
EXEC_TITLES = {
    "CTO": ["Chief Technology Officer", "CTO", "Co-founder & CTO", "Chief Technical Officer"],
    "CDO": ["Chief Data Officer", "CDO", "Chief Data & Analytics Officer"],
    "CPO": ["Chief Product Officer", "CPO"],
    "CRO": ["Chief Revenue Officer", "CRO", "Chief Commercial Officer", "Chief Sales Officer"],
    "CMO": ["Chief Marketing Officer", "CMO"],
    "CCO": ["Chief Customer Officer"],
    "CFO": ["Chief Financial Officer", "CFO", "Chief Finance Officer"],
    "CHRO": ["Chief People Officer", "CHRO", "Chief Human Resources Officer"],
    "GC": ["General Counsel", "Chief Legal Officer", "CLO"],
    "COO": ["Chief Operating Officer", "COO", "Chief Operations Officer"],
    "CIO": ["Chief Information Officer", "CIO"],
    "CISO": ["Chief Information Security Officer", "CISO", "Chief Security Officer"],
}
DEPT_NAMES = {  # department as it appears inside titles: canonical + variants
    "Engineering": ["Engineering", "Eng", "Software Engineering", "Technology"],
    "Data": ["Data", "Data & Analytics", "Data and AI", "Analytics"],
    "Product": ["Product", "Product Management"],
    "Design": ["Design", "Product Design", "UX"],
    "Sales": ["Sales", "Global Sales", "Revenue"],
    "Marketing": ["Marketing", "Mktg", "Growth Marketing"],
    "Customer Success": ["Customer Success", "Customer Experience", "CS", "Support"],
    "Finance": ["Finance", "Fin", "Finance & Accounting"],
    "People": ["People", "Human Resources", "HR", "Talent"],
    "Legal": ["Legal", "Legal & Compliance"],
    "Operations": ["Operations", "Ops", "Business Operations"],
    "IT": ["IT", "Information Technology", "Corporate IT"],
    "Security": ["Security", "Information Security", "InfoSec", "Cybersecurity"],
}
DEPT_FIELD_VARIANTS = {  # the HR-system "department" column
    "Engineering": ["Engineering", "Eng", "R&D", "Tech", "Product & Engineering"],
    "Data": ["Data", "Data & Analytics", "BI", "Data Science"],
    "Product": ["Product", "Product Mgmt", "R&D"],
    "Design": ["Design", "UX"],
    "Sales": ["Sales", "GTM", "Revenue", "Commercial"],
    "Marketing": ["Marketing", "Mktg", "GTM"],
    "Customer Success": ["Customer Success", "Support", "CX", "Customer Service"],
    "Finance": ["Finance", "Accounting", "FIN"],
    "People": ["People", "HR", "Human Resources", "Talent"],
    "Legal": ["Legal", "Compliance"],
    "Operations": ["Operations", "Ops", "Supply Chain"],
    "IT": ["IT", "Information Technology"],
    "Security": ["Security", "InfoSec", "IT"],
}
MANAGER_TITLES = {
    "Engineering": ["Engineering Manager", "Engineering Manager, {s}", "{s} Engineering Manager", "EM - {s}",
                    "Software Engineering Manager", "Mgr, Software Engineering", "Team Lead, {s}"],
    "Data": ["{s} Manager", "Manager, {s}", "Data Engineering Manager", "Analytics Manager", "Head of {s}", "Lead, {s}"],
    "Product": ["Group Product Manager", "Group Product Manager, {s}", "Product Lead, {s}"],
    "Design": ["Design Manager", "{s} Manager", "Design Lead"],
    "Sales": ["{s} Sales Manager", "Sales Manager", "Regional Sales Manager", "Sales Manager, {s}", "SDR Manager"],
    "Marketing": ["{s} Manager", "Marketing Manager", "Manager, {s}"],
    "Customer Success": ["{s} Manager", "Customer Success Manager Lead", "Support Manager", "Team Lead, {s}"],
    "Finance": ["{s} Manager", "Finance Manager", "Accounting Manager", "Controller"],
    "People": ["{s} Manager", "HR Manager", "Talent Acquisition Manager", "People Ops Manager"],
    "Legal": ["Legal Manager", "Compliance Manager", "Senior Counsel"],
    "Operations": ["{s} Manager", "Operations Manager", "Ops Manager, {s}", "Warehouse Manager", "Plant Manager"],
    "IT": ["IT Manager", "IT Support Manager", "Systems Manager"],
    "Security": ["Security Engineering Manager", "GRC Manager", "Security Manager"],
}
IC_ROLES = {  # specialty -> IC role nouns
    "Backend": ["Backend Engineer", "Software Engineer", "Back-end Developer", "Software Developer", "SWE"],
    "Frontend": ["Frontend Engineer", "Front-end Developer", "UI Engineer", "Software Engineer"],
    "Platform": ["Platform Engineer", "Site Reliability Engineer", "DevOps Engineer", "SRE", "Infrastructure Engineer"],
    "Mobile": ["iOS Engineer", "Android Engineer", "Mobile Developer", "Mobile Engineer"],
    "QA": ["QA Engineer", "Test Engineer", "SDET", "Quality Assurance Analyst"],
    "Data Engineering": ["Data Engineer", "Analytics Engineer", "ETL Developer", "Big Data Engineer"],
    "Analytics": ["Data Analyst", "BI Analyst", "Business Intelligence Developer", "Analyst"],
    "Machine Learning": ["Data Scientist", "Machine Learning Engineer", "ML Engineer", "Applied Scientist"],
    "Core Product": ["Product Manager", "Product Owner", "Technical Product Manager"],
    "Growth": ["Product Manager, Growth", "Growth Product Manager", "Product Analyst"],
    "Product Design": ["Product Designer", "UX Designer", "UI/UX Designer", "Visual Designer"],
    "UX Research": ["UX Researcher", "User Researcher", "Design Researcher"],
    "Enterprise": ["Enterprise Account Executive", "Account Executive", "Solutions Engineer", "Sales Engineer"],
    "Mid-Market": ["Mid-Market Account Executive", "Account Executive", "AE"],
    "SMB": ["SMB Account Executive", "Inside Sales Representative", "Account Executive"],
    "Sales Development": ["Sales Development Representative", "SDR", "BDR", "Business Development Representative"],
    "Demand Generation": ["Demand Generation Specialist", "Performance Marketer", "Marketing Specialist"],
    "Product Marketing": ["Product Marketing Manager", "PMM", "Product Marketer"],
    "Content": ["Content Writer", "Content Strategist", "Copywriter", "Social Media Manager"],
    "Brand": ["Brand Designer", "Brand Manager", "Graphic Designer"],
    "Support": ["Customer Support Specialist", "Support Engineer", "Customer Service Representative", "Support Agent"],
    "Onboarding": ["Onboarding Specialist", "Implementation Consultant", "Implementation Manager"],
    "Account Management": ["Customer Success Manager", "Account Manager", "CSM"],
    "FP&A": ["Financial Analyst", "FP&A Analyst", "Finance Business Partner"],
    "Accounting": ["Accountant", "Staff Accountant", "Accounts Payable Specialist", "Payroll Specialist"],
    "Recruiting": ["Recruiter", "Technical Recruiter", "Talent Acquisition Partner", "Sourcer"],
    "People Operations": ["HR Generalist", "People Partner", "HR Business Partner", "People Operations Specialist"],
    "Legal": ["Counsel", "Legal Counsel", "Paralegal", "Contracts Manager"],
    "Compliance": ["Compliance Analyst", "Compliance Officer", "Risk Analyst"],
    "Business Operations": ["Business Operations Analyst", "Operations Analyst", "Program Manager", "Project Manager"],
    "Supply Chain": ["Supply Chain Analyst", "Logistics Coordinator", "Warehouse Associate", "Procurement Specialist", "Buyer"],
    "Facilities": ["Facilities Coordinator", "Office Manager", "Workplace Specialist"],
    "IT Support": ["IT Support Specialist", "Help Desk Technician", "Desktop Support Engineer"],
    "Corporate Systems": ["Systems Administrator", "IT Systems Engineer", "Salesforce Administrator"],
    "Security Engineering": ["Security Engineer", "Application Security Engineer", "SOC Analyst"],
    "GRC": ["GRC Analyst", "Security Compliance Analyst", "Risk Analyst"],
}
IC_SENIORITY = [("intern", 0.03), ("junior", 0.17), ("mid", 0.43), ("senior", 0.27), ("staff", 0.07), ("lead", 0.03)]
SENIORITY_PREFIX = {
    "intern": ["{r} Intern", "Intern - {r}", "{r} (Intern)"],
    "junior": ["Junior {r}", "Jr. {r}", "Associate {r}", "{r} I"],
    "mid": ["{r}", "{r}", "{r} II"],
    "senior": ["Senior {r}", "Sr. {r}", "Sr {r}", "{r} III"],
    "staff": ["Staff {r}", "Principal {r}"],
    "lead": ["Lead {r}", "{r} Lead"],
}
# Held-out vocabulary: titles the parser was never written for (multilingual / quirky).
HELDOUT = {
    5: ["Software Craftsperson", "Code Ninja", "Desarrollador de Software", "Entwickler", "Member of Technical Staff",
        "Analista de Datos", "Ejecutivo de Ventas", "Customer Hero", "Growth Hacker", "Vertriebsmitarbeiter"],
    4: ["Jefe de Equipo", "Teamleiter", "Responsable de Ventas", "Squad Lead"],
    3: ["Directora de Ventas", "Bereichsleiter", "Responsable Marketing"],
    2: ["Vicepresidente de Ventas", "Leiter Vertrieb"],
}
JUNK = [" | We're hiring!", " @ {company}", " 🚀", " - Open to work", " | ex-Google", " (she/her)", " (he/him)"]


@dataclass
class Person:
    pid: str
    level: int                      # 0 CEO, 1 exec, 2 VP, 3 director, 4 manager, 5 IC
    dept: str | None
    specialty: str | None = None
    exec_role: str | None = None
    seniority: str = "mid"
    manager: str | None = None
    location: str | None = None
    is_contractor: bool = False
    is_assistant: bool = False
    reports: list = field(default_factory=list)


def _wchoice(rng: random.Random, items: dict | list):
    if isinstance(items, dict):
        keys, weights = list(items.keys()), list(items.values())
    else:
        keys, weights = [k for k, _ in items], [w for _, w in items]
    return rng.choices(keys, weights=weights, k=1)[0]


class CompanyBuilder:
    def __init__(self, rng: random.Random, company_id: str, size: int, industry: str, country: str):
        self.rng, self.cid, self.size, self.industry, self.country = rng, company_id, size, industry, country
        self.people: dict[str, Person] = {}
        self.n = 0
        locs = COUNTRIES[country][1]
        n_offices = 1 if size < 200 else (2 if size < 500 else min(4, len(locs)))
        self.offices = rng.sample(locs, n_offices)
        self.hq = self.offices[0]

    def _new(self, **kw) -> Person:
        self.n += 1
        p = Person(pid=f"{self.cid}-P{self.n:05d}", **kw)
        self.people[p.pid] = p
        return p

    def _attach(self, child: Person, parent: Person):
        child.manager = parent.pid
        parent.reports.append(child.pid)

    def _loc(self, near: str | None = None, stick: float = 0.75) -> str:
        if near and self.rng.random() < stick:
            return near
        return self.rng.choice(self.offices)

    def build(self) -> dict[str, Person]:
        rng = self.rng
        ceo = self._new(level=0, dept=None, exec_role="CEO", location=self.hq)
        weights = INDUSTRIES[self.industry]
        depts = [d for d in weights if self.size >= 150 or d not in ("Security", "IT", "Legal") or rng.random() < 0.4]
        # Which exec owns each department
        owner = {}
        for d in depts:
            opts = [(r, w) for r, w in EXEC_OWNER[d] if r == "CEO" or self.size >= EXEC_MIN_SIZE.get(r, 0)]
            if not opts:
                opts = [("CEO", 1.0)]
            owner[d] = _wchoice(rng, opts)
        exec_roles = sorted({r for r in owner.values() if r != "CEO"})
        execs = {}
        for r in exec_roles:
            home = EXEC_HOME[r]
            p = self._new(level=1, dept=home, exec_role=r, location=self._loc(self.hq, 0.85))
            self._attach(p, ceo)
            execs[r] = p
        # Executive assistant / chief of staff
        n_assist = 0
        if self.size >= 300 and rng.random() < 0.7:
            ea = self._new(level=5, dept=None, exec_role=None, location=self.hq, is_assistant=True)
            self._attach(ea, ceo)
            n_assist = 1
        remaining = self.size - 1 - len(execs) - n_assist
        tot_w = sum(weights[d] for d in depts)
        alloc = {d: max(2, int(round(remaining * weights[d] / tot_w))) for d in depts}
        # fix rounding so total == size
        diff = remaining - sum(alloc.values())
        big = max(alloc, key=alloc.get)
        alloc[big] += diff
        for d in depts:
            parent = execs.get(owner[d], ceo) if owner[d] != "CEO" else ceo
            own_exec = parent.exec_role != "CEO" and EXEC_HOME.get(parent.exec_role) == d
            self._build_dept(d, alloc[d], parent, own_exec)
        return self.people

    def _build_dept(self, dept: str, n: int, parent: Person, own_exec: bool):
        rng = self.rng
        specs = SPECIALTIES[dept][:]
        rng.shuffle(specs)
        n_specs = max(1, min(len(specs), n // 8 + 1))
        specs = specs[:n_specs]
        has_vp = n >= 45 and self.size >= 300
        rem = n - int(has_vp)
        n_dir = 0 if rem < 18 else max(1, int(round(rem / rng.uniform(30, 55))))
        head_is_director = n_dir == 0 and not has_vp and n >= 7
        top_nodes: list[Person] = []
        anchor = parent
        if has_vp:
            vp = self._new(level=2, dept=dept, location=self._loc(parent.location, 0.8))
            self._attach(vp, parent)
            anchor = vp
        if head_is_director:
            n_dir = 1
        rem -= n_dir
        directors = []
        dir_specs = [specs[i::n_dir] for i in range(n_dir)] if n_dir else []
        for i in range(n_dir):
            d = self._new(level=3, dept=dept, location=self._loc(anchor.location, 0.7))
            d.specialty = dir_specs[i][0] if (n_dir > 1 and len(dir_specs[i]) == 1) else None
            d._owned = dir_specs[i] or specs  # type: ignore[attr-defined]
            self._attach(d, anchor)
            directors.append(d)
        # managers
        span = rng.uniform(5, 9)
        n_mgr = 0 if (rem < 10 and n_dir) or rem < 4 else max(1, int(round(rem / (span + 1))))
        rem -= n_mgr
        managers = []
        for i in range(n_mgr):
            if directors:
                d = directors[i % len(directors)]
                spec = d._owned[(i // len(directors)) % len(d._owned)]  # type: ignore[attr-defined]
                boss = d
            else:
                spec = specs[i % len(specs)]
                boss = anchor
            m = self._new(level=4, dept=dept, specialty=spec, location=self._loc(boss.location, 0.6))
            self._attach(m, boss)
            managers.append(m)
        leads = managers or directors or [anchor]
        # uneven spans: weights per manager
        caps = [rng.uniform(0.6, 1.4) for _ in leads]
        for _ in range(max(0, rem)):
            boss = rng.choices(leads, weights=caps, k=1)[0]
            spec = boss.specialty or (rng.choice(getattr(boss, "_owned", specs)) if boss.level >= 3 else rng.choice(specs))
            sen = _wchoice(rng, IC_SENIORITY)
            ic = self._new(level=5, dept=dept, specialty=spec, seniority=sen, location=self._loc(boss.location),
                           is_contractor=rng.random() < 0.04)
            self._attach(ic, boss)


# --------------------------------------------------------------------------
# Mess: turn a true person into a messy record
# --------------------------------------------------------------------------
def _typo(rng: random.Random, s: str) -> str:
    if len(s) < 5:
        return s
    i = rng.randrange(1, len(s) - 1)
    op = rng.random()
    if op < 0.33:
        return s[:i] + s[i + 1:]                 # drop
    if op < 0.66:
        return s[:i] + s[i + 1] + s[i] + s[i + 2:]  # swap
    return s[:i] + s[i] + s[i:]                 # double


def make_title(rng: random.Random, p: Person, noise: float, company_name: str) -> tuple[str | None, bool]:
    """Return (title, used_heldout)."""
    heldout = False
    if p.level in HELDOUT and rng.random() < 0.02 * noise:
        t, heldout = rng.choice(HELDOUT[p.level]), True
    elif p.level == 0:
        t = rng.choice(CEO_TITLES) if rng.random() < 0.6 * noise else "Chief Executive Officer"
    elif p.level == 1:
        opts = EXEC_TITLES[p.exec_role]
        t = rng.choice(opts) if rng.random() < 0.6 * noise else opts[0]
    elif p.is_assistant:
        t = rng.choice(["Executive Assistant to the CEO", "Chief of Staff", "Executive Assistant", "EA to CEO"])
    elif p.level == 2:
        dn = rng.choice(DEPT_NAMES[p.dept]) if rng.random() < 0.5 * noise else DEPT_NAMES[p.dept][0]
        pat = rng.choice(["VP {d}", "Vice President of {d}", "VP, {d}", "SVP {d}", "Vice-President {d}",
                          "Head of {d}", "VP of {d}"]) if rng.random() < 0.7 * noise else "Vice President of {d}"
        t = pat.format(d=dn)
    elif p.level == 3:
        dn = rng.choice(DEPT_NAMES[p.dept]) if rng.random() < 0.5 * noise else DEPT_NAMES[p.dept][0]
        if p.specialty and rng.random() < 0.7:
            pat = rng.choice(["Director, {s}", "{s} Director", "Director of {s}", "Head of {s}", "Sr. Director, {s}"])
            t = pat.format(s=p.specialty)
        else:
            pat = rng.choice(["Director of {d}", "Dir. {d}", "Head of {d}", "{d} Director", "Senior Director, {d}"]) \
                if rng.random() < 0.7 * noise else "Director of {d}"
            t = pat.format(d=dn)
    elif p.level == 4:
        pats = MANAGER_TITLES[p.dept]
        keep_spec = rng.random() > (0.25 + 0.1 * noise)
        cand = [x for x in pats if ("{s}" in x) == keep_spec] or pats
        t = rng.choice(cand).format(s=p.specialty or "")
    else:
        role = rng.choice(IC_ROLES[p.specialty])
        t = rng.choice(SENIORITY_PREFIX[p.seniority]).format(r=role)
    if p.is_contractor:
        t = rng.choice(["{t} (Contract)", "Contractor - {t}", "{t} - Contractor", "{t} [contract]"]).format(t=t)
    # abbreviations
    if rng.random() < 0.15 * noise:
        for a, b in [("Senior", "Sr."), ("Manager", "Mgr"), ("Director", "Dir."), ("Engineering", "Eng."),
                     ("Vice President", "VP"), ("Operations", "Ops"), ("Marketing", "Mktg"), ("Development", "Dev")]:
            if a in t and rng.random() < 0.6:
                t = t.replace(a, b)
    if rng.random() < 0.04 * noise:
        t = _typo(rng, t)
    r = rng.random()
    if r < 0.03 * noise:
        t = t.upper()
    elif r < 0.07 * noise:
        t = t.lower()
    if rng.random() < 0.03 * noise:
        t = t + rng.choice(JUNK).format(company=company_name)
    if rng.random() < 0.015 * noise:
        return None, heldout
    return t, heldout


def generate(n_companies: int = 520, seed: int = 42) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Return (companies, people, truth) DataFrames."""
    rng = random.Random(seed)
    fakers = {c: Faker(loc) for c, (loc, _) in COUNTRIES.items()}
    for i, f in enumerate(fakers.values()):
        f.seed_instance(seed + i)
    companies, people_rows, truth_rows = [], [], []
    used_names = set()
    for ci in range(n_companies):
        cid = f"C{ci:04d}"
        industry = rng.choice(list(INDUSTRIES))
        country = _wchoice(rng, COUNTRY_WEIGHTS)
        lo, hi = _wchoice(rng, [(b, w) for b, w in SIZE_BUCKETS])
        size = rng.randint(lo, hi)
        noise_name = _wchoice(rng, NOISE_WEIGHTS)
        noise = NOISE_LEVELS[noise_name]
        while True:
            name = f"{rng.choice(COMPANY_WORDS)} {rng.choice(COMPANY_SUFFIX[industry])}"
            if name not in used_names or len(used_names) > 800:
                break
            name = f"{name} {rng.choice(['Group', 'Co', 'Inc', 'Global', 'Partners'])}"
            if name not in used_names:
                break
        used_names.add(name)
        builder = CompanyBuilder(rng, cid, size, industry, country)
        tree = builder.build()
        fk = fakers[country]
        size_bucket = "100-199" if size < 200 else "200-499" if size < 500 else "500-999" if size < 1000 else "1000+"
        companies.append(dict(company_id=cid, company_name=name, industry=industry, country=country,
                              n_employees=len(tree), size_bucket=size_bucket, noise_level=noise_name))
        recs = []
        for p in tree.values():
            title, heldout = make_title(rng, p, noise, name)
            dept_true = p.dept if not p.is_assistant else None
            if dept_true and rng.random() > min(0.85, 0.22 * noise):
                dept_field = rng.choice(DEPT_FIELD_VARIANTS[dept_true]) if rng.random() < 0.5 * noise else dept_true
                if rng.random() < 0.025 * noise:   # HR system has it wrong
                    dept_field = rng.choice(list(DEPT_FIELD_VARIANTS))
            else:
                dept_field = None
            loc = p.location if rng.random() > 0.12 * noise else None
            stale_profile = rng.random() < 0.08
            updated = TODAY - timedelta(days=rng.randint(700, 1800) if stale_profile else rng.randint(0, 420))
            if rng.random() < 0.15 * noise:
                updated = None
            rec = dict(person_id=p.pid, company_id=cid, full_name=fk.name(), title=title, department=dept_field,
                       location=loc, last_updated=updated)
            recs.append(rec)
            truth_rows.append(dict(person_id=p.pid, company_id=cid, manager_id=p.manager, true_level=p.level,
                                   true_dept=p.dept, true_specialty=p.specialty, exec_role=p.exec_role,
                                   is_contractor=p.is_contractor, is_stale=False, duplicate_of=None,
                                   heldout_title=heldout, n_direct_reports=len(p.reports)))
        # Stale records: people who left. Plausible titles, not in the tree: no true manager.
        n_stale = int(round(len(tree) * rng.uniform(0.01, 0.04)))
        ic_pool = [p for p in tree.values() if p.level >= 4]
        for _ in range(n_stale):
            src = rng.choice(ic_pool)
            builder.n += 1
            ghost = Person(pid=f"{cid}-P{builder.n:05d}", level=src.level, dept=src.dept, specialty=src.specialty,
                           seniority=src.seniority, location=src.location)
            title, _ = make_title(rng, ghost, noise, name)
            # most leavers have old records, but not all
            updated = TODAY - timedelta(days=rng.randint(600, 2000) if rng.random() < 0.7 else rng.randint(0, 400))
            recs.append(dict(person_id=ghost.pid, company_id=cid, full_name=fk.name(), title=title,
                             department=ghost.dept if rng.random() < 0.6 else None, location=ghost.location,
                             last_updated=updated))
            truth_rows.append(dict(person_id=ghost.pid, company_id=cid, manager_id=None, true_level=ghost.level,
                                   true_dept=ghost.dept, true_specialty=ghost.specialty, exec_role=None,
                                   is_contractor=False, is_stale=True, duplicate_of=None, heldout_title=False,
                                   n_direct_reports=0))
        # Duplicates: same person scraped twice with a slightly different title.
        n_dup = int(round(len(tree) * 0.01 * noise))
        for _ in range(n_dup):
            src_rec = rng.choice(recs[: len(tree)])
            src_truth = next(t for t in truth_rows[-(len(recs)):] if t["person_id"] == src_rec["person_id"])
            builder.n += 1
            dup_id = f"{cid}-P{builder.n:05d}"
            t = src_rec["title"]
            t2 = (t.lower() if rng.random() < 0.5 else _typo(rng, t)) if t else None
            recs.append(dict(src_rec, person_id=dup_id, title=t2,
                             department=src_rec["department"] if rng.random() < 0.5 else None))
            truth_rows.append(dict(src_truth, person_id=dup_id, duplicate_of=src_rec["person_id"],
                                   n_direct_reports=0))
        rng.shuffle(recs)   # the flat list carries no order signal
        people_rows.extend(recs)
    people = pd.DataFrame(people_rows)
    people["last_updated"] = pd.to_datetime(people["last_updated"])
    return pd.DataFrame(companies), people, pd.DataFrame(truth_rows)
