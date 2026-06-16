#!/usr/bin/env python3
"""모든 브랜치에서 각 작성자가 '추가한' 라인을 파일 basename 단위로 집계.
통합(squash) 이전 원작성 기여를 포착하기 위함.
출력: docs/_authorship/author_evidence.csv  (basename, author, lines_added, n_commits)
"""
import subprocess, csv, os, collections

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(ROOT)

ALIAS = {
    "joon7575@gmail.com": "나(이재호)",
    "kapol2990@gmail.com": "csw",
    "js6088@naver.com": "normaluser111",
    "shj4902@gmail.com": "서호준",
    "kingnh0328@gmail.com": "김나현",
}

# author email per basename -> lines, commits
lines = collections.defaultdict(lambda: collections.Counter())
commits = collections.defaultdict(lambda: collections.Counter())

raw = subprocess.check_output(
    ["git", "log", "--all", "--no-merges", "--pretty=@%ae", "--numstat",
     "--", "*.py", "*.html", "*.js", "*.css"],
    text=True, stderr=subprocess.DEVNULL,
)

cur = None
seen_in_commit = set()
for line in raw.splitlines():
    if line.startswith("@"):
        cur = line[1:]
        seen_in_commit = set()
        continue
    if not line or not line[0].isdigit():
        continue
    parts = line.split("\t")
    if len(parts) != 3:
        continue
    added, _, path = parts
    if "migrations/" in path or "__pycache__" in path:
        continue
    if added == "-":
        continue
    base = os.path.basename(path)
    author = ALIAS.get(cur, cur)
    lines[base][author] += int(added)
    if base not in seen_in_commit:
        commits[base][author] += 1
        seen_in_commit.add(base)

rows = []
for base in sorted(lines):
    for author, n in lines[base].items():
        rows.append((base, author, n, commits[base][author]))

outdir = os.path.join(ROOT, "docs", "_authorship")
with open(os.path.join(outdir, "author_evidence.csv"), "w", newline="") as fh:
    w = csv.writer(fh)
    w.writerow(["basename", "author", "lines_added", "n_commits"])
    w.writerows(rows)

# 콘솔: 작성자별 '본인이 1순위(최다 추가)인' 파일 수
primary = collections.Counter()
for base in lines:
    top = lines[base].most_common(1)[0][0]
    primary[top] += 1
print(f"파일(basename) {len(lines)}개 / 작성자 {len(set(a for b in lines.values() for a in b))}명")
print("\n[파일 1순위 작성자 기준] 누가 몇 개 파일을 주도했나:")
for author, n in primary.most_common():
    print(f"  {author:14s} {n:4d} 파일")
