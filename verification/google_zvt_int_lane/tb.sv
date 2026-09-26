// Standalone functional smoke test for the unmodified Google Zvt integer PE lane.
// This is not a test of the complete Zvt matrix array or the full NPU core.
module zvt_int_lane_tb;
  logic clk = 1'b0;
  always #5 clk = ~clk;

  logic rst_n;
  logic up_valid;
  logic [0:0] reg_enable;
  logic [1:0] operand_signed;
  logic [1:0][31:0] operands;
  logic [3:0] mask;
  fpnew_pkg::int_format_e src_fmt;
  fpnew_pkg::int_format_e dst_fmt;
  logic [31:0] result;
  fpnew_pkg::status_t status;
  logic down_valid;
  integer passed = 0;

  zvt_pe_mulbulk_int_lane #(
    .WIDTH(32),
    .INT_FMT_CONFIG(2'b11),
    .NUM_MID_REGS(1)
  ) dut (
    .clk(clk),
    .rst_n(rst_n),
    .reg_enable(reg_enable),
    .up_valid(up_valid),
    .operand_signed(operand_signed),
    .operands(operands),
    .mask(mask),
    .src_fmt(src_fmt),
    .dst_fmt(dst_fmt),
    .result(result),
    .status(status),
    .down_valid(down_valid)
  );

  task automatic check_case(
    input logic [31:0] a,
    input logic [31:0] b,
    input logic [1:0] sign_mode,
    input logic [3:0] byte_mask,
    input logic [31:0] expected
  );
    begin
      @(negedge clk);
      operands[0] = a;
      operands[1] = b;
      operand_signed = sign_mode;
      mask = byte_mask;
      up_valid = 1'b1;
      @(posedge clk);
      #1;
      if (down_valid !== 1'b1 || result !== expected || status !== '0)
        $fatal(1, "case %0d: valid=%b result=%h expected=%h status=%h",
               passed + 1, down_valid, result, expected, status);
      $display("[PASS] case %0d: result=%h", passed + 1, result);
      passed = passed + 1;
      @(negedge clk);
      up_valid = 1'b0;
      @(posedge clk);
      #1;
      if (down_valid !== 1'b0)
        $fatal(1, "case %0d: output valid did not clear", passed);
    end
  endtask

  initial begin
    rst_n = 1'b0;
    up_valid = 1'b0;
    reg_enable = 1'b1;
    operand_signed = '0;
    operands = '0;
    mask = '0;
    src_fmt = fpnew_pkg::INT8;
    dst_fmt = fpnew_pkg::INT32;
    repeat (3) @(posedge clk);
    @(negedge clk);
    rst_n = 1'b1;

    // Four 200*3 products. All bytes are unsigned.
    check_case(32'hc8c8c8c8, 32'h03030303, 2'b00, 4'hf, 32'd2400);
    // The same data, with A signed: 4*(-56)*3 = -672.
    check_case(32'hc8c8c8c8, 32'h03030303, 2'b01, 4'hf, 32'hfffffd60);
    // Both operands signed: 4*(-128)*(-1) = 512.
    check_case(32'h80808080, 32'hffffffff, 2'b11, 4'hf, 32'd512);
    // Only byte lanes 0 and 2 are active: 1+3 = 4.
    check_case(32'h04030201, 32'h01010101, 2'b00, 4'b0101, 32'd4);

    $display("[SUMMARY] Google Zvt integer PE lane: %0d/4 passed", passed);
    $finish;
  end

  initial begin
    #10000;
    $fatal(1, "Zvt integer PE lane smoke test timed out");
  end
endmodule
