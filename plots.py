import numpy as np, matplotlib
matplotlib.use("Agg"); import matplotlib.pyplot as plt
p=np.fromfile("pmod.bin",dtype=np.int64); N=len(p)-1; n=np.arange(N+1,dtype=np.int64)
def qr(e): return set((x*x)%e for x in range(1,e))
def i24(e): return pow(24,-1,e)
primes=[13,17,19,23,29,31,37,41]

# ---- decay data (my 1-5M) ----
ell=13;QR=qr(13);div13=(p%13==0);t=((24*n-1)//13)%13;isq=np.isin(t,list(QR|{0}));br=(n%13==6)&(n>=1)
cut=[1e6,2e6,3e6,4e6,5e6]; Dc=[]
for c in cut:
    u=n<=c; a=br&u&isq; b=br&u&(~isq); Dc.append((div13[a].mean()-div13[b].mean())*13)
Dc=np.array(Dc); cut=np.array(cut)
A=np.polyfit(np.log(cut),np.log(Dc),1); aa=-A[0]; cc=np.exp(A[1])
xx=np.logspace(6,9,200)

fig,ax=plt.subplots(figsize=(7,4.5))
ax.plot(xx,cc*xx**-aa,'-',color="#888",label=f"power-law fit  $\\Delta\\sim{cc:.1f}\\,N^{{-{aa:.3f}}}$ (→0)")
ax.plot(cut,Dc,'o',color="#c0392b",ms=8,label="this work (independent, 1–5M)")
ax.plot([1e7,2e7],[0.183,0.154],'s',color="#2c70b8",ms=8,label="user's data (10M, 20M)")
ax.set_xscale("log"); ax.set_xlabel("N"); ax.set_ylabel("$\\Delta_{13}=B_{QR/0}-B_{NQR}$")
ax.axhline(0,color="k",lw=.6); ax.set_ylim(0,0.36)
ax.set_title("Square-class contrast decays toward 0 as a slow power law\n(fit on 1–5M predicts 10M/20M)")
ax.legend(fontsize=8); ax.grid(alpha=.3); fig.tight_layout(); fig.savefig("fig_decay.png",dpi=130)

# ---- windowed local contrast ----
wins=[(1,1e6),(1e6,2e6),(2e6,3e6),(3e6,4e6),(4e6,5e6)]; lab=[];dw=[];zw=[]
for lo,hi in wins:
    w=(n>=lo)&(n<hi);a=br&w&isq;b=br&w&(~isq)
    ra,rb=div13[a].mean(),div13[b].mean();se=13*np.sqrt(ra*(1-ra)/a.sum()+rb*(1-rb)/b.sum())
    dw.append((ra-rb)*13);zw.append((ra-rb)*13/se);lab.append(f"{int(lo//1e6)}–{int(hi//1e6)}M")
fig,ax=plt.subplots(figsize=(7,4.5))
bars=ax.bar(lab,dw,color="#c0392b",alpha=.8)
for bar,z in zip(bars,zw): ax.text(bar.get_x()+bar.get_width()/2,bar.get_height()+.005,f"Z={z:.1f}",ha="center",fontsize=8)
ax.set_ylabel("local $\\Delta_{13}$ in window"); ax.set_xlabel("disjoint window of n")
ax.set_title("Effect is NOT only at small n: local contrast still Δ≈0.15, Z≈5.7 at 4–5M")
ax.grid(alpha=.3,axis="y"); fig.tight_layout(); fig.savefig("fig_windows.png",dpi=130)

# ---- controls ----
names=[];delt=[];zs=[]
for e in primes:
    Q=qr(e);d=(p%e==0);b0=(n%e==i24(e))&(n>=1);tt=((24*n-1)//e)%e;iq=np.isin(tt,list(Q|{0}))
    a=b0&iq;b=b0&(~iq);ra,rb=d[a].mean(),d[b].mean();se=e*np.sqrt(ra*(1-ra)/a.sum()+rb*(1-rb)/b.sum())
    names.append(str(e));delt.append((ra-rb)*e);zs.append((ra-rb)*e/se)
fig,ax=plt.subplots(figsize=(7,4.5))
cols=["#c0392b" if abs(z)>3 else "#bbb" for z in zs]
bars=ax.bar(names,delt,color=cols)
for bar,z in zip(bars,zs): ax.text(bar.get_x()+bar.get_width()/2,bar.get_height()+(.006 if bar.get_height()>=0 else -.018),f"{z:.1f}",ha="center",fontsize=8)
ax.axhline(0,color="k",lw=.6);ax.set_ylabel("$\\Delta_\\ell$ (signed)");ax.set_xlabel("prime $\\ell$")
ax.set_title("Only ℓ=13 shows real square-class contrast; controls are noise (|Z|<2.2)\nbar labels = Z(Δ); N=5M")
ax.grid(alpha=.3,axis="y");fig.tight_layout();fig.savefig("fig_controls.png",dpi=130)
print("plots saved; power-law a=%.3f c=%.2f"%(aa,cc))
print("control Z:",dict(zip(names,[round(z,2) for z in zs])))
