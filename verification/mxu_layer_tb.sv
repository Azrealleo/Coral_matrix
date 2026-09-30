`timescale 1ns/1ps

// Independent multi-pass tile diagnostic; original DUT and legacy TB unchanged.
module mxu_layer_tb;
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
    integer n_passes, k0, k1, k2, pass_k, pass_index;
    integer output_count = 0, pass_count = 0, fail_count = 0;
    integer cycles = 0, input_cycle = 0, final_cycle = 0;
    integer mma_cycle = 0, mma_sum_cycles = 0, mma_count = 0;
    bit mma_active = 0, mma_seen_low = 0;
    string tile_name, filename;

    always @(posedge clk) begin
        if (!rst_n) begin
            cycles = 0;
            output_count = 0;
            pass_count = 0;
            fail_count = 0;
            input_cycle = 0;
            mma_active = 0;
            mma_sum_cycles = 0;
            mma_count = 0;
        end else begin
            cycles = cycles + 1;
            if (cycles > 100000) $fatal(1, "MXU_LAYER_TIMEOUT");
            if (op_valid && op_ready && op_type == 3'd1 && input_cycle == 0)
                input_cycle = cycles;
            if (op_valid && op_ready && op_type == 3'd4) begin
                if (mma_active) $fatal(1, "MXU_LAYER: overlapping MMA");
                mma_cycle = cycles;
                mma_active = 1;
                mma_seen_low = 0;
            end
            if (result_valid && result_ready) begin
                if (output_count >= 64) $fatal(1, "MXU_LAYER: extra output");
                if (result_data === golden[output_count]) pass_count = pass_count + 1;
                else begin
                    fail_count = fail_count + 1;
                    if (fail_count <= 3)
                        $display("[MXU_LAYER_MISMATCH] beat=%0d got=%h expected=%h",
                                 output_count, result_data, golden[output_count]);
                end
                output_count = output_count + 1;
                if (output_count == 64) final_cycle = cycles;
            end
            #0.001;
            if (mma_active) begin
                if (op_done === 1'b0) mma_seen_low = 1;
                if (mma_seen_low && op_done === 1'b1) begin
                    mma_sum_cycles = mma_sum_cycles + cycles - mma_cycle;
                    mma_count = mma_count + 1;
                    mma_active = 0;
                end
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
            tick; done_seen = (op_done === 1'b1);
            for (i = 1; i < beats; i = i + 1) begin
                @(negedge clk); op_valid = 0;
                weight_valid = 0; act_valid = 0; uop_last = 0;
                while ((activation ? act_ready : weight_ready) !== 1'b1)
                    @(negedge clk);
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
                op_type = 3'd5; op_valid = 1; uop_last = 1;
                tick;
                @(negedge clk); op_valid = 0; uop_last = 0;
                while (output_count <= i) begin tick; @(negedge clk); end
            end
        end
    endtask

    initial begin
        if (!$value$plusargs("PASSES=%d", n_passes) ||
            !$value$plusargs("K0=%d", k0) ||
            !$value$plusargs("K1=%d", k1) ||
            !$value$plusargs("TILE=%s", tile_name))
            $fatal(1, "MXU_LAYER: missing plusargs");
        if (!$value$plusargs("K2=%d", k2)) k2 = 0;
        if (n_passes < 2 || n_passes > 3 ||
            k0 != 256 || k1 < 16 || k1 > 256 || k1 % 16 != 0 ||
            (n_passes == 3 && (k2 < 16 || k2 > 256 || k2 % 16 != 0)))
            $fatal(1, "MXU_LAYER: invalid K passes");
        $readmemh("golden.hex", golden);
        repeat (5) tick;
        @(negedge clk); rst_n = 1;
        repeat (2) tick;
        for (pass_index = 0; pass_index < n_passes; pass_index = pass_index + 1) begin
            pass_k = (pass_index == 0) ? k0 : ((pass_index == 1) ? k1 : k2);
            cfg_Tk = (pass_k == 256) ? 8'd0 : pass_k;
            simple_command(3'd0);
            if (pass_index == 0) simple_command(3'd3); // ONE clear per tile.
            filename = $sformatf("weight_%0d.hex", pass_index);
            $readmemh(filename, weights);
            filename = $sformatf("act_%0d.hex", pass_index);
            $readmemh(filename, acts);
            load_input(0, pass_k);
            load_input(1, pass_k);
            simple_command(3'd4);
        end
        read_output;
        repeat (2) tick;
        $display("[MXU_LAYER_RESULT] tile=%s passes=%0d beats=%0d pass=%0d fail=%0d mma_sum_cycles=%0d input_to_output_cycles=%0d",
                 tile_name, n_passes, output_count, pass_count, fail_count,
                 mma_sum_cycles, final_cycle - input_cycle + 1);
        if (output_count != 64 || pass_count != 64 || fail_count != 0 ||
            mma_count != n_passes || input_cycle == 0)
            $fatal(1, "MXU_LAYER: golden or timing mismatch");
        $display("[MXU_LAYER_PASS] tile=%s", tile_name);
        $finish;
    end
endmodule
