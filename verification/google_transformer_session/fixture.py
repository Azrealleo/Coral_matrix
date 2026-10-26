"""Multi-call layer reference: independent full causal sequence + FP32 FFN boundary."""
import hashlib
import math
import random
import attention_reference as attn
import ffn_reference as ffn

CASES=(('session_decode2','GEGLU',(1,4,8,2,3)),
       ('session_tail3','GEGLU',(2,6,13,3,7)),
       ('session_prefill3','GEGLU',(3,8,8,3,11)))
PROBE_CASE=('session_zero_safety','GEGLU',(1,2,3,2,0))
f32=attn.f32;packed=attn.packed;GUARD=attn.GUARD

def layout(shape):
    if len(shape)!=5 or any(type(v) is not int for v in shape):raise ValueError('Invalid session shape types')
    p,h,f,t,base=shape;s=p+t
    if p<1 or not 1<=t<=3 or s>8 or not 1<=f<=32:raise ValueError('Invalid session geometry')
    a=attn.layout((s-1,h,base,0,0));start=a[-1][1]+a[-1][2]+4
    result=a+[("ffn_"+name,start+at,n) for name,at,n in ffn.layout((s,h,f,0,0))]
    if result[-1][1]+result[-1][2]>1024:raise ValueError('Session workspace exceeded')
    return result

def golden(shape,x,w):
    p,h,f,t,base=shape;s=p+t;n=s*h;layout(shape);split=h+4*h*h+n
    a=attn.golden((s-1,h,base,0,0),x,w[:split])
    parts={name:(at,size) for name,at,size in attn.layout((s-1,h,base,0,0))}
    for pre,source,poison in (('prefill_k','k_rope',attn.KEY_POISON),('prefill_v','v',attn.VALUE_POISON)):
        at,_=parts[pre];src,_=parts[source]
        a[at:at+n]=a[src:src+p*h]+[poison]*(t*h)
    at,_=parts['output'];b=ffn.golden((s,h,f,0,0),a[at:at+n],w[split:])
    return a+[GUARD]*4+b

def fixture(index):
    if type(index) is not int or not 0<=index<=3:raise ValueError('Invalid session case')
    name,kind,shape=PROBE_CASE if index==3 else CASES[index]
    p,h,f,t,base=shape;s=p+t;rng=random.Random(20261029+index);layout(shape)
    x=[f32(rng.uniform(-1,1)) for _ in range(s*h)]
    if index==3:x=[0.]*(s*h)
    w=[f32(rng.uniform(-.2,.2)) for _ in range(h)]
    w.extend(f32(rng.uniform(-.5,.5)/math.sqrt(h)) for _ in range(4*h*h))
    for r in range(s):
        angles=[(base+r)*10000**(-2*j/h) for j in range(h//2)]
        w.extend([f32(math.cos(a)) for a in angles]+[f32(math.sin(a)) for a in angles])
    w.extend(f32(rng.uniform(-.2,.2)) for _ in range(h))
    for k,n in ((h,f),(h,f),(f,h)):
        w.extend(f32(rng.uniform(-.5,.5)/math.sqrt(k)) for _ in range(k*n))
    y=golden(shape,x,w);alternate=golden(shape,[-v for v in x],w)
    if max(len(x),len(w),len(y),len(alternate))>1024:raise ValueError('Static session capacity exceeded')
    return dict(id=index,name=name,kind=kind,shape=shape,x=x,w=w,v=alternate,y=y,algorithm=y[:],
                vector_sha256=hashlib.sha256(packed(x)+packed(w)).hexdigest(),
                algorithm_sha256=hashlib.sha256(packed(y)).hexdigest(),
                alternate_sha256=hashlib.sha256(packed(alternate)).hexdigest())
