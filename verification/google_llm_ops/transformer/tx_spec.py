"""Independent FP64 references for small FP32 Transformer operators."""
import hashlib
import json
import math
import re
import struct

UPSTREAM="8e4df09b4ea7e065e02d14ce3ae033d40dfd973a"
LINEAR_PACKAGE="tests/cocotb/llm_linear_v1"
PACKAGE="tests/cocotb/llm_transformer_v1"
TOP="VmeCoreMini_ITCM256KB_DTCM512KBAxi"
SCOPE="resident_FP32_operator_scalar_vs_RVV_not_full_Transformer_or_LLM"
MARKER="[LLM_TX_OBSERVATION] "
ATOL=0.00002
RTOL=0.0002
SAMPLES=4
CAPACITY=1024
KINDS=("MATMUL","RMS","SOFTMAX","ROPE","SWIGLU","GEGLU","RESIDUAL","KVAPPEND","ATTENTION")
CASES=(
    ("f32_decode","MATMUL",(1,16,32,0,0)),
    ("f32_prefill","MATMUL",(4,16,32,0,0)),
    ("rms_decode","RMS",(1,64,0,0,0)),
    ("rms_prefill","RMS",(8,64,0,0,0)),
    ("rms_tail","RMS",(3,37,0,0,0)),
    ("softmax_short","SOFTMAX",(1,32,0,0,0)),
    ("softmax_extreme_tail","SOFTMAX",(4,37,0,0,0)),
    ("rope_decode","ROPE",(1,64,7,0,0)),
    ("rope_prefill","ROPE",(8,64,3,0,0)),
    ("swiglu","SWIGLU",(256,0,0,0,0)),
    ("geglu","GEGLU",(256,0,0,0,0)),
    ("residual","RESIDUAL",(512,0,0,0,0)),
    ("kv_append","KVAPPEND",(4,2,16,0,0)),
    ("causal_prefill","ATTENTION",(2,4,4,16,0)),
    ("causal_decode","ATTENTION",(2,1,16,16,15)),
    ("causal_first","ATTENTION",(2,1,4,16,0)),
    ("causal_future_poison","ATTENTION",(2,1,4,16,0)),
)


def f32(x):return struct.unpack("<f",struct.pack("<f",x))[0]


def packed(values):return struct.pack("<"+"f"*len(values),*values)


def softmax(values):
    maximum=max(values); terms=[math.exp(v-maximum) for v in values];total=sum(terms)
    return [v/total for v in terms]


def golden(kind,shape,x,w,v):
    a,b,c,d,p=shape
    if kind=="MATMUL":
        return [sum(x[r*b+k]*w[k*c+n] for k in range(b)) for r in range(a) for n in range(c)]
    if kind=="RMS":
        return [value/math.sqrt(sum(t*t for t in x[r*b:(r+1)*b])/b+1e-5)*(1+w[j])
                for r in range(a) for j,value in enumerate(x[r*b:(r+1)*b])]
    if kind=="SOFTMAX":
        return [value for r in range(a) for value in softmax(x[r*b:(r+1)*b])]
    if kind=="ROPE":
        out=[0.0]*(a*b)
        for r in range(a):
            for i in range(b//2):
                at=r*b+i;co,si=w[at],w[at+b//2]
                out[at]=x[at]*co-x[at+b//2]*si
                out[at+b//2]=x[at+b//2]*co+x[at]*si
        return out
    if kind=="SWIGLU":return [value/(1+math.exp(-value))*weight for value,weight in zip(x,w)]
    if kind=="GEGLU":
        return [0.5*value*(1+math.tanh(math.sqrt(2/math.pi)*(value+0.044715*value**3)))*weight
                for value,weight in zip(x,w)]
    if kind=="RESIDUAL":return [a+b for a,b in zip(x,w)]
    if kind=="KVAPPEND":
        old,added=a*c,b*c
        return x[:old]+w[:added]+x[old:]+w[added:]
    if kind=="ATTENTION":
        out=[]
        # Two query heads share ONE KV head, explicit causal absolute positions.
        for h in range(a):
            for q in range(b):
                visible=min(c,p+q+1);query=x[(h*b+q)*d:(h*b+q+1)*d]
                scores=[sum(query[j]*w[k*d+j] for j in range(d))/math.sqrt(d) for k in range(visible)]
                probabilities=softmax(scores)
                out.extend(sum(probabilities[k]*v[k*d+j] for k in range(visible)) for j in range(d))
        return out
    raise ValueError("Unknown operator")


def fixture(index):
    name,kind,shape=CASES[index];a,b,c,d,p=shape
    # Last pair shares identical data except future K/V, to expose missing mask.
    state=20261022+(15 if index==16 else index)
    def random_values(count):
        nonlocal state
        result=[]
        for _ in range(count):
            state^=(state<<13)&0xffffffff;state^=state>>17;state^=(state<<5)&0xffffffff
            result.append(f32((state%257-128)/64))
        return result
    if kind=="MATMUL":counts=(a*b,b*c,0)
    elif kind=="RMS":counts=(a*b,b,0)
    elif kind=="SOFTMAX":counts=(a*b,0,0)
    elif kind=="ROPE":counts=(a*b,0,0)
    elif kind in ("SWIGLU","GEGLU","RESIDUAL"):counts=(a,a,0)
    elif kind=="KVAPPEND":counts=(2*a*c,2*b*c,0)
    elif kind=="ATTENTION":counts=(a*b*d,c*d,c*d)
    else:raise ValueError("Unsupported kind")
    x,w,v=[random_values(count) for count in counts]
    if kind=="SOFTMAX" and name=="softmax_extreme_tail":
        x=[f32(value+(1000 if (i//b)%2==0 else -1000)) for i,value in enumerate(x)]
    if kind=="ROPE":
        for r in range(a):
            angles=[(c+r)*10000**(-2*i/b) for i in range(b//2)]
            w.extend(map(f32,map(math.cos,angles)));w.extend(map(f32,map(math.sin,angles)))
    if name=="causal_future_poison":
        w[d:]=[f32(1000+i) for i in range(len(w)-d)]
        v[d:]=[f32(-1000-i) for i in range(len(v)-d)]
    y=list(map(f32,golden(kind,shape,x,w,v)))
    if max(map(len,(x,w,v,y)))>CAPACITY:raise ValueError("Fixture exceeds fixed workspace")
    digest=hashlib.sha256(packed(x)+packed(w)+packed(v)).hexdigest()
    return dict(id=index,name=name,kind=kind,shape=list(shape),x=x,w=w,v=v,y=y,vector_sha256=digest)


def close(actual,expected):
    return math.isfinite(actual) and abs(actual-expected)<=ATOL+RTOL*abs(expected)


def accept(row,index):
    data=fixture(index)
    required=dict(schema=1,scope=SCOPE,case_id=index,case=data["name"],kind=data["kind"],shape=data["shape"],
        itcm_kib=256,dtcm_kib=512,fault=False,natural_halt=True,firmware_status=3,
        mismatches=0,guard_ok=True,stack_low_canary_intact=True,input_readback_equal=True,
        independent_output_check=True,checked_elements=SAMPLES*len(data["y"]),rvv_calls=SAMPLES,
        vector_sha256=data["vector_sha256"],atol=ATOL,rtol=RTOL)
    if any(type(row.get(k)) is not type(v) or row[k]!=v for k,v in required.items()):
        raise ValueError("Incomplete/wrong Transformer result")
    for name in ("elf_sha256","rtl_sha256"):
        if not re.fullmatch("[a-f0-9]{64}",row.get(name,"")):raise ValueError("Missing identity")
    for name in ("scalar_max_abs_error","rvv_max_abs_error"):
        if type(row.get(name)) not in (float,int) or not math.isfinite(row[name]) or row[name]<0:
            raise ValueError("Missing finite numerical error measurement")
        if row[name]>ATOL+RTOL*max(map(abs,data["y"])):
            raise ValueError("Reported error contradicts numerical PASS")
    total,empty=row.get("observation_elapsed_cycles"),row.get("empty_boundary_cycles")
    arrays=[row.get("scalar_cycles"),row.get("rvv_cycles")]
    if type(total) is not int or total<=0 or type(empty) is not int or empty<0:
        raise ValueError("Invalid total/boundary cycles")
    if any(not isinstance(xs,list) or len(xs)!=SAMPLES or
           any(type(x) is not int or x<=empty or x>total for x in xs) for xs in arrays):
        raise ValueError("Invalid mcycle samples")
    if sum(map(sum,arrays))>total:raise ValueError("Timed samples exceed total")
    return dict(case_id=index,case=data["name"],kind=data["kind"],shape=data["shape"],
        scalar_cycles=arrays[0],rvv_cycles=arrays[1],empty_boundary_cycles=empty,
        first_scalar_over_rvv=arrays[0][0]/arrays[1][0],
        steady_scalar_over_rvv=sum(arrays[0][1:])/sum(arrays[1][1:]),
        scope=SCOPE,full_model="NOT_RUN",VME="NOT_RUN",
        scalar_max_abs_error=row["scalar_max_abs_error"],rvv_max_abs_error=row["rvv_max_abs_error"])


def checked_log(text,index):
    text=re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]","",text)
    rows=[json.loads(s.split(MARKER,1)[1]) for s in text.splitlines() if MARKER in s]
    results=re.findall(r"TESTS=(\d+)\s+PASS=(\d+)\s+FAIL=(\d+)\s+SKIP=(\d+)",text)
    if len(rows)!=1 or not results or results[-1]!=("1","1","0","0"):
        raise ValueError("Missing/failed/duplicate Transformer test")
    return rows[0],accept(rows[0],index)
