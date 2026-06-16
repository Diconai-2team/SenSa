import numpy as np
p = np.fromfile("pmod.bin", dtype=np.int64)
N = len(p)-1
n = np.arange(N+1, dtype=np.int64)
primes = [13,17,19,23,29,31,37,41]
def inv24(ell): return pow(24,-1,ell)
def qrset(ell): return set((x*x)%ell for x in range(1,ell))

print("========== CONTROLS DONE PROPERLY (N=5M, per-prime favored-side) ==========")
print(f"{'ell':>3} {'r0':>3} {'Delta(QR0-NQR)':>15} {'|Delta|':>8} {'Z(Delta)':>9} {'favored':>8} {'topK==QR0?':>11}")
rows=[]
for ell in primes:
    r0=inv24(ell); QR=qrset(ell); div=(p%ell==0)
    branch=(n%ell==r0)&(n>=1)
    t=((24*n-1)//ell)%ell
    isqr0=np.isin(t,list(QR|{0}))
    a=branch&isqr0; b=branch&(~isqr0)
    ra,rb=div[a].mean(),div[b].mean()
    Ba,Bb=ra*ell,rb*ell
    se=ell*np.sqrt(ra*(1-ra)/a.sum()+rb*(1-rb)/b.sum())
    Z=(Ba-Bb)/se
    # rank classes, is favored side = QR0 ?
    Bc=np.array([div[branch&(t==tc)].mean()*ell for tc in range(ell)])
    qr0idx=sorted(QR|{0}); k=len(qr0idx)
    topk=set(np.argsort(-Bc)[:k].tolist())
    favored = "QR0" if Ba>Bb else "NQR"
    rows.append((ell,Ba-Bb,Z))
    print(f"{ell:>3} {r0:>3} {Ba-Bb:>+15.4f} {abs(Ba-Bb):>8.4f} {Z:>9.2f} {favored:>8} {str(topk==set(qr0idx)):>11}")

print("\nInterpretation: 13's |Delta| vs controls")
d13=abs(rows[0][1]); others=[abs(r[1]) for r in rows[1:]]
print(f"  |Delta_13|={d13:.4f}   max control |Delta|={max(others):.4f} (ell={primes[1:][int(np.argmax(others))]})   ratio={d13/max(others):.1f}x")

print("\n========== DECISIVE: WINDOWED (LOCAL) contrast for ell=13 ==========")
print("Cumulative is dominated by small n. Disjoint windows reveal if effect lives at small n.")
ell=13; r0=6; QR=qrset(13); div=(p%13==0)
t=((24*n-1)//13)%13; isqr0=np.isin(t,list(QR|{0})); branch=(n%13==r0)&(n>=1)
wins=[(1,1_000_000),(1_000_000,2_000_000),(2_000_000,3_000_000),(3_000_000,4_000_000),(4_000_000,5_000_000)]
print(f"{'window':>20} {'B_QR0':>8} {'B_NQR':>8} {'Delta':>8} {'Z':>7}")
for lo,hi in wins:
    w=(n>=lo)&(n<hi)
    a=branch&w&isqr0; b=branch&w&(~isqr0)
    ra,rb=div[a].mean(),div[b].mean()
    se=13*np.sqrt(ra*(1-ra)/a.sum()+rb*(1-rb)/b.sum())
    print(f"{str((lo,hi)):>20} {ra*13:>8.4f} {rb*13:>8.4f} {(ra-rb)*13:>+8.4f} {((ra-rb)*13)/se:>7.2f}")

print("\n========== DECAY FIT for cumulative Delta_13 ==========")
Ns=np.array([1e6,2e6,3e6,4e6,5e6])
D=np.array([0.3157,0.2740,0.2407,0.2249,0.2099])
# power law D = c*N^-a  -> log D = log c - a log N
A=np.polyfit(np.log(Ns),np.log(D),1)
a=-A[0]; c=np.exp(A[1])
print(f"power-law fit: Delta ~ {c:.3f} * N^(-{a:.3f})")
for NN in [1e7,2e7,5e7,1e8,1e9,1e12]:
    print(f"   predict Delta_13({NN:.0e}) = {c*NN**(-a):.4f}")
# compare with user's reported 10M,20M
print("   user-reported actual: 10M->0.183, 20M->0.154")
print(f"   power-law predicts:   10M->{c*1e7**-a:.4f}, 20M->{c*2e7**-a:.4f}")
