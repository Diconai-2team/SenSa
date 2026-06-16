import numpy as np
M = 131710070791
p = np.fromfile("pmod.bin", dtype=np.int64)
N = len(p)-1
print("loaded p(n) for n=0..%d"%N)

# --- sanity: small partition values (p(n) < M so residue == true value) ---
known = [1,1,2,3,5,7,11,15,22,30,42,56,77,101,135]
ok = all(int(p[i])==known[i] for i in range(len(known)))
print("small-value check p(0..14):", "PASS" if ok else "FAIL", [int(p[i]) for i in range(11)])
# p(100)=190569292
print("p(100) check:", int(p[100]), "expected 190569292 ->", int(p[100])==190569292)

n = np.arange(N+1, dtype=np.int64)
primes = [13,17,19,23,29,31,37,41]
def inv24(ell):
    return pow(24, -1, ell)
def qrset(ell):
    return set((x*x)%ell for x in range(1,ell))

cutoffs = [1_000_000,2_000_000,3_000_000,4_000_000,5_000_000]

print("\n========== GLOBAL NORMALIZATION CHECK (ell=13) ==========")
div13 = (p % 13 == 0)
for N0 in cutoffs:
    mask = n<=N0
    glob = div13[1:N0+1].mean()
    print(f"N={N0:>9}: global rate(13|p(n)) = {glob:.5f}   (1/13={1/13:.5f})   B_global={glob*13:.4f}")
# per-branch (all 13 residues mod 13), at 5M
print("\nPer-branch rate at N=%d (residue mod 13 : B):"%N)
for r in range(13):
    m = (n%13==r)&(n>=1)
    rate = div13[m].mean()
    print(f"  n=={r:2d} mod13 : B={rate*13:.4f}")

print("\n========== VERIFY mod-169 cluster (ell=13, threshold 1.2) ==========")
cluster_claim = {19,58,71,84,97,136,162}
for N0 in [1_000_000,3_000_000,5_000_000]:
    sl = slice(1,N0+1)
    nn = n[sl]; dd = div13[sl]
    res = nn % 169
    # rate per residue
    cnt = np.bincount(res, minlength=169)
    div = np.bincount(res, weights=dd, minlength=169)
    B = np.where(cnt>0, div/cnt*13, 0)
    cl = set(np.where(B>=1.2)[0].tolist())
    print(f"N={N0:>9}: cluster(B>=1.2) = {sorted(cl)}  matches claim: {cl==cluster_claim}")

print("\n========== ell=13 QR/0 vs NQR contrast (square class of (24n-1)/13 mod 13) ==========")
ell=13; r0=inv24(ell); QR=qrset(ell)
print("24^-1 mod 13 =", r0, " QR set mod13 =", sorted(QR))
branch = (n%ell==r0)&(n>=1)
t = ((24*n-1)//ell) % ell   # square-class index
is_qr0 = np.isin(t, list(QR|{0}))
for N0 in cutoffs:
    up = n<=N0
    a = branch&up&is_qr0
    b = branch&up&(~is_qr0)
    ra, rb = div13[a].mean(), div13[b].mean()
    Ba, Bb = ra*ell, rb*ell
    # SE of contrast in B units
    na,nb = a.sum(), b.sum()
    se = ell*np.sqrt(ra*(1-ra)/na + rb*(1-rb)/nb)
    Z = (Ba-Bb)/se
    print(f"N={N0:>9}: B_QR0={Ba:.4f} (n={na})  B_NQR={Bb:.4f} (n={nb})  Delta={Ba-Bb:+.4f}  Z(Delta)={Z:.2f}")

print("\n========== THRESHOLD-FREE: rank all 13 t-classes by B (N=5M) ==========")
up = n<=5_000_000
order=[]
for tc in range(13):
    m = branch&up&(t==tc)
    B = div13[m].mean()*ell
    order.append((B,tc,tc in QR, tc==0))
order.sort(reverse=True)
for B,tc,isqr,isz in order:
    tag = "QR" if isqr else ("ZERO" if isz else "NQR")
    print(f"  t={tc:2d} [{tag:4}] B={B:.4f}")
