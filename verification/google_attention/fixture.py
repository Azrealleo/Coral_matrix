"""Independent single-head causal Attention reference and stage boundaries."""
import hashlib
import math
import random
import struct

CASES=(('attention_decode','GEGLU',(1,4,3,0,0)),
       ('attention_tail','GEGLU',(3,6,7,0,0)),
       ('attention_prefill','GEGLU',(4,8,11,0,0)))
PROBE_CASE=('attention_zero_safety','GEGLU',(1,2,0,0,0))
NAMES=('norm','q','k','v','q_rope','k_rope','prefill_k','prefill_v','final_k','final_v','context','projected','output')
KEY_POISON=71.25;VALUE_POISON=-43.5
GUARD=struct.unpack('<f',struct.pack('<I',0x55aa7711))[0]
def f32(x):return struct.unpack('<f',struct.pack('<f',x))[0]
def packed(values):return struct.pack('<'+'f'*len(values),*values)

def layout(shape):
    p,h,base,*_=shape
    if any(type(v) is not int for v in (p,h,base)) or p<1 or h<2 or h%2 or base<0 or (p+1)*h>64:
        raise ValueError('Invalid single-head Attention shape')
    n=(p+1)*h
    return [(name,i*(n+4),n) for i,name in enumerate(NAMES)]

def golden(shape,x,w):
    p,h,base,*_=shape;s=p+1;n=s*h;layout(shape)
    if len(x)!=n or len(w)!=h+4*h*h+n:raise ValueError('Wrong Attention input geometry')
    gamma=w[:h];matrices=[w[h+i*h*h:h+(i+1)*h*h] for i in range(4)];rope=w[h+4*h*h:]
    norm=[]
    for r in range(s):
        row=x[r*h:(r+1)*h];scale=1/math.sqrt(math.fsum(v*v for v in row)/h+1e-5)
        norm.extend(f32(v*scale*(1+gamma[c])) for c,v in enumerate(row))
    def linear(a,b):return [f32(math.fsum(a[r*h+i]*b[i*h+c] for i in range(h))) for r in range(s) for c in range(h)]
    q,k,v=[linear(norm,m) for m in matrices[:3]]
    def rotate(a):
        out=[0.]*n
        for r in range(s):
            for j in range(h//2):
                at=r*h+j;hi=at+h//2;co,si=rope[at],rope[hi]
                out[at]=f32(a[at]*co-a[hi]*si);out[hi]=f32(a[hi]*co+a[at]*si)
        return out
    qr,kr=rotate(q),rotate(k)
    context=[]
    for r in range(s):
        logits=[math.fsum(qr[r*h+j]*kr[i*h+j] for j in range(h))/math.sqrt(h) for i in range(r+1)]
        terms=[math.exp(t-max(logits)) for t in logits];den=math.fsum(terms)
        prob=[t/den for t in terms]
        context.extend(f32(math.fsum(prob[i]*v[i*h+j] for i in range(r+1))) for j in range(h))
    projected=linear(context,matrices[3]);output=[f32(a+b) for a,b in zip(projected,x)]
    tensors=(norm,q,k,v,qr,kr,kr[:p*h]+[KEY_POISON]*h,v[:p*h]+[VALUE_POISON]*h,kr,v,context,projected,output)
    y=[]
    for i,values in enumerate(tensors):
        y.extend(values)
        if i<len(tensors)-1:y.extend([GUARD]*4)
    return y

def fixture(index):
    if type(index) is not int or not 0<=index<=len(CASES):raise ValueError('Wrong case index')
    name,kind,shape=PROBE_CASE if index==len(CASES) else CASES[index]
    p,h,base,*_=shape;s=p+1;n=s*h;rng=random.Random(20261027+index)
    x=[f32(rng.uniform(-1,1)) for _ in range(n)]
    w=[f32(rng.uniform(-.2,.2)) for _ in range(h)]
    w += [f32(rng.uniform(-.5,.5)/math.sqrt(h)) for _ in range(4*h*h)]
    for r in range(s):
        angles=[(base+r)*10000**(-2*j/h) for j in range(h//2)]
        w += [f32(math.cos(a)) for a in angles]+[f32(math.sin(a)) for a in angles]
    if index==len(CASES):x=[0.]*n
    y=golden(shape,x,w)
    if max(len(x),len(w),len(y))>1024:raise ValueError('Attention static capacity exceeded')
    return dict(id=index,name=name,kind=kind,shape=shape,x=x,w=w,v=[],y=y,algorithm=y[:],
                vector_sha256=hashlib.sha256(packed(x)+packed(w)).hexdigest(),
                algorithm_sha256=hashlib.sha256(packed(y)).hexdigest())
