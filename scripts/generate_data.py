"""Generate the synthetic dataset. Usage: python scripts/generate_data.py [--companies 520] [--seed 42]"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from orgchart.generator import generate  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--companies", type=int, default=520)
ap.add_argument("--seed", type=int, default=42)
ap.add_argument("--out", default="data")
a = ap.parse_args()
out = Path(a.out)
out.mkdir(parents=True, exist_ok=True)
companies, people, truth = generate(a.companies, a.seed)
companies.to_parquet(out / "companies.parquet", index=False)
people.to_parquet(out / "people.parquet", index=False)
truth.to_parquet(out / "truth.parquet", index=False)
people.head(2000).to_csv(out / "sample_people.csv", index=False)
print(f"{len(companies)} companies, {len(people)} records, min company size {companies.n_employees.min()}")
