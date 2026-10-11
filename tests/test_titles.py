import pytest

from orgchart.titles import parse_title


@pytest.mark.parametrize("title,level,dept", [
    ("Chief Executive Officer", 0, None),
    ("Co-Founder & CEO", 0, None),
    ("CTO", 1, "Engineering"),
    ("Chief People Officer", 1, "People"),
    ("VP Eng", 2, "Engineering"),
    ("Vice President of Sales", 2, "Sales"),
    ("Director of Customer Success", 3, "Customer Success"),
    ("Engineering Manager, Platform", 4, "Engineering"),
    ("EM - Backend", 4, "Engineering"),
    ("Group Product Manager", 4, "Product"),
    ("Sr. Data Engineer", 5, "Data"),
    ("Product Manager", 5, "Product"),          # IC despite the word "manager"
    ("Customer Success Manager", 5, "Customer Success"),
    ("Program Manager Lead", 5, "Operations"),  # senior IC, not a people manager
    ("Solutions Engineer", 5, "Sales"),         # not Engineering
    ("Security Engineer", 5, "Security"),
])
def test_levels_and_departments(title, level, dept):
    p = parse_title(title)
    assert p.level == level
    assert p.dept == dept


def test_typo_and_case_are_repaired():
    p = parse_title("ENGINERING MANAGER, PLATFROM")
    assert p.level == 4 and p.dept == "Engineering"


def test_junk_and_contractor_flags():
    p = parse_title("Sr Enterprise Account Executive [contract] | We're hiring!")
    assert p.level == 5 and p.dept == "Sales" and p.specialty == "Enterprise" and p.is_contractor
    assert p.seniority == "senior"


def test_department_field_used_when_title_is_vague():
    p = parse_title("Analyst", "Data & Analytics")
    assert p.dept == "Data"
    q = parse_title("Software Engineer", "R&D")
    assert q.dept == "Engineering" and q.dept_conf > 0.9


def test_missing_and_unknown_titles_do_not_guess():
    assert parse_title(None).level is None
    assert parse_title("Code Ninja").level is None   # held-out vocabulary: we abstain
