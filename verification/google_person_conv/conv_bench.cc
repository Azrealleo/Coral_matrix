// Copyright 2026. SPDX-License-Identifier: Apache-2.0
// One-operator Invoke comparison. Checking and Prepare are outside timed calls.
#include "conv_cases.h"
#include "conv_vme.h"
#include "tensorflow/lite/micro/micro_interpreter.h"
#include "tensorflow/lite/micro/micro_mutable_op_resolver.h"
#include "tensorflow/lite/schema/schema_generated.h"
#include <cstring>
#ifdef PD_CONV_HOST
#include <cstdio>
#endif
extern "C" {
volatile uint32_t pd_probe_status,pd_probe_cases,pd_probe_checked,pd_probe_mismatches;
volatile uint32_t pd_probe_first_expected,pd_probe_first_actual,pd_probe_first_case;
volatile uint32_t pd_probe_signature;
uint32_t pd_probe_commands;
// Nonzero .data initializer preserves the host-selected case across CRT BSS init.
volatile uint32_t pd_conv_case=0xfffffffeu;
volatile uint32_t pd_conv_ref_cycles[4],pd_conv_vme_cycles[4],pd_conv_empty_cycles;
volatile uint32_t pd_conv_m,pd_conv_k,pd_conv_n,pd_conv_op,pd_conv_arena_ref,pd_conv_arena_vme;
}
namespace {
alignas(16) uint8_t reference_arena[kConvArenaBytes],vme_arena[kConvArenaBytes];
uint32_t Cycle() {
#ifdef PD_CONV_HOST
  return 0; // Host numerical qualification only; never a hardware timing claim.
#else
  uint32_t value;asm volatile("fence rw,rw\ncsrr %0,mcycle":"=r"(value)::"memory");return value;
#endif
}
int Fail(unsigned status) {pd_probe_status=status;return 1;}
int Run(unsigned index) {
  pd_probe_status=1;pd_probe_cases=pd_probe_checked=pd_probe_mismatches=0;
  pd_probe_first_expected=pd_probe_first_actual=pd_probe_first_case=0;
  pd_vme_conv_calls=pd_vme_fallback_calls=pd_vme_commands=pd_vme_mismatches=0;
  pd_vme_emulated_tiles=pd_vme_validated_layers=0;
  const ConvCase& c=kConvCases[index];
  pd_conv_m=c.m;pd_conv_k=c.k;pd_conv_n=c.n;pd_conv_op=c.op;
  tflite::MicroMutableOpResolver<1> ref_resolver,vme_resolver;
  if(ref_resolver.AddConv2D(tflite::Register_CONV_2D_INT8())!=kTfLiteOk ||
     vme_resolver.AddConv2D(person_vme::RegisterPointwise())!=kTfLiteOk)return Fail(101);
  const tflite::Model* model=tflite::GetModel(c.model);
  tflite::MicroInterpreter ref(model,ref_resolver,reference_arena,sizeof(reference_arena));
  tflite::MicroInterpreter vme(model,vme_resolver,vme_arena,sizeof(vme_arena));
  if(ref.AllocateTensors()!=kTfLiteOk || vme.AllocateTensors()!=kTfLiteOk)return Fail(102);
  pd_conv_arena_ref=ref.arena_used_bytes();pd_conv_arena_vme=vme.arena_used_bytes();
  if(!ref.input(0) || !vme.input(0) || ref.input(0)->bytes!=c.input_bytes ||
     vme.input(0)->bytes!=c.input_bytes || ref.output(0)->bytes!=static_cast<unsigned>(c.m*c.n) ||
     vme.output(0)->bytes!=ref.output(0)->bytes)return Fail(103);
  std::memcpy(ref.input(0)->data.int8,c.input,c.input_bytes);
  std::memcpy(vme.input(0)->data.int8,c.input,c.input_bytes);
  const uint32_t empty=Cycle();pd_conv_empty_cycles=Cycle()-empty;
  uint32_t signature=2166136261u;
  pd_probe_status=2;
  for(unsigned r=0;r<kConvSamples;++r) {
    // First-call and 3 steady samples; alternate order to expose order effects.
    for(unsigned t=0;t<2;++t) {
      const bool optimized=((t+r)%2)!=0;
      tflite::MicroInterpreter& interpreter=optimized?vme:ref;
      const uint32_t start=Cycle();
      const TfLiteStatus status=interpreter.Invoke();
      const uint32_t elapsed=Cycle()-start;
      if(optimized)pd_conv_vme_cycles[r]=elapsed;else pd_conv_ref_cycles[r]=elapsed;
      if(status!=kTfLiteOk)return Fail(104);
    }
    // This loop and the reference Invoke are NOT inside VME timing.
    for(int i=0;i<c.m*c.n;++i) {
      const int8_t expected=ref.output(0)->data.int8[i],actual=vme.output(0)->data.int8[i];
      if(actual!=expected) {
        if(!pd_probe_mismatches) {
          pd_probe_first_case=index;pd_probe_first_expected=static_cast<uint32_t>(expected);
          pd_probe_first_actual=static_cast<uint32_t>(actual);
        }
        ++pd_probe_mismatches;
      }
      ++pd_probe_checked;signature=(signature^static_cast<uint8_t>(actual))*16777619u;
    }
  }
  pd_probe_commands=pd_vme_commands;pd_probe_signature=signature;pd_probe_cases=1;
  if(pd_probe_mismatches || pd_vme_conv_calls!=kConvSamples || pd_vme_fallback_calls ||
     pd_vme_mismatches || pd_vme_validated_layers || pd_probe_checked!=kConvSamples*c.m*c.n)return Fail(105);
#ifdef PD_CONV_HOST
  if(!pd_vme_emulated_tiles || pd_vme_commands)return Fail(106);
  std::printf("[PERSON_CONV_HOST_CASE] id=%u name=%s checked=%u signature=%u ref_and_emulated_vme_equal=true\n",
      index,c.name,static_cast<unsigned>(pd_probe_checked),signature);
#else
  if(!pd_vme_commands || pd_vme_emulated_tiles)return Fail(106);
  for(unsigned r=0;r<kConvSamples;++r)if(!pd_conv_ref_cycles[r] || !pd_conv_vme_cycles[r])return Fail(107);
#endif
  pd_probe_status=3;return 0;
}
}
int main() {
#ifdef PD_CONV_HOST
  for(unsigned i=0;i<kConvCaseCount;++i)if(Run(i))return 1;
  std::printf("[PERSON_CONV_HOST_PASS] cases=5 complete_model=NOT_RUN hardware=NOT_RUN\n");
  return 0;
#else
  const unsigned index=pd_conv_case;
  if(index>=kConvCaseCount)return Fail(108);
  return Run(index);
#endif
}
