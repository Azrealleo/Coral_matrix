`timescale 1ns/1ps

// Read-only, bind-only counter for the existing independent MXU boundary TB.
// Edges/first-beat semantics match mxu_perf_monitor.sv. This is a standalone
// unit schedule; its input-to-output window is NOT a full CoralNPU workload.
module mxu_model_perf_monitor (
    input wire clk, rst_n,
    input wire [2:0] op_type,
    input wire op_valid, op_ready, op_done,
    input wire [7:0] cfg_Tk,
    input wire result_valid, result_ready
);
    integer logical_m, logical_n, logical_k, physical_k;
    integer input_cycle, mma_cycle, mma_done_cycle, store_cycle, final_cycle;
    integer cycle_no = 0, output_beats = 0;
    bit input_started = 0, mma_active = 0, mma_completed = 0;
    bit mma_seen_done_low = 0, store_started = 0;

    initial begin
        if (!$value$plusargs("MODEL_M=%d", logical_m) ||
            !$value$plusargs("MODEL_N=%d", logical_n) ||
            !$value$plusargs("MODEL_K=%d", logical_k))
            $fatal(1, "MXU_MODEL_PERF: missing logical M/N/K plusargs");
        if (logical_m < 1 || logical_m > 16 || logical_n < 1 ||
            logical_n > 16 || logical_k < 1 || logical_k > 256)
            $fatal(1, "MXU_MODEL_PERF: invalid logical shape");
    end

    always @(posedge clk) begin
        if (rst_n !== 1'b1) begin
            cycle_no = 0;
            output_beats = 0;
            input_started = 0;
            mma_active = 0;
            mma_completed = 0;
            store_started = 0;
        end else begin
            cycle_no = cycle_no + 1;
            if (op_valid && op_ready && op_type == 3'd0) begin
                physical_k = (cfg_Tk == 0) ? 256 : cfg_Tk;
                if (physical_k < logical_k || physical_k > 256 ||
                    physical_k % 16 != 0)
                    $fatal(1, "MXU_MODEL_PERF: invalid physical K");
            end
            // Weight beat zero is consumed with the MLOAD_W command itself.
            if (op_valid && op_ready && op_type == 3'd1) begin
                if (input_started) $fatal(1, "MXU_MODEL_PERF: duplicate load");
                input_started = 1;
                input_cycle = cycle_no;
            end
            if (op_valid && op_ready && op_type == 3'd4) begin
                if (!input_started || mma_active || mma_completed)
                    $fatal(1, "MXU_MODEL_PERF: invalid MMA sequence");
                mma_cycle = cycle_no;
                mma_active = 1;
                mma_seen_done_low = 0;
            end
            if (op_valid && op_ready && op_type == 3'd5) begin
                if (!mma_completed)
                    $fatal(1, "MXU_MODEL_PERF: MSTORE before MMA completion");
                if (!store_started) begin
                    store_started = 1;
                    store_cycle = cycle_no;
                end
            end
            if (result_valid && result_ready) begin
                if (!store_started || output_beats >= 64)
                    $fatal(1, "MXU_MODEL_PERF: unexpected output handshake");
                output_beats = output_beats + 1;
                if (output_beats == 64) begin
                    final_cycle = cycle_no;
                    $display("[MXU_MODEL_PERF] M=%0d N=%0d K=%0d K_hw=%0d output_beats=64 mma_latency_cycles=%0d input_to_output_span_cycles=%0d readback_span_cycles=%0d useful_macs=%0d physical_macs=%0d",
                             logical_m, logical_n, logical_k, physical_k,
                             mma_done_cycle - mma_cycle,
                             final_cycle - input_cycle + 1,
                             final_cycle - store_cycle + 1,
                             logical_m * logical_n * logical_k,
                             256 * physical_k);
                end
            end
            // Registered completion is visible after the rising-edge NBA.
            #0.001;
            if (mma_active) begin
                if (op_done === 1'b0) mma_seen_done_low = 1;
                if (mma_seen_done_low && op_done === 1'b1) begin
                    mma_done_cycle = cycle_no;
                    if (mma_done_cycle - mma_cycle != physical_k + 3)
                        $fatal(1, "MXU_MODEL_PERF: MMA latency changed; check counter/RTL");
                    mma_active = 0;
                    mma_completed = 1;
                end
            end
        end
    end
endmodule

bind mxu_boundary_tb mxu_model_perf_monitor u_mxu_model_perf_monitor (
    .clk(clk), .rst_n(rst_n), .op_type(op_type), .op_valid(op_valid),
    .op_ready(op_ready), .op_done(op_done), .cfg_Tk(cfg_Tk),
    .result_valid(result_valid), .result_ready(result_ready)
);
