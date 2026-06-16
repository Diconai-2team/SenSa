#!/usr/bin/env python3
"""파일별 git blame 작성자 라인 집계.
출력: docs/_authorship/blame_by_file.csv  (file, author_email, lines)
      docs/_authorship/blame_summary.csv  (author_email, lines, pct)
"""
import subprocess, csv, os, collections, sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(ROOT)

# 작성자 이메일 → 표시 이름 정규화
ALIAS = {
    "joon7575@gmail.com": "나(4M/이재호)",
    "kapol2990@gmail.com": "normalframe1094",
    "js6088@naver.com": "normaluser111",
    "shj4902@gmail.com": "서호준",
    "kingnh0328@gmail.com": "김나현",
}

def tracked_files():
    out = subprocess.check_output(
        ["git", "ls-files", "*.py", "*.html", "*.js", "*.css"], text=True
    ).splitlines()
    skip = ("migrations/", "__pycache__", ".min.js", ".min.css")
    return [f for f in out if not any(s in f for s in skip)]

def blame_file(path):
    """이메일 → 라인수"""
    try:
        out = subprocess.check_output(
            ["git", "blame", "--line-porcelain", "HEAD", "--", path],
            text=True, stderr=subprocess.DEVNULL,
        )
    except subprocess.CalledProcessError:
        return {}
    counts = collections.Counter()
    for line in out.splitlines():
        if line.startswith("author-mail "):
            email = line[len("author-mail "):].strip("<>")
            counts[email] += 1
    return counts

def main():
    files = tracked_files()
    per_file = []
    total = collections.Counter()
    for i, f in enumerate(files, 1):
        c = blame_file(f)
        for email, n in c.items():
            per_file.append((f, ALIAS.get(email, email), email, n))
            total[email] += n
        if i % 25 == 0:
            print(f"  ...{i}/{len(files)}", file=sys.stderr)

    outdir = os.path.join(ROOT, "docs", "_authorship")
    with open(os.path.join(outdir, "blame_by_file.csv"), "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["file", "author", "author_email", "lines"])
        w.writerows(sorted(per_file))

    grand = sum(total.values())
    with open(os.path.join(outdir, "blame_summary.csv"), "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["author", "author_email", "lines", "pct"])
        for email, n in total.most_common():
            w.writerow([ALIAS.get(email, email), email, n, f"{100*n/grand:.1f}"])

    print(f"\n총 {len(files)}개 파일, {grand:,} 라인")
    for email, n in total.most_common():
        print(f"  {ALIAS.get(email, email):20s} {n:7,} ({100*n/grand:4.1f}%)")

if __name__ == "__main__":
    main()
