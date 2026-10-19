// Copyright 2026. SPDX-License-Identifier: Apache-2.0
// Entire unchanged pretrained model, pinned TFLM INT8 kernels, no VME offload.
#include "person_program.h"
#include "tensorflow/lite/c/common.h"
#include "tensorflow/lite/micro/micro_interpreter.h"
#include "tensorflow/lite/micro/micro_mutable_op_resolver.h"
#include "tensorflow/lite/schema/schema_generated.h"

extern "C" {
// Nonzero initializer keeps the host-preloaded input in .data, not CRT-zeroed BSS.
alignas(16) int8_t pd_input[kPersonInputBytes] = {1};
alignas(16) int8_t pd_output[2] = {37, 53};
alignas(16) uint8_t pd_tensor_arena[kPersonArenaBytes];
volatile uint32_t pd_status = 0;
volatile uint32_t pd_arena_used = 0;
volatile uint32_t pd_invoke_cycles = 0;
}

static uint32_t cycle() {
  uint32_t value;
  asm volatile("fence rw, rw\ncsrr %0, mcycle" : "=r"(value) : : "memory");
  return value;
}

static int fail(uint32_t status) {
  pd_status = status;
  asm volatile("fence rw, rw" : : : "memory");
  return 1;
}

int main() {
  pd_status = 1;
  const tflite::Model* model = tflite::GetModel(pd_model);
  if (model->version() != TFLITE_SCHEMA_VERSION) return fail(101);
  tflite::MicroMutableOpResolver<5> resolver;
  if (resolver.AddAveragePool2D(tflite::Register_AVERAGE_POOL_2D_INT8()) != kTfLiteOk ||
      resolver.AddConv2D(tflite::Register_CONV_2D_INT8()) != kTfLiteOk ||
      resolver.AddDepthwiseConv2D(tflite::Register_DEPTHWISE_CONV_2D_INT8()) != kTfLiteOk ||
      resolver.AddReshape() != kTfLiteOk ||
      resolver.AddSoftmax(tflite::Register_SOFTMAX_INT8()) != kTfLiteOk) return fail(102);
  tflite::MicroInterpreter interpreter(model, resolver, pd_tensor_arena, kPersonArenaBytes);
  if (interpreter.AllocateTensors() != kTfLiteOk) return fail(103);
  pd_arena_used = static_cast<uint32_t>(interpreter.arena_used_bytes());
  TfLiteTensor* input = interpreter.input(0);
  TfLiteTensor* output = interpreter.output(0);
  if (!input || !output || input->type != kTfLiteInt8 || output->type != kTfLiteInt8 ||
      input->dims->size != 4 || input->dims->data[0] != 1 || input->dims->data[1] != 96 ||
      input->dims->data[2] != 96 || input->dims->data[3] != 1 ||
      input->bytes != kPersonInputBytes || output->bytes != 2 ||
      output->dims->size != 2 || output->dims->data[0] != 1 || output->dims->data[1] != 2)
    return fail(104);
  for (unsigned i = 0; i < kPersonInputBytes; ++i) input->data.int8[i] = pd_input[i];
  pd_status = 2;
  const uint32_t start = cycle();
  if (interpreter.Invoke() != kTfLiteOk) return fail(105);
  pd_invoke_cycles = cycle() - start;
  pd_output[0] = output->data.int8[0];  // no_person
  pd_output[1] = output->data.int8[1];  // person
  pd_status = 3;
  asm volatile("fence rw, rw" : : : "memory");
  return 0;
}
