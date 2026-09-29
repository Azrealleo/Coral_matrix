`timescale 1ns/1ps

// Independent diagnostic only. All drives occur at negedge; result handshakes
// are scored at posedge before NBA. This does not modify the original mxu_tb.
module mxu_boundary_tb;
    reg clk = 0;
    always #5 clk = ~clk;
    reg rst_n = 0;
    reg [2:0] op_type = 0;
    reg op_valid = 0, uop_last = 0;
    wire op_ready, op_done;
    reg [7:0] cfg_Tk = 0;
    reg [127:0] weight_vec = 0, act_vec = 0;
    reg weight_valid = 0, act_valid = 0, result_ready = 1;
    wire weight_ready, act_ready, result_valid, mfence_done;
    wire [127:0] result_data;

    rvv_backend_mxu_unit dut (
        .clk(clk), .rst_n(rst_n), .op_type(op_type), .op_valid(op_valid),
        .op_ready(op_ready), .op_done(op_done), .uop_index(6'd0), .uop_last(uop_last),
        .cfg_Tk(cfg_Tk), .cfg_signed(1'b1), .weight_vec(weight_vec),
        .weight_valid(weight_valid), .weight_ready(weight_ready),
        .act_vec(act_vec), .act_valid(act_valid), .act_ready(act_ready),
        .result_data(result_data), .result_valid(result_valid),
        .result_ready(result_ready), .mfence_done(mfence_done)
    );

    reg [127:0] weights [0:255];
    reg [127:0] acts [0:255];
    reg [127:0] golden [0:63];
    integer K, input_gaps, output_stall;
    integer output_count = 0, pass_count = 0, fail_count = 0, cycles = 0;
    reg held = 0;
    reg [127:0] held_data;

    always @(posedge clk) begin
        cycles = cycles + 1;
        if (cycles > 40000) $fatal(1, "[MXU_BOUNDARY_TIMEOUT] K=%0d", K);
        if (!rst_n) begin
            output_count = 0; pass_count = 0; fail_count = 0; held = 0;
        end else begin
            // Standard ready/valid contract under test: valid and payload must
            // survive stalls. If an always-ready-only contract is intended,
            // a failure here diagnoses that unsupported integration feature.
            if (held && (result_valid !== 1'b1 || result_data !== held_data))
                $fatal(1, "[MXU_OUTPUT_STALL_FAIL] valid/data not held while ready=0");
            held = (result_valid === 1'b1 && result_ready === 1'b0);
            held_data = result_data;
            if (result_valid === 1'b1 && result_ready === 1'b1) begin
                if (output_count >= 64) $fatal(1, "Extra result handshake");
                if (result_data === golden[output_count]) pass_count = pass_count + 1;
                else begin
                    fail_count = fail_count + 1;
                    if (fail_count <= 3)
                        $display("[MXU_BOUNDARY_MISMATCH] beat=%0d got=%h expected=%h",
                                 output_count, result_data, golden[output_count]);
                end
                output_count = output_count + 1;
            end
        end
    end

    task automatic tick;
        begin @(posedge clk); #1; end
    endtask

    task automatic wait_command;
        begin while (op_ready !== 1'b1) @(negedge clk); end
    endtask

    task automatic simple_command(input [2:0] operation);
        reg done_seen;
        begin
            @(negedge clk); wait_command;
            op_type = operation; op_valid = 1; uop_last = 1;
            tick; done_seen = (op_done === 1'b1);
            @(negedge clk); op_valid = 0; uop_last = 0;
            while (!done_seen) begin tick; done_seen = (op_done === 1'b1); end
            @(negedge clk);
        end
    endtask

    task automatic load_input(input integer activation, input integer beats);
        integer i;
        reg done_seen;
        begin
            @(negedge clk); wait_command;
            op_type = activation ? 3'd2 : 3'd1;
            op_valid = 1; uop_last = (beats == 1);
            weight_valid = !activation; act_valid = activation;
            if (activation) act_vec = acts[0]; else weight_vec = weights[0];
            // First beat is accepted with the command even though stream-ready
            // is initially low. Only continuation beats use stream handshakes.
            tick; done_seen = (op_done === 1'b1);
            for (i = 1; i < beats; i = i + 1) begin
                @(negedge clk); op_valid = 0;
                weight_valid = 0; act_valid = 0; uop_last = 0;
                while ((activation ? act_ready : weight_ready) !== 1'b1)
                    @(negedge clk);
                if (input_gaps && (i % 3 == 1)) begin
                    repeat (2) begin tick; @(negedge clk); end
                end
                if (activation) act_vec = acts[i]; else weight_vec = weights[i];
                weight_valid = !activation; act_valid = activation;
                uop_last = (i == beats - 1);
                tick; done_seen = done_seen || (op_done === 1'b1);
            end
            @(negedge clk);
            op_valid = 0; weight_valid = 0; act_valid = 0; uop_last = 0;
            while (!done_seen) begin tick; done_seen = (op_done === 1'b1); end
            @(negedge clk);
        end
    endtask

    task automatic read_output;
        integer i;
        begin
            for (i = 0; i < 64; i = i + 1) begin
                @(negedge clk); wait_command;
                result_ready = !(output_stall && i == 0);
                op_type = 3'd5; op_valid = 1; uop_last = 1;
                tick;
                @(negedge clk); op_valid = 0; uop_last = 0;
                if (output_stall && i == 0) begin
                    repeat (3) begin tick; @(negedge clk); end
                    result_ready = 1;
                end
                // Check actual result_valid && result_ready, not op_done alone.
                while (output_count <= i) begin tick; @(negedge clk); end
            end
        end
    endtask

    initial begin
        if (!$value$plusargs("K=%d", K)) K = 16;
        if (!$value$plusargs("INPUT_GAPS=%d", input_gaps)) input_gaps = 0;
        if (!$value$plusargs("OUTPUT_STALL=%d", output_stall)) output_stall = 0;
        if (K < 1 || K > 256 || input_gaps < 0 || input_gaps > 1 ||
            output_stall < 0 || output_stall > 1) $fatal(1, "Invalid test parameters");
        $readmemh("weight.hex", weights);
        $readmemh("act.hex", acts);
        $readmemh("golden.hex", golden);
        $display("[MXU_BOUNDARY_START] K=%0d input_gaps=%0d output_stall=%0d", K, input_gaps, output_stall);
        repeat (5) tick;
        @(negedge clk); rst_n = 1;
        repeat (2) tick;
        @(negedge clk); cfg_Tk = (K == 256) ? 8'd0 : K;
        simple_command(3'd0);
        simple_command(3'd3);
        load_input(0, K);
        load_input(1, 16 * ((K + 15) / 16));
        simple_command(3'd4);
        read_output;
        repeat (2) tick;
        $display("[MXU_BOUNDARY_RESULT] K=%0d input_gaps=%0d output_stall=%0d beats=%0d pass=%0d fail=%0d",
                 K, input_gaps, output_stall, output_count, pass_count, fail_count);
        if (output_count != 64 || pass_count != 64 || fail_count != 0)
            $fatal(1, "MXU boundary golden mismatch");
        $display("[MXU_BOUNDARY_PASS] K=%0d input_gaps=%0d output_stall=%0d", K, input_gaps, output_stall);
        $finish;
    end
endmodule
