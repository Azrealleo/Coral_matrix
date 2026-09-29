`timescale 1ns/1ps

// Simulation-only observer for mxu_tb. Never drives DUT or testbench signals.
// Handshakes are sampled immediately before the rising-edge NBA updates.
// op_done is observed 1 ps after the same edge, matching the edge on which
// registered completion becomes visible, without do_mma's extra wait edge.
module mxu_perf_monitor (
    input wire clk,
    input wire rst_n,
    input wire [2:0] op_type,
    input wire op_valid,
    input wire op_ready,
    input wire op_done,
    input wire [7:0] cfg_Tk,
    input wire cfg_signed,
    input wire weight_valid,
    input wire weight_ready,
    input wire act_valid,
    input wire act_ready,
    input wire result_valid,
    input wire result_ready
);
    longint unsigned cycle_no = 0;
    longint unsigned config_cycle, first_input_cycle, last_input_cycle;
    longint unsigned mma_start_cycle, mma_latency_cycles;
    longint unsigned store_start_cycle;
    longint unsigned load_span, readback_span, total_span, config_span, useful_macs;
    integer case_no = 0;
    integer weight_beats, act_beats, output_beats, configured_k;
    bit frame_active = 0;
    bit mma_active = 0;
    bit mma_seen_done_low = 0;
    bit mma_completed = 0;
    bit store_started = 0;
    bit input_started = 0;
    bit signed_cfg;
    string repo_revision;

    initial begin
        if (!$value$plusargs("MXU_REPO_REV=%s", repo_revision))
            repo_revision = "unknown";
        $display("[MXU_PERF_META] monitor_version=1 repo_revision=%s scope=existing_mxu_tb_schedule", repo_revision);
    end

    always @(posedge clk) begin
        if (rst_n !== 1'b1) begin
            cycle_no = 0;
            case_no = 0;
            frame_active = 0;
            mma_active = 0;
            mma_completed = 0;
            store_started = 0;
            input_started = 0;
        end else begin
            cycle_no = cycle_no + 1;

            // One frame is the current mxu_tb sequence: MCFG, MZERO,
            // weight load, activation load, one MMA, and 64 MSTORE beats.
            if (op_valid && op_ready && op_type == 3'd0) begin
                if (frame_active)
                    $fatal(1, "MXU_PERF: reconfiguration before previous output completed");
                case_no = case_no + 1;
                frame_active = 1;
                config_cycle = cycle_no;
                configured_k = (cfg_Tk == 0) ? 256 : cfg_Tk;
                signed_cfg = cfg_signed;
                weight_beats = 0;
                act_beats = 0;
                output_beats = 0;
                input_started = 0;
                mma_active = 0;
                mma_completed = 0;
                store_started = 0;
                mma_latency_cycles = 0;
            end

            // This RTL consumes beat 0 on the command handshake, BEFORE
            // weight_ready/act_ready becomes asserted. Count it exactly once.
            if ((op_valid && op_ready && op_type == 3'd1) ||
                (weight_valid && weight_ready)) begin
                if (!frame_active)
                    $fatal(1, "MXU_PERF: weight arrived before MCFG");
                if (!input_started) begin
                    first_input_cycle = cycle_no;
                    input_started = 1;
                end
                weight_beats = weight_beats + 1;
                last_input_cycle = cycle_no;
            end

            if ((op_valid && op_ready && op_type == 3'd2) ||
                (act_valid && act_ready)) begin
                if (!frame_active || !input_started)
                    $fatal(1, "MXU_PERF: activation arrived before first weight beat");
                act_beats = act_beats + 1;
                last_input_cycle = cycle_no;
            end

            // OP_MMA=4 and OP_MSTORE=5 are the encodings used by mxu_tb.
            if (op_valid && op_ready && op_type == 3'd4) begin
                if (!frame_active || mma_active || mma_completed)
                    $fatal(1, "MXU_PERF: unexpected MMA command sequence");
                if (weight_beats != configured_k ||
                    act_beats != 16 * ((configured_k + 15) / 16))
                    $fatal(1, "MXU_PERF: input beat counts do not match configured K");
                mma_start_cycle = cycle_no;
                mma_active = 1;
                mma_seen_done_low = 0;
            end

            if (op_valid && op_ready && op_type == 3'd5) begin
                if (!frame_active || !mma_completed)
                    $fatal(1, "MXU_PERF: store accepted before MMA completion");
                if (!store_started) begin
                    store_start_cycle = cycle_no;
                    store_started = 1;
                end
            end

            if (result_valid && result_ready) begin
                if (!frame_active || !store_started)
                    $fatal(1, "MXU_PERF: unexpected output handshake");
                output_beats = output_beats + 1;
                if (output_beats == 64) begin
                    load_span = last_input_cycle - first_input_cycle + 1;
                    readback_span = cycle_no - store_start_cycle + 1;
                    total_span = cycle_no - first_input_cycle + 1;
                    config_span = cycle_no - config_cycle + 1;
                    useful_macs = 256 * configured_k;
                    $display("[MXU_PERF] case=%0d K=%0d cfg_signed=%0b weight_beats=%0d act_beats=%0d output_beats=%0d load_span_cycles=%0d mma_latency_cycles=%0d readback_span_cycles=%0d input_to_output_span_cycles=%0d config_to_output_span_cycles=%0d useful_macs=%0d mma_mac_per_cycle=%0.3f",
                        case_no, configured_k, signed_cfg, weight_beats,
                        act_beats, output_beats, load_span, mma_latency_cycles,
                        readback_span, total_span, config_span, useful_macs,
                        real'(useful_macs) / real'(mma_latency_cycles));
                    frame_active = 0;
                end
            end

            if (frame_active && cycle_no - config_cycle > 1000000)
                $fatal(1, "MXU_PERF: input-to-output watchdog timeout");

            // Observe completion after the DUT's nonblocking assignments.
            #0.001;
            if (mma_active) begin
                if (op_done === 1'b0)
                    mma_seen_done_low = 1;
                if (mma_seen_done_low && op_done === 1'b1) begin
                    mma_latency_cycles = cycle_no - mma_start_cycle;
                    if (mma_latency_cycles == 0)
                        $fatal(1, "MXU_PERF: zero-latency MMA; check monitor boundary");
                    if (mma_latency_cycles != configured_k + 3)
                        $warning("MXU_PERF: expected K+3 latency for the inspected FSM; observed %0d for K=%0d. Check boundaries/source before ranking.", mma_latency_cycles, configured_k);
                    mma_active = 0;
                    mma_completed = 1;
                end
            end
        end
    end

    final begin
        if (frame_active)
            $display("[MXU_PERF_INCOMPLETE] case=%0d output_beats=%0d; do not use this run for performance ranking", case_no, output_beats);
    end
endmodule

bind mxu_tb mxu_perf_monitor u_mxu_perf_monitor (
    .clk(clk), .rst_n(rst_n),
    .op_type(op_type), .op_valid(op_valid), .op_ready(op_ready),
    .op_done(op_done), .cfg_Tk(cfg_Tk), .cfg_signed(cfg_signed),
    .weight_valid(weight_valid), .weight_ready(weight_ready),
    .act_valid(act_valid), .act_ready(act_ready),
    .result_valid(result_valid), .result_ready(result_ready)
);
