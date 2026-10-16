"""Read-only top-port AXI observer, sampling before the accepting edge."""
import cocotb
from cocotb.triggers import FallingEdge, ReadOnly, RisingEdge

from workset_spec import TrafficCounter


class WorksetAxiProbe:
    def __init__(self, dut, tiles):
        self.dut = dut
        self.counter = TrafficCounter(tiles)
        self.error = None
        self.task = None
        self.channels = {}
        fields = dict(read_addr=("addr", "size", "len", "id"),
                      write_addr=("addr", "size", "len", "id"),
                      read_data=("id", "last", "resp"),
                      write_data=("strb",), write_resp=("id", "resp"))
        for channel, names in fields.items():
            prefix = "io_axi_master_" + channel
            self.channels[channel] = (
                getattr(dut, prefix + "_valid"), getattr(dut, prefix + "_ready"),
                [getattr(dut, prefix + "_bits_" + name) for name in names])

    def start(self):
        assert self.task is None
        self.task = cocotb.start_soon(self._observe())

    async def _observe(self):
        try:
            while True:
                await FallingEdge(self.dut.io_aclk)
                await ReadOnly()
                sample = {name: tuple(int(value.value) for value in values)
                          for name, (valid, ready, values) in self.channels.items()
                          if int(valid.value) and int(ready.value)}
                await RisingEdge(self.dut.io_aclk)
                for channel, function in (("read_addr", self.counter.ar), ("write_addr", self.counter.aw),
                                          ("read_data", self.counter.r), ("write_data", self.counter.w),
                                          ("write_resp", self.counter.b)):
                    if channel in sample:
                        function(*sample[channel])
        except Exception as error:
            self.error = error

    def stop(self, expected):
        if self.task is not None:
            self.task.cancel()
            self.task = None
        if self.error is not None:
            raise AssertionError("AXI observer rejected run: " + str(self.error)) from self.error
        return self.counter.finish(expected)
