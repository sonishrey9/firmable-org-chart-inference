from orgchart.generator import generate


def test_dataset_shape_and_truth():
    companies, people, truth = generate(12, seed=7)
    assert len(companies) == 12
    assert companies.n_employees.min() >= 100
    assert set(people.person_id) == set(truth.person_id)
    assert "manager_id" not in people.columns           # answer key is separate
    ids = set(truth.person_id)
    live = truth[~truth.is_stale & truth.duplicate_of.isna()]
    # every live person except one CEO per company has a manager inside the same company
    roots = live[live.manager_id.isna()]
    assert (roots.groupby("company_id").size() == 1).all()
    assert live.manager_id.dropna().isin(ids).all()
    # stale records have no true manager; the mess is there
    assert truth[truth.is_stale].manager_id.isna().all()
    assert people.title.isna().any() and people.department.isna().any()


def test_trees_are_acyclic():
    _, _, truth = generate(5, seed=3)
    parent = dict(zip(truth.person_id, truth.manager_id))
    for pid in truth.person_id:
        seen, cur = set(), pid
        while isinstance(cur, str):
            assert cur not in seen
            seen.add(cur)
            cur = parent.get(cur)


def test_deterministic():
    a = generate(3, seed=11)[1]
    b = generate(3, seed=11)[1]
    assert a.equals(b)
