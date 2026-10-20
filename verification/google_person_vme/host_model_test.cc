// Copyright 2026. SPDX-License-Identifier: Apache-2.0
// Native pinned-TFLM integration, emulated matrix arithmetic, NOT NPU RTL.
#include "conv_vme.h"
#include "person_program.h"
#include "fixtures.h"
#include "tensorflow/lite/micro/micro_interpreter.h"
#include "tensorflow/lite/micro/micro_mutable_op_resolver.h"
#include "tensorflow/lite/schema/schema_generated.h"
#include <cstdio>
#include <cstring>
#define CHECK(x) do { if (!(x)) { std::fprintf(stderr,"FAIL line %d: %s\n",__LINE__,#x); return 1; } } while (0)
int main() {
  alignas(16) static uint8_t arena[kPersonArenaBytes];
  tflite::MicroMutableOpResolver<5> resolver;
  CHECK(resolver.AddAveragePool2D(tflite::Register_AVERAGE_POOL_2D_INT8())==kTfLiteOk);
  CHECK(resolver.AddConv2D(person_vme::RegisterPointwise())==kTfLiteOk);
  CHECK(resolver.AddDepthwiseConv2D(tflite::Register_DEPTHWISE_CONV_2D_INT8())==kTfLiteOk);
  CHECK(resolver.AddReshape()==kTfLiteOk);
  CHECK(resolver.AddSoftmax(tflite::Register_SOFTMAX_INT8())==kTfLiteOk);
  tflite::MicroInterpreter interpreter(tflite::GetModel(pd_model),resolver,arena,sizeof(arena));
  CHECK(interpreter.AllocateTensors()==kTfLiteOk);
  const unsigned char* inputs[]={pd_fixture_person,pd_fixture_no_person};
  const char* names[]={"person","no_person"};
  const int scores[][2]={{-113,113},{57,-57}};
  for(int c=0;c<2;++c) {
    std::memcpy(interpreter.input(0)->data.int8,inputs[c],kPersonInputBytes);
    CHECK(interpreter.Invoke()==kTfLiteOk);
    CHECK(interpreter.output(0)->data.int8[0]==scores[c][0]);
    CHECK(interpreter.output(0)->data.int8[1]==scores[c][1]);
    CHECK(pd_vme_conv_calls==static_cast<unsigned>((c+1)*14));
    CHECK(pd_vme_validated_layers==pd_vme_conv_calls);
    CHECK(pd_vme_fallback_calls==0 && pd_vme_mismatches==0 && pd_vme_commands==0);
    CHECK(pd_vme_emulated_tiles>0);
    std::printf("[PERSON_VME_HOST_MODEL_CASE] case=%s layers=14 byte_exact=true scores=%d,%d\n",
                names[c],scores[c][0],scores[c][1]);
  }
  std::printf("[PERSON_VME_HOST_MODEL_PASS] cases=2 compared_layers=28 arena_used=%u hardware=NOT_RUN\n",
              static_cast<unsigned>(interpreter.arena_used_bytes()));
  return 0;
}
