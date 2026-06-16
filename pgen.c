#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <time.h>
// p(n) mod M, M = 13*17*19*23*29*31*37*41
int main(int argc, char**argv){
    long N = atol(argv[1]);
    const int64_t M = 131710070791LL; // 13*17*19*23*29*31*37*41
    // generalized pentagonal numbers up to N with signs
    long maxk = 1; while ( (long)maxk*(3L*maxk-1)/2 <= N ) maxk++;
    long cap = 2*maxk+4;
    long *g = malloc(sizeof(long)*cap);
    int *sg = malloc(sizeof(int)*cap);
    long cnt=0;
    for(long k=1;;k++){
        long a = k*(3*k-1)/2;
        long b = k*(3*k+1)/2;
        int s = (k%2==1)?1:-1;
        if(a>N && b>N) break;
        if(a<=N){g[cnt]=a; sg[cnt]=s; cnt++;}
        if(b<=N){g[cnt]=b; sg[cnt]=s; cnt++;}
    }
    int64_t *p = malloc(sizeof(int64_t)*(N+1));
    p[0]=1;
    clock_t t0=clock();
    for(long n=1;n<=N;n++){
        int64_t acc=0;
        for(long i=0;i<cnt && g[i]<=n;i++){
            acc += sg[i]*p[n-g[i]];
        }
        acc %= M; if(acc<0) acc+=M;
        p[n]=acc;
    }
    fprintf(stderr,"compute done N=%ld in %.1fs, pentterms=%ld\n",N,(double)(clock()-t0)/CLOCKS_PER_SEC,cnt);
    FILE*f=fopen("pmod.bin","wb");
    fwrite(p,sizeof(int64_t),N+1,f);
    fclose(f);
    return 0;
}
