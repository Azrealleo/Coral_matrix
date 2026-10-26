"""Independent FP64 references composed through an explicit FP32 residual boundary."""
import hashlib
import math
import random
import struct
import attention_reference as attn
import ffn_reference as ffn

CASES=(('layer_decode','GEGLU',(1,4,8,3,0)),
       ('layer_tail','GEGLU',(3,6,13,7,0)),
       ('layer_prefill','GEGLU',(4,8,16,11,0)))
PROBE_CASE=('layer_zero_safety','GEGLU',(1,2,3,0,0))
f32=attn.f32;packed=attn.packed;GUARD=attn.GUARD

def layout(shape):
    p,h,f,base,_=shape
    if type(f) is not int or not 1<=f<=32:raise ValueError('Invalid layer FFN dimension')
    a=attn.layout((p,h,base,0,0));start=a[-1][1]+a[-1][2]+4
    return a+[("ffn_"+name,start+at,n) for name,at,n in ffn.layout((p+1,h,f,0,0))]

def golden(shape,x,w):
    p,h,f,base,_=shape;layout(shape);nw=h+4*h*h+(p+1)*h
    a=attn.golden((p,h,base,0,0),x,w[:nw]);at=attn.layout((p,h,base,0,0))[-1][1]
    residual=a[at:at+(p+1)*h]
    b=ffn.golden((p+1,h,f,0,0),residual,w[nw:])
    return a+[GUARD]*4+b

def fixture(index):
    if type(index) is not int or not 0<=index<=3:raise ValueError('Wrong layer case index')
    name,kind,shape=PROBE_CASE if index==3 else CASES[index]
    p,h,f,base,_=shape;a=attn.fixture(index)
    if a['shape'][:3]!=(p,h,base):raise ValueError('Frozen Attention geometry changed')
    rng=random.Random(20261028+index)
    fw=[f32(rng.uniform(-.2,.2)) for _ in range(h)]
    for k,n in ((h,f),(h,f),(f,h)):
        fw.extend(f32(rng.uniform(-.5,.5)/math.sqrt(k)) for _ in range(k*n))
    x=a['x'];w=a['w']+fw;y=golden(shape,x,w)
    if max(len(x),len(w),len(y))>1024:raise ValueError('Layer static capacity exceeded')
    return dict(id=index,name=name,kind=kind,shape=shape,x=x,w=w,v=[],y=y,algorithm=y[:],
                vector_sha256=hashlib.sha256(packed(x)+packed(w)).hexdigest(),
                algorithm_sha256=hashlib.sha256(packed(y)).hexdigest())
